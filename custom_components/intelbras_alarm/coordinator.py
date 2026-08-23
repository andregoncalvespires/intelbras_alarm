"""Coordenador de atualização de dados da central de alarme Intelbras."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import protocol_legacy_eeprom as legacy_eeprom
from .const import (
    ACK_OK,
    AMT8000_ALL_PARTITIONS,
    AMT8000_EVENT_BUFFER_SIZE,
    AMT8000_MODE_ARM,
    AMT8000_MODE_DISARM,
    AMT8000_MODE_STAY,
    AMT8000_STATUS_MAX_LEN,
    AMT_8000_MODEL_NAME,
    CMD_EEPROM_READ,
    CONF_ENABLED_ZONES,
    CONF_LEGACY_EEPROM_PASSWORD,
    DEFAULT_CONNECTION_HEALTH_TIMEOUT,
    DEFAULT_ENABLED_ZONES_SPEC,
    DEFAULT_REQUEST_TIMEOUT,
    EEPROM_EXTENDED_MIN_FIRMWARE,
    EVENT_ENTITY_RECENT_COUNT,
    EVENT_LOG_BASE_ADDRESS,
    EVENT_LOG_CHUNK_BYTES,
    EVENT_LOG_TOTAL_BYTES,
    EVENT_RECORD_LEN,
    FAMILY_2018,
    FAMILY_4010,
    FAMILY_8000,
    FAMILY_MAX_ZONES,
    FAMILY_STATUS_CMD,
    FAMILY_STATUS_LEN,
    InvalidZoneSpec,
    MODEL_AMT_8000,
    MODEL_TABLE,
    MODEL_UNKNOWN,
    PGM_ADDRESSES,
    RECEPTOR_IP_EVENT_TABLE,
    ZONE_NAME_BASE_ADDRESS,
    ZONE_NAME_MAX_READ,
    ZONE_NAME_RECORD_LEN,
    parse_zone_spec,
)
from .panel_client import PanelClient, PanelConnectionError
from .panel_client_amt8000 import Amt8000AuthError, PanelConnectionErrorAmt8000
from . import protocol_amt8000 as amt8000
from .protocol import (
    NackError,
    PanelStatus,
    ParsedFrame,
    build_command,
    checksum,
    cmd_arm,
    cmd_bypass,
    cmd_disarm,
    cmd_eeprom_read,
    cmd_panic,
    cmd_pgm,
    cmd_siren,
    decode_zone_names,
    parse_event_record,
    parse_hex_bytes,
    parse_status,
    raise_for_ack,
)

_LOGGER = logging.getLogger(__name__)

# Erros de conexão possíveis vindos de QUALQUER um dos dois clients (o
# ISECMobile normal ou o experimental da AMT 8000) — usado nos pontos do
# coordinator que ainda não sabem (ou não precisam saber) qual família
# está em uso, só que a comunicação falhou.
_ANY_PANEL_CONNECTION_ERROR = (PanelConnectionError, PanelConnectionErrorAmt8000, Amt8000AuthError)


class IntelbrasAlarmCoordinator(DataUpdateCoordinator[PanelStatus]):
    """Consulta o status da central periodicamente e expõe comandos de alto nível."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PanelClient,
        password: str,
        family: str,
        model_key: str,
        partition_passwords: dict[str, str] | None = None,
    ) -> None:
        self.entry = entry
        self.client = client
        self._password = password
        # Senhas específicas por partição (4010, opcional — ver
        # config_flow.py). Partições sem senha própria configurada caem na
        # senha principal (ver `password_for_partition`).
        self._partition_passwords = partition_passwords or {}
        self.family = family
        self.model_key = model_key
        # Senha opcional de leitura de mensagens (0xE7 + identificação),
        # ver protocol_legacy_eeprom.py e supports_legacy_eeprom abaixo.
        # Em branco por padrão -- só habilita a funcionalidade se o
        # usuário preencher explicitamente na configuração. Não se
        # aplica à AMT 8000 (ver supports_legacy_eeprom).
        self._legacy_eeprom_password: str | None = entry.data.get(
            CONF_LEGACY_EEPROM_PASSWORD
        ) or None
        self.zone_names: dict[int, str] = {}
        # Eventos mais recentes já lidos (limitado a
        # EVENT_ENTITY_RECENT_COUNT, ordenados do mais novo pro mais
        # velho por data/hora real do registro — NÃO pela ordem de
        # endereço, que não corresponde à ordem cronológica, confirmado
        # em campo). O serviço de leitura devolve a lista completa (até
        # 256) na resposta; só o que fica aqui, nos atributos da
        # entidade, é truncado.
        self.recent_events: list[dict] = []
        # Último evento recebido via Receptor IP (empurrado pela própria
        # central, tempo real — diferente de recent_events, que vem da
        # leitura sob demanda da EEPROM). None enquanto o recurso estiver
        # desligado ou nenhum evento tiver chegado ainda.
        self.receptor_last_event: dict | None = None
        # Data/hora (deste servidor Home Assistant, não da central) do
        # último sinal de vida recebido do Receptor IP — heartbeat (0xF7)
        # ou qualquer evento, o que chegar primeiro/depois.
        self.receptor_last_heartbeat: datetime | None = None
        # Rastreamento local do modo de ativação (stay/away), pois o status
        # da central não informa o modo, apenas se está ativada ou não.
        self.armed_home_mode: dict[str, bool] = {"CENTRAL": False, "A": False, "B": False, "C": False, "D": False}
        # Descrição textual do resultado do último comando enviado (ACK/NACK),
        # útil como diagnóstico (ex.: "Senha incorreta"), exposta pelo sensor
        # "Último comando".
        self.last_command_result: str | None = None
        # Bytes brutos (hex) da última resposta de status completa recebida
        # no polling — sugestão do usuário: dá pra ver a sequência inteira
        # sem precisar de log, como atributo do sensor "Último comando".
        self.last_status_raw: str | None = None
        # Os três campos abaixo só são atualizados por comandos REAIS
        # (armar, desarmar, PGM, sirene, pânico, bypass) — nunca pela
        # consulta de status, que roda a cada ciclo de polling (0,25s por
        # padrão) e sobrescreveria os valores rápido demais para dar tempo
        # de analisar. Mantidos separados de propósito, a pedido do
        # usuário, para permitir inspecionar com calma qual foi o último
        # comando de verdade (não a consulta de status) e sua resposta.
        self.last_command_action: str | None = None  # finalidade/nome, ex. "Ativar Partição A"
        self.last_command_frame_hex: str | None = None  # bytes do comando enviado
        self.last_command_response_hex: str | None = None  # bytes da resposta a esse comando

        # Marca de tempo (monotônica, imune a ajuste de relógio do sistema)
        # da última consulta de status bem-sucedida — usada só para decidir
        # se uma falha de consulta é "tolerada" (dentro da janela de saúde
        # da conexão) ou se já vira indisponibilidade de verdade. Ver
        # _async_update_data(). None só antes da primeira consulta bem-
        # sucedida desde que a integração carregou.
        self._last_poll_success_monotonic: float | None = None
        # Evita logar a MESMA falha repetidamente a cada ciclo de polling
        # (0,25s por padrão) enquanto ela persistir — sem isso, deixar a
        # central offline (ou o switch desligado) por muito tempo gera
        # milhões de linhas de log idênticas, incha o banco do recorder e
        # pode inutilizar o Home Assistant (caso real relatado pelo
        # usuário: 12 milhões de linhas em ~35 dias, banco de 16GB). Só
        # registra a falha UMA VEZ ao virar definitiva, e a recuperação
        # (quando volta a funcionar) também só uma vez.
        self._poll_failure_logged = False
        # Idem, mas específico para "switch de conexão desligado" — esse
        # caso nem tenta se comunicar com a central (ver
        # _async_update_data), só precisa de um log próprio na transição.
        self._disabled_logged = False

        # Zonas que nascem habilitadas por padrão no Home Assistant,
        # configurável pelo usuário na inclusão da integração (formato
        # "1-8;17-24" — ver const.parse_zone_spec). Um valor mal formatado
        # não deveria acontecer (validado no config_flow), mas por
        # segurança cai no padrão em vez de quebrar a integração.
        try:
            self._enabled_zones = parse_zone_spec(
                entry.data.get(CONF_ENABLED_ZONES, DEFAULT_ENABLED_ZONES_SPEC)
            )
        except InvalidZoneSpec:
            _LOGGER.warning(
                "Especificação de zonas habilitadas inválida em '%s'; usando padrão '%s'",
                entry.data.get(CONF_ENABLED_ZONES),
                DEFAULT_ENABLED_ZONES_SPEC,
            )
            self._enabled_zones = parse_zone_spec(DEFAULT_ENABLED_ZONES_SPEC)

        super().__init__(
            hass,
            _LOGGER,
            name=f"Intelbras Alarm ({entry.title})",
            update_interval=timedelta(seconds=entry.options.get("polling_interval", 0.25)),
        )
        # Guardado à parte pra poder restaurar depois de pause_polling()
        # (ver logo abaixo) — self.update_interval pode ser zerado
        # temporariamente, então precisamos lembrar o valor de verdade.
        self._configured_polling_interval = self.update_interval

    def pause_polling(self) -> None:
        """Interrompe por completo o agendamento automático de consultas.

        BUG REAL corrigido em `main` (relatado em produção, agosto/2026),
        equiparado aqui: antes desta correção, desligar o switch "Conexão
        com a central" só fazia cada *tentativa* de consulta falhar rápido
        (``UpdateFailed``, sem tentar se comunicar de verdade) — mas o
        **agendador** do próprio `DataUpdateCoordinator` (Home Assistant
        core) continuava se reagendando sozinho, chamando
        `_async_update_data()` de novo e de novo. Como cada tentativa
        desabilitada termina em ~0,000s, isso criava um laço apertadíssimo
        (chegou a **milhares de chamadas por segundo**, confirmado em log
        real), consumindo CPU à toa mesmo sem nenhuma tentativa de
        comunicação de rede — só o próprio custo de Python de levantar a
        exceção, formatar o log de debug do HA core ("Finished fetching...
        success: False", gerado pelo próprio `update_coordinator.py`, não
        por nós) e reagendar, repetidamente.

        A correção: `update_interval = None` faz o agendador do HA core
        (`_schedule_refresh()`) simplesmente **não agendar mais nada**
        (`if self._update_interval_seconds is None: return`) — não é
        "tentar rápido e falhar", é "não tentar mais até alguém pedir".
        Chamado tanto ao desligar o switch manualmente (`switch.py`) quanto
        na inicialização, se a integração já subir com o switch desligado
        (`__init__.py`) — nesse segundo caso, sem isso, o primeiro listener
        adicionado (`async_add_listener`, quando as entidades são criadas)
        já dispararia um agendamento normal antes de qualquer consulta
        sequer ter rodado uma vez.

        Vale igualmente para `_async_update_data()` e
        `_async_update_data_amt8000()` — o agendamento é um só, do
        coordinator, independente de qual família de central está em uso.
        """
        self.update_interval = None

    def resume_polling(self) -> None:
        """Restaura o intervalo de consulta configurado, depois de pause_polling().

        Não dispara uma consulta sozinho — quem chama continua responsável
        por pedir um ciclo nova (``await coordinator.async_request_refresh()``),
        exatamente como já era feito ao religar o switch.
        """
        self.update_interval = self._configured_polling_interval

    @property
    def max_zones(self) -> int:
        """Nº de zonas cobertas pelos bytes de status (limite do protocolo)."""
        return FAMILY_MAX_ZONES[self.family]

    @property
    def native_zone_count(self) -> int:
        """Nº de zonas do modelo detectado — usado para criar as entidades.

        Definido automaticamente a partir do modelo identificado na
        configuração; não é ajustável pelo usuário. Caso a instalação tenha
        expansoras de zona além do nativo do modelo, ajuste
        ``MODEL_TABLE`` em ``const.py``.
        """
        from .const import MODEL_ZONE_COUNT

        return MODEL_ZONE_COUNT.get(self.model_key, self.max_zones)

    @property
    def pgm_count(self) -> int:
        from .const import FAMILY_PGM_COUNT

        return FAMILY_PGM_COUNT[self.family]

    @property
    def supports_extended_eeprom(self) -> bool:
        """Se este modelo/firmware tem acesso ao comando 0x5C para ler
        nomes de zona e o log de eventos via EEPROM.

        Extraído literalmente da tela de ajuda "Senha Acesso Remoto" do
        app oficial AMT Mobile: ela lista exatamente quais centrais NÃO
        precisam dessa senha adicional para sincronizar nomes/eventos —
        e, por extensão, são as que têm esse caminho (0x5C) liberado.

        Fora dessa lista, ver ``supports_legacy_eeprom`` abaixo — essas
        centrais usam um protocolo diferente (comando 0xE7 +
        identificação por senha de 6 dígitos), implementado
        separadamente em ``protocol_legacy_eeprom.py``.
        """
        if self.family == FAMILY_8000:
            # A AMT 8000 lê nomes/eventos por um comando próprio (ver
            # protocol_amt8000.py), sem a complexidade de limiar de
            # firmware do comando 0x5C legado — sempre disponível nesta
            # família, independente de self.data já ter chegado ou não.
            return True
        if self.data is None:
            return False
        if self.model_key not in EEPROM_EXTENDED_MIN_FIRMWARE:
            return False
        minimo = EEPROM_EXTENDED_MIN_FIRMWARE[self.model_key]
        if minimo is None:
            return True
        try:
            major_str, minor_str = self.data.firmware.split(".")
            atual = (int(major_str), int(minor_str))
        except (ValueError, AttributeError):
            return False
        return atual >= minimo

    @property
    def supports_legacy_eeprom(self) -> bool:
        """Se esta central pode ler nomes de zona/usuário e eventos pelo
        protocolo legado (comando ``0xE7`` + identificação por senha de
        6 dígitos, ``protocol_legacy_eeprom.py``) — alternativa ao
        ``0x5C`` para os modelos/firmwares fora da lista de
        ``supports_extended_eeprom``.

        Requer duas condições: (1) o modelo/firmware realmente **não**
        tem acesso ao ``0x5C`` (senão, o caminho moderno é sempre
        preferido) e (2) a senha de 6 dígitos foi configurada
        explicitamente (``const.CONF_LEGACY_EEPROM_PASSWORD``) — em
        branco por padrão, funcionalidade desligada até o usuário optar
        por ativá-la.

        Não se aplica à AMT 8000 automaticamente: como
        ``supports_extended_eeprom`` já retorna ``True`` incondicionalmente
        para ``FAMILY_8000`` (comando próprio, sem limiar de firmware),
        a primeira condição abaixo já exclui essa família sem precisar
        de checagem extra.

        Confirmado funcionando em hardware real (AMT 1016 NET, firmware
        3.1) — ver docstring de ``protocol_legacy_eeprom.py`` para os
        detalhes da validação.
        """
        if self.supports_extended_eeprom:
            return False
        return self._legacy_eeprom_password is not None

    def zone_enabled_by_default(self, zone: int) -> bool:
        """Se a zona deve nascer habilitada no registro de entidades.

        Configurável pelo usuário na inclusão da integração (ver
        ``const.CONF_ENABLED_ZONES``); ``const.DEFAULT_ENABLED_ZONES_SPEC``
        é usado se não informado.
        """
        return zone in self._enabled_zones

    @property
    def supports_stay(self) -> bool:
        """Se este modelo suporta de verdade o comando de ativação em modo Stay.

        Confirmado pelo usuário: só a 4010 e a 2018 E SMART respondem
        corretamente ao comando 0x50 — nos demais modelos da família 2018
        (E/EG, 1016 NET, AMN 24 NET) o comando existe no protocolo mas a
        central não implementa esse modo. Usado para remover a opção
        `armed_home` da UI nesses modelos (ver alarm_control_panel.py).
        """
        from .const import MODELS_SUPPORTING_STAY

        return self.model_key in MODELS_SUPPORTING_STAY

    @property
    def password(self) -> str:
        """Senha ISECMobile principal, usada para validar códigos digitados na UI."""
        return self._password

    async def async_validate_password(self, password: str) -> None:
        """Testa uma senha candidata reaproveitando a conexão persistente
        já aberta com a central — usada pela tela de "Configurar" (opções)
        para confirmar uma nova senha antes de salvar.

        Importante: **não abre uma segunda conexão TCP** para testar —
        muitos modelos (confirmado em campo) só aceitam um cliente
        conectado por vez, o mesmo motivo pelo qual o app AMT Remoto
        conectado ao mesmo tempo já causou falha de conexão nesta
        integração antes. Em vez disso, monta um comando de consulta de
        status com a senha candidata e envia pela conexão já existente —
        o protocolo ISECMobile leva a senha em cada frame individual, não
        na conexão TCP em si, então isso funciona sem desconectar nada.

        Levanta ``NackError`` (ex.: "Senha incorreta") se a central
        rejeitar, ou ``PanelConnectionError`` se a conexão atual não
        estiver disponível.
        """
        if self.family == FAMILY_8000:
            await self._async_validate_password_amt8000(password)
            return
        frame = _build_status_frame(password, self.family)
        response = await self.client.send_command(frame, context="validar nova senha")
        # Uma resposta de status completa (43 ou 54 bytes, conforme a
        # família) já confirma que a senha foi aceita. Não usamos
        # raise_for_ack() nesse caso: o primeiro byte de um status
        # completo (zonas abertas 1-8) pode coincidentemente bater com um
        # código de NACK sem ser erro nenhum. Só tratamos como ACK/NACK
        # quando a resposta é curta (1-2 bytes), como a central realmente
        # usa para confirmar/rejeitar comandos.
        if len(response.content) in (43, 54):
            return
        raise_for_ack(response)

    async def _async_validate_password_amt8000(self, password: str) -> None:
        """Testa uma senha candidata para a AMT 8000.

        Diferente do ISECMobile (senha embutida em cada frame), a AMT
        8000 autentica a **conexão inteira** uma única vez (ver
        protocol_amt8000.py) — não dá pra "testar" uma senha nova sem
        reautenticar. Estratégia: desconecta a sessão atual e tenta
        reconectar/reautenticar com a senha candidata; se falhar,
        restaura a senha original e reconecta antes de propagar o erro,
        para não deixar a integração sem conexão só por causa de um
        teste de senha malsucedido.

        ⚠️ Ainda não confirmado se a central aceita uma segunda conexão
        simultânea de outro cliente enquanto esta reconecta — se isso se
        mostrar um problema em campo, esta função pode precisar de
        ajuste (ver mesma ressalva já documentada para o ISECMobile).
        """
        original_password = self.client._password  # noqa: SLF001 — ver docstring
        try:
            await self.client.disconnect()
            self.client._password = password  # noqa: SLF001
            await self.client.connect()
        except Amt8000AuthError:
            self.client._password = original_password  # noqa: SLF001
            try:
                await self.client.connect()
            except _ANY_PANEL_CONNECTION_ERROR:
                pass
            raise

    def password_for_partition(self, partition: str | None) -> str:
        """Senha a usar para armar/desarmar uma partição específica.

        Se a partição tiver uma senha própria configurada (só possível na
        4010, ver config_flow.py), ela é usada; senão, cai na senha
        principal. Para ``partition=None`` (comando dirigido à central,
        sem especificar partição), sempre usa a senha principal.
        """
        if partition is None:
            return self._password
        return self._partition_passwords.get(partition) or self._password

    async def _async_update_data(self) -> PanelStatus:
        if not self.client.enabled:
            # Switch "Conexão com a central" desligado deliberadamente pelo
            # usuário — CASO CRÍTICO (bug real relatado em produção): antes
            # desta correção, o coordinator continuava tentando e logando
            # ERROR a cada ciclo de polling (0,25s) indefinidamente enquanto
            # o switch ficasse desligado, gerando milhões de linhas de log
            # idênticas em poucas semanas e inchando o banco do recorder em
            # vários GB. Agora: nenhuma tentativa de comunicação sequer é
            # feita (nem chega a chamar send_command), e o log da transição
            # para esse estado só acontece UMA VEZ, não a cada ciclo.
            if not self._disabled_logged:
                _LOGGER.info(
                    'Comunicação com a central desativada (switch "Conexão com a '
                    'central" desligado) — pausando consultas até ser reativado, '
                    "sem tentar se comunicar nem repetir este log enquanto durar"
                )
                self._disabled_logged = True
            raise UpdateFailed("Comunicação com a central está desativada")

        if self._disabled_logged:
            _LOGGER.info('Switch "Conexão com a central" reativado — retomando consultas')
            self._disabled_logged = False

        if self.family == FAMILY_8000:
            return await self._async_update_data_amt8000()

        try:
            response = await self.client.send_command(
                _build_status_frame(self._password, self.family), context="consulta de status"
            )
            if not response.valid_checksum:
                raise UpdateFailed("Checksum inválido na resposta de status")

            # Discutido e decidido explicitamente com o usuário (mesma decisão
            # aplicada em main): uma resposta de tamanho errado NÃO é mais
            # aceita como status válido (mesmo que protocol.py consiga "ler"
            # ela de forma defensiva, com zero/False nos campos ausentes) —
            # isso já causou risco real de a integração aplicar um valor
            # ERRADO numa entidade por um ciclo (ex.: uma zona aberta
            # aparecendo como fechada), podendo disparar automações por
            # engano. Em vez disso, tratamos como falha de leitura, igual a
            # uma queda de conexão: cai no mesmo mecanismo de tolerância de
            # _handle_poll_failure() (silencioso se isolado, dentro dos 8s
            # de tolerância; escala pra indisponível de verdade só se
            # persistir) — nenhuma entidade muda de valor por causa de uma
            # leitura isolada incompleta.
            expected_len = FAMILY_STATUS_LEN.get(self.family)
            if expected_len is not None and len(response.content) != expected_len:
                raise UpdateFailed(
                    f"Resposta de status com tamanho inesperado para {self.family}: "
                    f"recebidos {len(response.content)} bytes, esperados {expected_len} "
                    f"— a central pode ter um firmware com comportamento incorreto "
                    f"(ver README, seção de modelos testados). Conteúdo recebido: "
                    f"{response.content.hex(' ').upper()}"
                )

            status = parse_status(response.content, self.family)
        except (PanelConnectionError, UpdateFailed, IndexError, ValueError) as err:
            self._handle_poll_failure(err)
            # _handle_poll_failure() levanta UpdateFailed se a falha não for
            # tolerável (ver docstring dela) — se chegou até aqui, a falha
            # foi tolerada: mantém e devolve o último dado bom conhecido,
            # sem marcar as entidades como indisponíveis por causa de um
            # soluço isolado e passageiro da central.
            if self.data is not None:
                return self.data
            # Nunca teve um dado bom — não há o que "tolerar", teria que
            # inventar um status vazio. _handle_poll_failure() já deveria
            # ter levantado UpdateFailed nesse caso (ver lá), mas por
            # segurança levanta aqui também.
            raise UpdateFailed(str(err)) from err

        # Sucesso: reseta a marca de tempo de "última consulta boa", usada
        # pela lógica de tolerância acima. Se estava marcado como falho,
        # avisa UMA VEZ que voltou a funcionar (pedido explícito do
        # usuário — sem isso, uma queda real vira indisponibilidade
        # silenciosa até alguém checar manualmente).
        if self._poll_failure_logged:
            elapsed = (
                time.monotonic() - self._last_poll_success_monotonic
                if self._last_poll_success_monotonic is not None
                else 0.0
            )
            _LOGGER.warning(
                "Comunicação com a central reestabelecida (ficou sem responder por "
                "cerca de %.1fs)",
                elapsed,
            )
            self._poll_failure_logged = False
        self._last_poll_success_monotonic = time.monotonic()

        # Log de diagnóstico do status bruto recebido a cada polling — é o
        # que permite comparar, byte a byte, o comportamento real da
        # central com a lógica de armed/triggered em alarm_control_panel.py.
        # Só produz saída com o logger desta integração em nível DEBUG
        # (ver README, seção "Diagnóstico").
        _LOGGER.debug(
            "status recebido: conteúdo=%s | activated(central)=%s partitions_armed=%s "
            "zone_triggered=%s siren_on=%s problem=%s",
            response.content.hex(" ").upper(),
            status.activated,
            status.partitions_armed,
            status.zone_triggered,
            status.siren_on,
            status.problem,
        )
        self.last_status_raw = response.content.hex(" ").upper()

        return status

    async def _async_update_data_amt8000(self) -> PanelStatus:
        """Consulta de status para a família AMT 8000 (protocolo próprio).

        EXPERIMENTAL — ver protocol_amt8000.py e README_DETALHADO.md.
        Reaproveita a mesma lógica de tolerância a falha isolada
        (`_handle_poll_failure`) e a mesma dataclass `PanelStatus` das
        demais famílias, para que as entidades (sensor/binary_sensor/
        switch) funcionem sem qualquer alteração — ver
        `protocol_amt8000.parse_status`.
        """
        try:
            response = await self.client.send_command(
                amt8000.cmd_status(), context="consulta de status (AMT 8000)"
            )
            if not response.valid_checksum:
                raise UpdateFailed("Checksum inválido na resposta de status (AMT 8000)")

            # Equiparação com a mesma proteção aplicada às demais famílias
            # (ver _async_update_data acima) — com um critério ainda um
            # pouco mais cauteloso que FAMILY_STATUS_LEN: AMT8000_STATUS_MAX_LEN
            # (143 bytes, só o conteúdo — response.content já vem sem
            # cabeçalho/opcode/checksum) agora é um valor CONFIRMADO em
            # hardware real (projeto de terceiros
            # fdaneluzzi/homeassistant-amt8000, cruzado com nossa análise),
            # não mais uma estimativa — mas os OFFSETS dos campos dentro
            # desse conteúdo continuam sem validação própria (protocolo
            # ainda experimental). Por isso mantemos a margem de 50%, em
            # vez de comparação exata: pega qualquer truncamento claro sem
            # arriscar rejeitar uma resposta válida por uma diferença
            # pequena entre modelos/firmwares que ainda não vimos.
            if len(response.content) < (AMT8000_STATUS_MAX_LEN // 2):
                raise UpdateFailed(
                    f"Resposta de status da AMT 8000 muito curta: recebidos "
                    f"{len(response.content)} bytes, esperado {AMT8000_STATUS_MAX_LEN} "
                    f"(conteúdo, sem framing). Conteúdo recebido: "
                    f"{response.content.hex(' ').upper()}"
                )

            status = amt8000.parse_status(response.content)
        except (*_ANY_PANEL_CONNECTION_ERROR, UpdateFailed, IndexError, ValueError) as err:
            self._handle_poll_failure(err)
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(err)) from err

        if self._poll_failure_logged:
            elapsed = (
                time.monotonic() - self._last_poll_success_monotonic
                if self._last_poll_success_monotonic is not None
                else 0.0
            )
            _LOGGER.warning(
                "Comunicação com a central AMT 8000 reestabelecida (ficou sem "
                "responder por cerca de %.1fs)",
                elapsed,
            )
            self._poll_failure_logged = False
        self._last_poll_success_monotonic = time.monotonic()

        _LOGGER.debug(
            "AMT 8000 status recebido: conteúdo=%s | activated=%s partitions_armed=%s "
            "zone_triggered=%s siren_on=%s problem=%s",
            response.content.hex(" ").upper(),
            status.activated,
            status.partitions_armed,
            status.zone_triggered,
            status.siren_on,
            status.problem,
        )
        self.last_status_raw = response.content.hex(" ").upper()
        return status

    def _handle_poll_failure(self, err: Exception) -> None:
        """Decide se uma falha de CONSULTA DE STATUS é tolerada ou definitiva.

        Só se aplica à consulta de status periódica quando o switch de
        conexão está LIGADO (o caso de switch desligado é tratado à parte,
        no início de ``_async_update_data``, e nunca chega aqui). Comandos
        reais (armar, desarmar, PGM, etc.) também nunca passam por aqui,
        sempre falham de forma imediata e visível (ver ``_send_and_check``),
        porque são ações que o usuário pediu explicitamente e precisam de
        feedback rápido, não silêncio tolerado.

        Tolerância: se o tempo desde a última consulta bem-sucedida ainda
        está dentro de ``DEFAULT_CONNECTION_HEALTH_TIMEOUT`` (8s por
        padrão), a falha vira só um aviso no log — as entidades continuam
        "disponíveis", mostrando o último dado bom conhecido, e a próxima
        tentativa (0,25s depois, por padrão) tenta de novo normalmente.
        Isso evita marcar tudo como indisponível por causa de um soluço
        isolado (ex.: o bug do firmware 6.2 documentado no README).

        Levanta ``UpdateFailed`` (marcando as entidades como indisponíveis
        de verdade) quando: nunca houve nenhuma consulta bem-sucedida
        ainda, ou o silêncio acumulado já ultrapassou a janela de
        tolerância — nesse ponto, o problema não parece mais passageiro.

        IMPORTANTE (correção de um bug real de produção): a falha só é
        REGISTRADA NO LOG uma vez, na transição para o estado "indisponível"
        — enquanto continuar falhando, os ciclos seguintes levantam
        ``UpdateFailed`` normalmente (as entidades continuam indisponíveis,
        como devem) mas SEM gerar uma nova linha de log a cada 0,25s. Sem
        essa supressão, uma central genuinamente offline por dias/semanas
        gera milhões de linhas de log idênticas, inchando o banco do
        `recorder` em vários GB — caso real relatado em produção.
        """
        now = time.monotonic()
        if self._last_poll_success_monotonic is None:
            if not self._poll_failure_logged:
                _LOGGER.error(
                    "Falha na consulta de status (nenhuma comunicação bem-sucedida "
                    "ainda): %s — próximas falhas iguais não serão repetidas no log "
                    "até a comunicação normalizar",
                    err,
                )
                self._poll_failure_logged = True
            raise UpdateFailed(str(err)) from err

        elapsed = now - self._last_poll_success_monotonic
        if elapsed >= DEFAULT_CONNECTION_HEALTH_TIMEOUT:
            if not self._poll_failure_logged:
                _LOGGER.error(
                    "Falha na consulta de status: %s (sem comunicação bem-sucedida há "
                    "%.1fs, acima da tolerância de %ds — marcando como indisponível; "
                    "próximas falhas iguais não serão repetidas no log até a "
                    "comunicação normalizar)",
                    err,
                    elapsed,
                    DEFAULT_CONNECTION_HEALTH_TIMEOUT,
                )
                self._poll_failure_logged = True
            raise UpdateFailed(str(err)) from err

        _LOGGER.warning(
            "Falha isolada na consulta de status (tolerada, %.1fs desde a última com "
            "sucesso, dentro do limite de %ds): %s",
            elapsed,
            DEFAULT_CONNECTION_HEALTH_TIMEOUT,
            err,
        )

    # ------------------------------------------------------------------
    # Comandos de alto nível usados pelas entidades
    # ------------------------------------------------------------------
    async def async_arm(self, partition: str | None, stay: bool, password: str | None = None) -> None:
        if self.family == FAMILY_8000:
            mode = AMT8000_MODE_STAY if stay else AMT8000_MODE_ARM
            partition_num = int(partition) if partition is not None else AMT8000_ALL_PARTITIONS
            frame = amt8000.cmd_arm_disarm(partition_num, mode)
            label = f"Ativar {_partition_label(partition)}" + (" (Stay)" if stay else "")
            await self._send_and_check_amt8000(frame, label)
            key = partition or "CENTRAL"
            self.armed_home_mode[key] = stay
            await self.async_request_refresh()
            return
        code = None if partition is None else _partition_code(partition)
        frame = cmd_arm(password or self._password, code, stay=stay)
        label = f"Ativar {_partition_label(partition)}" + (" (Stay)" if stay else "")
        await self._send_and_check(frame, label)
        key = partition or "CENTRAL"
        self.armed_home_mode[key] = stay
        await self.async_request_refresh()

    async def async_disarm(self, partition: str | None, password: str | None = None) -> None:
        if self.family == FAMILY_8000:
            partition_num = int(partition) if partition is not None else AMT8000_ALL_PARTITIONS
            frame = amt8000.cmd_arm_disarm(partition_num, AMT8000_MODE_DISARM)
            label = f"Desativar {_partition_label(partition)}"
            await self._send_and_check_amt8000(frame, label)
            key = partition or "CENTRAL"
            self.armed_home_mode[key] = False
            await self.async_request_refresh()
            return
        code = None if partition is None else _partition_code(partition)
        frame = cmd_disarm(password or self._password, code)
        label = f"Desativar {_partition_label(partition)}"
        await self._send_and_check(frame, label)
        key = partition or "CENTRAL"
        self.armed_home_mode[key] = False
        await self.async_request_refresh()

    async def async_set_pgm(self, address: int, turn_on: bool, pgm: int | None = None) -> None:
        if self.family == FAMILY_8000:
            if pgm is None:
                raise HomeAssistantError("PGM não informada (interno) — AMT 8000 endereça PGM por número")
            frame = amt8000.cmd_pgm(pgm, turn_on)
            label = f"{'Ligar' if turn_on else 'Desligar'} PGM {pgm}"
            await self._send_and_check_amt8000(frame, label)
            await self.async_request_refresh()
            return
        frame = cmd_pgm(self._password, address, turn_on)
        pgm_label = f"PGM {pgm}" if pgm is not None else f"PGM (endereço 0x{address:02X})"
        label = f"{'Ligar' if turn_on else 'Desligar'} {pgm_label}"
        await self._send_and_check(frame, label)
        await self.async_request_refresh()

    async def async_set_siren(self, turn_on: bool) -> None:
        if self.family == FAMILY_8000:
            # Nenhum comando dedicado de liga/desliga sirene foi
            # encontrado no app oficial para a AMT 8000 (só o estado da
            # sirene é reportado no status) — ver README_DETALHADO.md.
            # A entidade switch.py não cria este switch para esta
            # família (ver switch.py), então este ramo não deveria ser
            # alcançável na prática; existe só como salvaguarda.
            raise HomeAssistantError(
                "Controle direto de sirene ainda não é suportado na AMT 8000 nesta integração"
            )
        frame = cmd_siren(self._password, turn_on)
        label = "Ligar sirene" if turn_on else "Desligar sirene"
        await self._send_and_check(frame, label)
        await self.async_request_refresh()

    async def async_panic(self, kind: int) -> None:
        if self.family == FAMILY_8000:
            frame = amt8000.cmd_panic(kind)
            label = f"Pânico ({_PANIC_LABELS.get(kind, f'0x{kind:02X}')})"
            await self._send_and_check_amt8000(frame, label)
            return
        frame = cmd_panic(self._password, kind)
        label = f"Pânico ({_PANIC_LABELS.get(kind, f'0x{kind:02X}')})"
        await self._send_and_check(frame, label)

    async def async_bypass_zones(self, zones_to_bypass: set[int], *, replace: bool = False) -> None:
        """Anula (bypass) as zonas indicadas.

        Na AMT 8000 (``self.family == FAMILY_8000``), o comando é
        individual por zona (ver ``protocol_amt8000.cmd_bypass``) — cada
        zona do conjunto é anulada com uma chamada própria, sem o
        conceito de "comando absoluto sobre as 64 zonas" das demais
        famílias; ``replace`` não se aplica nesse caso (não há zonas
        "fora do conjunto" para desanular implicitamente).

        Nas demais famílias, o comando 0x42 é absoluto (define o estado
        de anulação de todas as 64 zonas do protocolo de uma vez). Por
        padrão (``replace=False``), as zonas já anuladas na última
        leitura de status são preservadas — o comando enviado é a união
        entre o que já estava anulado e ``zones_to_bypass``. Use
        ``replace=True`` para enviar exatamente o conjunto informado
        (desanulando qualquer zona fora dele).
        """
        if self.family == FAMILY_8000:
            for zone in sorted(zones_to_bypass):
                frame = amt8000.cmd_bypass(zone, True)
                await self._send_and_check_amt8000(frame, f"Anular zona {zone}")
            await self.async_request_refresh()
            return

        target = set(zones_to_bypass)
        if not replace and self.data is not None:
            target |= {zone for zone, bypassed in self.data.zones_bypassed.items() if bypassed}
        _LOGGER.debug(
            "async_bypass_zones: solicitado=%s, já_anuladas_antes=%s, alvo_final=%s",
            zones_to_bypass,
            {z for z, b in self.data.zones_bypassed.items() if b} if self.data else "sem status ainda",
            target,
        )
        frame = cmd_bypass(self._password, {zone: True for zone in target})
        zones_fmt = ", ".join(str(z) for z in sorted(zones_to_bypass))
        label = f"Anular zona(s) {zones_fmt}"
        await self._send_and_check(frame, label)
        await self.async_request_refresh()
        _LOGGER.debug(
            "async_bypass_zones: após refresh, anuladas_agora=%s",
            {z for z, b in self.data.zones_bypassed.items() if b} if self.data else "sem status",
        )

    async def async_bypass_open_zones(self) -> None:
        """Anula todas as zonas atualmente abertas (equivalente ao atalho do fluxo Node-RED)."""
        if self.data is None:
            return
        open_zones = {zone for zone, is_open in self.data.zones_open.items() if is_open}
        if open_zones:
            await self.async_bypass_zones(open_zones)

    async def async_bypass_violated_zones(self) -> None:
        """Anula todas as zonas atualmente violadas (que geraram disparo)."""
        if self.data is None:
            return
        violated_zones = {zone for zone, violated in self.data.zones_violated.items() if violated}
        if violated_zones:
            await self.async_bypass_zones(violated_zones)

    async def async_bypass_open_or_violated_zones(self) -> None:
        """Anula, numa única operação, todas as zonas abertas OU violadas.

        Como o comando 0x42 é absoluto (redefine o estado de anulação das
        64 zonas de uma vez — ver ``async_bypass_zones``), fazer isso em
        duas chamadas separadas (abertas, depois violadas) faria a segunda
        chamada desfazer o que a primeira acabou de anular caso usassem
        `replace=True`; usando a união dos dois conjuntos numa única
        chamada, o problema não existe.
        """
        if self.data is None:
            return
        zones = {zone for zone, v in self.data.zones_open.items() if v}
        zones |= {zone for zone, v in self.data.zones_violated.items() if v}
        if zones:
            await self.async_bypass_zones(zones)

    async def async_clear_bypass(self) -> None:
        """Remove todas as anulações, reativando todas as zonas."""
        if self.family == FAMILY_8000:
            if self.data is not None:
                bypassed = {z for z, b in self.data.zones_bypassed.items() if b}
                await self.async_unbypass_zones(bypassed)
            return
        frame = cmd_bypass(self._password, {})
        await self._send_and_check(frame, "Remover todas as anulações de zona")
        await self.async_request_refresh()

    async def async_unbypass_zones(self, zones: set[int]) -> None:
        """Reativa uma ou mais zonas, preservando as demais anulações existentes.

        Contraparte de ``async_bypass_zones`` — usada pelo serviço
        ``intelbras_alarm.bypass_zone`` com ``bypass: false``. Aceita
        múltiplas zonas na mesma chamada pelo mesmo motivo que
        ``async_bypass_zones`` aceita um conjunto: o comando 0x42 é
        absoluto, então reativar zona a zona em chamadas separadas
        desfaria anulações de outras zonas no meio do caminho. Na AMT
        8000, o comando já é individual por zona (ver
        ``async_bypass_zones``), então este loop é natural, não uma
        adaptação.
        """
        if self.family == FAMILY_8000:
            for zone in sorted(zones):
                frame = amt8000.cmd_bypass(zone, False)
                await self._send_and_check_amt8000(frame, f"Reativar zona {zone}")
            await self.async_request_refresh()
            return

        current: set[int] = set()
        if self.data is not None:
            current = {z for z, bypassed in self.data.zones_bypassed.items() if bypassed}
        _LOGGER.debug(
            "async_unbypass_zones: zonas=%s, anuladas_antes=%s",
            zones,
            current,
        )
        current -= zones
        frame = cmd_bypass(self._password, {z: True for z in current})
        zones_fmt = ", ".join(str(z) for z in sorted(zones))
        await self._send_and_check(frame, f"Reativar zona(s) {zones_fmt}")
        await self.async_request_refresh()
        _LOGGER.debug(
            "async_unbypass_zones: após refresh, anuladas_agora=%s",
            {z for z, b in self.data.zones_bypassed.items() if b} if self.data else "sem status",
        )

    async def async_send_raw_command(
        self,
        frame: str | None = None,
        command: str | None = None,
        content: str | None = None,
        password: str | None = None,
        calculate_checksum: bool = False,
    ) -> dict:
        """Serviço de diagnóstico avançado: envia um comando "cru" pela
        conexão já existente e devolve a resposta bruta da central, sem
        as validações normais da integração — pra testar comandos ainda
        não implementados/documentados.

        Três modos de uso (mutuamente exclusivos):

        1. Só ``frame``: envia exatamente os bytes informados, sem tocar
           em nada (nem senha, nem checksum) — máxima flexibilidade, mas
           você monta tudo à mão, inclusive o checksum.
        2. ``frame`` + ``calculate_checksum=True``: envia os bytes
           informados, mas recalcula e substitui o ÚLTIMO byte pelo
           checksum correto antes de enviar. Útil pra digitar o frame
           quase inteiro (cabeçalho, comando, conteúdo) sem precisar
           calcular o checksum manualmente — basta terminar com um byte
           qualquer como placeholder (ex.: ``FF``).
        3. ``command`` + ``content`` (sem ``frame``): a integração monta o
           frame inteiro sozinha (cabeçalho, senha, checksum), do mesmo
           jeito que qualquer outro comando já implementado — só o byte
           de comando e o conteúdo em si são "crus"/não documentados.

        Reaproveita a MESMA conexão persistente já aberta (nunca abre uma
        segunda) e passa pelo mesmo lock serializado de sempre — não há
        risco de concorrência com a consulta de status ou outros comandos.

        Ao contrário dos demais comandos, um NACK aqui NÃO vira
        ``HomeAssistantError`` — o objetivo explícito deste serviço é
        justamente permitir ver a resposta (incluindo um NACK) que a
        central realmente devolveu, não interromper a chamada.
        """
        if frame is not None:
            try:
                frame_bytes = bytearray(parse_hex_bytes(frame))
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            if not frame_bytes:
                raise HomeAssistantError("Frame vazio")
            if calculate_checksum:
                if len(frame_bytes) < 2:
                    raise HomeAssistantError(
                        "Frame curto demais para calcular checksum (precisa de "
                        "pelo menos um byte antes do placeholder final)"
                    )
                frame_bytes[-1] = checksum(bytes(frame_bytes[:-1]))
            final_frame = bytes(frame_bytes)
        else:
            if command is None:
                raise HomeAssistantError(
                    "Informe 'frame' (comando completo) OU 'command' + "
                    "'content' (a integração monta o resto)"
                )
            try:
                command_bytes = parse_hex_bytes(command)
                content_bytes = parse_hex_bytes(content) if content else b""
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            if len(command_bytes) != 1:
                raise HomeAssistantError(
                    "'command' deve ser um único byte, ex.: 42 ou 0x42"
                )
            try:
                final_frame = build_command(
                    password or self._password, command_bytes[0], content_bytes
                )
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err

        label = "comando bruto (diagnóstico)"
        _LOGGER.debug("send_raw_command: frame=%s", final_frame.hex(" ").upper())
        try:
            response = await self.client.send_command(final_frame, context=label)
        except PanelConnectionError as err:
            raise HomeAssistantError(f"Falha de comunicação: {err}") from err

        result: dict = {
            "frame_enviado": final_frame.hex(" ").upper(),
            "resposta_bruta": response.raw.hex(" ").upper(),
            "checksum_valido": response.valid_checksum,
            "conteudo": response.content.hex(" ").upper(),
        }
        if len(response.content) <= 2:
            result["descricao"] = _describe_response(response)
        return result

    async def _send_and_check(self, frame: bytes, action_label: str | None = None) -> None:
        # Grava a ação sendo enviada ANTES da resposta chegar, e notifica
        # os listeners imediatamente (async_update_listeners, sem esperar
        # um novo ciclo de polling) — assim o sensor "Último comando" fica
        # rastreável em duas fases: o que foi pedido, depois o que a
        # central respondeu. Ver README, seção do sensor "Último comando".
        #
        # O log de depuração de "enviando comando" NÃO fica aqui de
        # propósito — fica dentro de PanelClient.send_command(), só depois
        # de conseguir a vez na fila (o lock da conexão). Se o log fosse
        # daqui, o horário registrado seria o momento em que decidimos
        # mandar, não o momento em que o comando realmente saiu pela
        # conexão — o que gerava sequências de log aparentemente fora de
        # ordem quando um comando tinha que esperar uma consulta de status
        # já em andamento (relatado pelo usuário).
        if action_label:
            self.last_command_result = f"{action_label}..."
            self.last_command_action = action_label
            self.last_command_frame_hex = frame.hex(" ").upper()
            self.async_update_listeners()
        try:
            response = await self.client.send_command(frame, context=action_label)
        except PanelConnectionError as err:
            self.last_command_result = f"{action_label + ': ' if action_label else ''}{err}"
            if action_label:
                # Limpa a resposta do comando anterior — não houve resposta
                # nova, e deixar o valor antigo aí passaria a impressão
                # enganosa de que ele pertence a este comando que falhou.
                self.last_command_response_hex = None
            self.async_update_listeners()
            # ERROR (não WARNING/DEBUG): comandos reais são pedidos
            # explícitos do usuário, e essa falha NÃO passa pela tolerância
            # usada na consulta de status periódica (ver
            # _handle_poll_failure) — é sempre imediata e definitiva, então
            # merece visibilidade alta no log.
            _LOGGER.error("Comando falhou (erro de conexão): ação=%s erro=%s", action_label, err)
            raise UpdateFailed(str(err)) from err
        result_desc = _describe_response(response)
        self.last_command_result = f"{action_label + ': ' if action_label else ''}{result_desc}"
        if action_label:
            self.last_command_response_hex = response.content.hex(" ").upper()
        self.async_update_listeners()
        _LOGGER.debug(
            "resposta recebida: ação=%s resultado=%s resposta_bruta=%s",
            action_label or "(sem rótulo)",
            result_desc,
            response.content.hex(" ").upper(),
        )
        try:
            raise_for_ack(response)
        except NackError as err:
            # Convertido para HomeAssistantError para que o Home Assistant
            # mostre a mensagem (ex.: "Senha incorreta", "Zonas abertas")
            # de forma amigável na UI/serviço, em vez de uma exceção
            # genérica não tratada.
            raise HomeAssistantError(err.message) from err

    async def _send_and_check_amt8000(self, frame: bytes, action_label: str | None = None) -> None:
        """Equivalente a ``_send_and_check`` para a AMT 8000.

        ⚠️ IMPORTANTE (limitação conhecida, ver README_DETALHADO.md): ao
        contrário do protocolo ISECMobile, ainda não temos um esquema de
        ACK/NACK confirmado por captura própria para os comandos de
        ação da AMT 8000 (arme, desarme, bypass, PGM, pânico) — só o
        opcode de falha de autenticação (``0xF0FD``) foi identificado com
        confiança alta. Por isso, esta função trata "não levantou erro de
        conexão" como sucesso, sem validar o conteúdo da resposta linha a
        linha — se a central devolver algum código de rejeição específico
        (ex.: senha incorreta num comando isolado, partição inválida),
        isso ainda não é detectado aqui e precisa ser observado no valor
        bruto de ``last_command_response_hex`` durante os testes de
        campo, até este ponto ser confirmado e o tratamento refinado.
        """
        if action_label:
            self.last_command_result = f"{action_label}..."
            self.last_command_action = action_label
            self.last_command_frame_hex = frame.hex(" ").upper()
            self.async_update_listeners()
        try:
            response = await self.client.send_command(frame, context=action_label)
        except _ANY_PANEL_CONNECTION_ERROR as err:
            self.last_command_result = f"{action_label + ': ' if action_label else ''}{err}"
            if action_label:
                self.last_command_response_hex = None
            self.async_update_listeners()
            _LOGGER.error("Comando AMT 8000 falhou (erro de conexão): ação=%s erro=%s", action_label, err)
            raise UpdateFailed(str(err)) from err
        result_desc = f"opcode=0x{response.opcode[0]:02X}{response.opcode[1]:02X}"
        self.last_command_result = f"{action_label + ': ' if action_label else ''}{result_desc}"
        if action_label:
            self.last_command_response_hex = response.content.hex(" ").upper()
        self.async_update_listeners()
        _LOGGER.debug(
            "AMT 8000 resposta recebida: ação=%s resultado=%s resposta_bruta=%s",
            action_label or "(sem rótulo)",
            result_desc,
            response.content.hex(" ").upper(),
        )

    # ------------------------------------------------------------------
    # Protocolo legado (0xE7 + identificação) — nomes de zona/usuário e
    # eventos para modelos/firmwares fora do supports_extended_eeprom,
    # SE o usuário configurou a senha de leitura de mensagens. Ver
    # supports_legacy_eeprom e protocol_legacy_eeprom.py. Não se aplica
    # à AMT 8000 (ver docstring de supports_legacy_eeprom).
    #
    # Usa uma conexão TCP isolada e descartável, própria pra essa
    # operação — NÃO reaproveita a conexão persistente já usada pro
    # polling normal (ISECMobile), por dois motivos: (1) é literalmente
    # outro protocolo, misturar na mesma conexão arrisca confundir
    # qualquer um dos dois lados; (2) só roda sob demanda (botão de
    # sincronizar zonas / serviço read_events), nunca no ciclo de
    # polling — não precisa ficar aberta.
    # ------------------------------------------------------------------
    async def _async_legacy_eeprom_session(self, paginas_info: list[tuple[int, int]]) -> bytes:
        """Abre conexão isolada, autentica com a senha de leitura, lê
        todas as páginas pedidas em sequência, fecha a conexão.

        ``paginas_info`` é uma lista de (endereço, tamanho) — ver
        ``protocol_legacy_eeprom.paginas()``.
        """
        host = self.entry.data["host"]
        port = self.entry.data["port"]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise UpdateFailed(
                f"Não foi possível conectar a {host}:{port} para leitura "
                f"legada de EEPROM: {err}"
            ) from err

        try:
            frame_auth = legacy_eeprom.montar_comando_autenticar(self._legacy_eeprom_password)
            writer.write(frame_auth)
            await writer.drain()
            try:
                resposta_auth = await asyncio.wait_for(reader.read(4096), timeout=5)
            except asyncio.TimeoutError as err:
                raise UpdateFailed(
                    "Sem resposta da central à identificação (senha de leitura de mensagens)"
                ) from err
            if not legacy_eeprom.autenticacao_bem_sucedida(resposta_auth):
                raise HomeAssistantError(
                    "Falha na identificação com a senha de leitura de mensagens "
                    "configurada — confira se está correta (6 dígitos, "
                    "\"Senha Acesso Remoto\" no app AMT Mobile)"
                )
            await asyncio.sleep(legacy_eeprom.DELAY_ENTRE_REQUISICOES)

            dados = bytearray()
            for endereco, tamanho in paginas_info:
                frame = legacy_eeprom.montar_comando_leitura(endereco, tamanho)
                writer.write(frame)
                await writer.drain()
                try:
                    resposta = await asyncio.wait_for(reader.read(4096), timeout=5)
                except asyncio.TimeoutError as err:
                    raise UpdateFailed(
                        f"Sem resposta lendo EEPROM legada no endereço 0x{endereco:04X}"
                    ) from err
                if len(resposta) < 4 + tamanho:
                    raise UpdateFailed(
                        f"Resposta incompleta lendo EEPROM legada no endereço "
                        f"0x{endereco:04X}: recebidos {len(resposta)} bytes, "
                        f"esperados pelo menos {4 + tamanho}"
                    )
                dados += resposta[4 : 4 + tamanho]
                await asyncio.sleep(legacy_eeprom.DELAY_ENTRE_REQUISICOES)
            return bytes(dados)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _async_refresh_zone_names_legacy(self) -> dict[int, str]:
        paginas_info = list(
            legacy_eeprom.paginas(
                legacy_eeprom.NAMES_START,
                legacy_eeprom.NAMES_PAGE,
                legacy_eeprom.NAMES_END,
                legacy_eeprom.NAMES_LAST,
            )
        )
        dados = await self._async_legacy_eeprom_session(paginas_info)
        resultado = legacy_eeprom.parse_nomes(dados)
        self.zone_names = resultado.zonas
        self.async_update_listeners()
        return resultado.zonas

    async def _async_read_events_legacy(self) -> list[dict]:
        paginas_info = list(
            legacy_eeprom.paginas(
                legacy_eeprom.EVENTS_START,
                legacy_eeprom.EVENTS_PAGE,
                legacy_eeprom.EVENTS_END,
                legacy_eeprom.EVENTS_LAST,
            )
        )
        dados = await self._async_legacy_eeprom_session(paginas_info)
        registros = legacy_eeprom.parse_eventos(dados)
        registros.sort(key=lambda e: e["data_hora"], reverse=True)
        self.recent_events = registros[:EVENT_ENTITY_RECENT_COUNT]
        self.async_update_listeners()
        return registros

    # ------------------------------------------------------------------
    # Nomes de zona (EEPROM, apenas família 4010)
    # ------------------------------------------------------------------
    async def async_refresh_zone_names(self) -> dict[int, str]:
        """Lê os nomes de todas as zonas gravados na EEPROM da central."""
        if self.supports_legacy_eeprom:
            return await self._async_refresh_zone_names_legacy()
        if not self.supports_extended_eeprom:
            return {}

        if self.family == FAMILY_8000:
            return await self._async_refresh_zone_names_amt8000()

        names: dict[int, str] = {}
        zone = 1
        while zone <= self.max_zones:
            batch = min(12, self.max_zones - zone + 1)  # 12 zonas x 16 bytes = 192 bytes (máx. do 0x5C)
            length = batch * ZONE_NAME_RECORD_LEN
            address = ZONE_NAME_BASE_ADDRESS + (zone - 1) * ZONE_NAME_RECORD_LEN
            frame = cmd_eeprom_read(self._password, address, length)
            try:
                response = await self.client.send_command(frame, context=f"ler nomes de zona {zone}")
            except PanelConnectionError as err:
                raise UpdateFailed(str(err)) from err
            if not response.content or response.content[0] in (0xE0, 0xE1, 0xE2, 0xE5):
                raise UpdateFailed("A central recusou a leitura de nomes de zona")
            # content[0] = índice do usuário que enviou o comando; resto = dados
            data = response.content[1:]
            names.update(decode_zone_names(data, zone))
            zone += batch

        self.zone_names = names
        self.async_update_listeners()
        return names

    async def _async_refresh_zone_names_amt8000(self) -> dict[int, str]:
        """Lê os nomes de zona da AMT 8000, um índice por vez.

        Decisão de arquitetura registrada no histórico do projeto: 1
        requisição por zona (não em lote de 10 como o app oficial),
        priorizando isolamento de erro e simplicidade do parser nesta
        primeira versão — só roda na configuração inicial ou por pedido
        manual (botão "Sincronizar nomes de zona"), nunca no polling
        normal. ⚠️ O formato exato da resposta (quantos bytes, padding)
        ainda não foi confirmado por captura própria — o decode abaixo é
        uma melhor tentativa (ASCII, removendo bytes nulos/não
        imprimíveis) e pode precisar de ajuste.
        """
        names: dict[int, str] = {}
        for zone in range(1, self.native_zone_count + 1):
            frame = amt8000.cmd_sync_names("zona", [zone])
            try:
                response = await self.client.send_command(frame, context=f"nome da zona {zone} (AMT 8000)")
            except _ANY_PANEL_CONNECTION_ERROR as err:
                _LOGGER.warning("AMT 8000: falha ao ler nome da zona %d: %s", zone, err)
                continue
            texto = response.content.decode("ascii", errors="ignore")
            texto = "".join(ch for ch in texto if ch.isprintable()).strip()
            if texto:
                names[zone] = texto

        self.zone_names = names
        self.async_update_listeners()
        return names

    # ------------------------------------------------------------------
    # Log de eventos (EEPROM, comando 0x5C — mesmos modelos/firmwares que
    # suportam nomes de zona, ver supports_extended_eeprom)
    # ------------------------------------------------------------------
    async def async_read_events(self) -> list[dict]:
        """Lê o log de eventos inteiro (256 registros, 0x1800-0x2000) e
        devolve todos, ordenados do mais recente pro mais antigo por
        data/hora real de cada registro.

        IMPORTANTE: a ordem dos endereços na EEPROM **não** corresponde à
        ordem cronológica dos eventos (confirmado em campo) — por isso
        sempre lemos o log inteiro e ordenamos pela data/hora decodificada
        de cada registro, em vez de tentar ler só "os últimos N" por
        endereço (que poderia devolver dados desatualizados ou fora de
        ordem).

        Também atualiza ``self.recent_events`` com os
        ``EVENT_ENTITY_RECENT_COUNT`` mais recentes, para a entidade
        "Últimos eventos" — independente de quantos eventos válidos
        existirem no total.
        """
        if self.supports_legacy_eeprom:
            return await self._async_read_events_legacy()
        if not self.supports_extended_eeprom:
            raise HomeAssistantError(
                "Este modelo/firmware não tem acesso à leitura de eventos "
                "nesta integração (ver README, seção de modelos suportados)"
            )

        if self.family == FAMILY_8000:
            return await self._async_read_events_amt8000()

        registros: list[dict] = []
        endereco = EVENT_LOG_BASE_ADDRESS
        fim = EVENT_LOG_BASE_ADDRESS + EVENT_LOG_TOTAL_BYTES
        while endereco < fim:
            tamanho = min(EVENT_LOG_CHUNK_BYTES, fim - endereco)
            frame = cmd_eeprom_read(self._password, endereco, tamanho)
            try:
                response = await self.client.send_command(
                    frame, context=f"ler eventos 0x{endereco:04X}"
                )
            except PanelConnectionError as err:
                raise UpdateFailed(str(err)) from err
            if not response.content or response.content[0] in (0xE0, 0xE1, 0xE2, 0xE5):
                raise UpdateFailed("A central recusou a leitura do log de eventos")
            # content[0] = índice do usuário que enviou o comando; resto = dados
            dados = response.content[1:]
            for i in range(0, len(dados), EVENT_RECORD_LEN):
                registro = dados[i : i + EVENT_RECORD_LEN]
                if len(registro) < EVENT_RECORD_LEN:
                    break
                evento = parse_event_record(bytes(registro))
                if evento is not None:
                    registros.append(evento)
            endereco += tamanho

        registros.sort(key=lambda e: e["data_hora"], reverse=True)

        self.recent_events = registros[:EVENT_ENTITY_RECENT_COUNT]
        self.async_update_listeners()
        return registros

    async def _async_read_events_amt8000(self) -> list[dict]:
        """Lê o log de eventos da AMT 8000 (buffer circular, até
        ``AMT8000_EVENT_BUFFER_SIZE`` posições).

        ⚠️ Lê **um índice por vez** nesta primeira versão (não em lote de
        16 como o app oficial) — o formato de uma resposta com múltiplos
        registros concatenados ainda não foi confirmado por captura
        própria, então evitamos adivinhar os limites de cada registro
        dentro de uma resposta em lote. Isso torna a leitura completa
        (até 512 posições) mais lenta que nas demais famílias; como é
        uma operação sob demanda (serviço `read_events`), não afeta o
        polling normal. Cada índice vazio/não inicializado do buffer
        circular é descartado silenciosamente (mesmo comportamento das
        demais famílias — ver `protocol.parse_event_record`).
        """
        registros: list[dict] = []
        for idx in range(AMT8000_EVENT_BUFFER_SIZE):
            frame = amt8000.cmd_read_events([idx])
            try:
                response = await self.client.send_command(frame, context=f"evento {idx} (AMT 8000)")
            except _ANY_PANEL_CONNECTION_ERROR as err:
                raise UpdateFailed(str(err)) from err
            evento = amt8000.parse_event_record(list(response.content))
            if evento is None:
                continue
            codigo_raw = evento["codigo_raw"]
            descricao = RECEPTOR_IP_EVENT_TABLE.get(codigo_raw)
            evento["codigo_app"] = codigo_raw if descricao else None
            evento["descricao"] = descricao or "Código não mapeado (ver codigo_raw)"
            registros.append(evento)

        registros.sort(key=lambda e: e["data_hora"], reverse=True)
        self.recent_events = registros[:EVENT_ENTITY_RECENT_COUNT]
        self.async_update_listeners()
        return registros

    async def async_request_event_photo(self, photo_index: bytes) -> bytes | None:
        """Tenta buscar a foto de um evento (AMT 8000, sensores com câmera).

        ⚠️ INCOMPLETO/EXPERIMENTAL: o LEIA_ME oficial descreve o fluxo
        completo como autenticar → ``0x0BB0`` → ler MÚLTIPLOS fragmentos
        → ``0xF0F1`` (desconectar), com a foto em JPG ~320x200 dividida
        em pedaços de ~8KB cada, e um atraso de até 15s antes da foto
        ficar disponível na central (erro ``0xF0FD``/``0x28`` enquanto
        isso). Esta implementação faz só UMA tentativa de leitura de UM
        fragmento — não reconstrói uma foto completa a partir de vários
        fragmentos, nem trata o atraso/erro "ainda gravando" documentado.
        Serve como ponto de partida para completar quando houver uma
        central real disponível para captura de tráfego. Devolve
        ``None`` em qualquer falha ou resposta vazia, para que
        ``camera.py`` trate como "sem imagem disponível" (nunca levanta
        exceção).
        """
        try:
            response = await self.client.send_command(
                amt8000.cmd_photo_request(photo_index), context="solicitar foto (AMT 8000)"
            )
        except _ANY_PANEL_CONNECTION_ERROR as err:
            _LOGGER.debug("AMT 8000: falha ao solicitar foto: %s", err)
            return None
        if not response.content:
            return None
        return bytes(response.content)

    # ------------------------------------------------------------------
    # Receptor IP (eventos empurrados pela própria central, em tempo
    # real — ver receptor_ip.py). Estes dois métodos são passados como
    # callback pro ReceptorIPServer; não fazem nenhuma comunicação com a
    # central por conta própria, só guardam o que chegou e notificam as
    # entidades.
    #
    # A data/hora do "sinal de vida" é sempre a deste servidor (Home
    # Assistant), não a da central — o heartbeat (0xF7) não carrega
    # nenhuma data/hora, e foi assim que o usuário definiu (mesmo
    # critério usado nos scripts de referência testados antes desta
    # funcionalidade ser incorporada à integração). Usa
    # ``dt_util.utcnow()`` (com fuso horário definido, UTC) em vez de
    # ``datetime.now()`` porque a entidade correspondente usa
    # ``device_class: timestamp``, que exige isso do Home Assistant —
    # ele mesmo converte para o fuso local na exibição.
    # ------------------------------------------------------------------
    def on_receptor_event(self, evento: dict) -> None:
        self.receptor_last_event = evento
        self.receptor_last_heartbeat = dt_util.utcnow()
        self.async_update_listeners()

    def on_receptor_heartbeat(self) -> None:
        self.receptor_last_heartbeat = dt_util.utcnow()
        self.async_update_listeners()


def _build_status_frame(password: str, family: str) -> bytes:
    from .protocol import build_command

    return build_command(password, FAMILY_STATUS_CMD[family])


def _partition_code(partition: str) -> int:
    from .const import PARTITION_CODES

    return PARTITION_CODES[partition]


def _partition_label(partition: str | None) -> str:
    """Nome amigável de partição/central para o sensor "Último comando"."""
    return "Central" if partition is None else f"Partição {partition}"


_PANIC_LABELS = {
    0x00: "silencioso",
    0x01: "audível",
    0x02: "emergência médica",
    0x03: "incêndio",
}


def _describe_response(response: ParsedFrame) -> str:
    """Descrição textual amigável de uma resposta curta (ACK/NACK)."""
    from .const import ACK_OK, NACK_MESSAGES

    if not response.content:
        return "Resposta vazia"
    code = response.content[0]
    if code == ACK_OK:
        return "OK"
    return NACK_MESSAGES.get(code, f"NACK desconhecido (0x{code:02X})")


async def async_detect_model(host: str, port: int, password: str) -> tuple[str, str, str]:
    """Detecta automaticamente a família/modelo da central.

    Estratégia: envia primeiro o comando 0x5A (famílias 2018/1016/SMART).
    Se a central responder com NACK "comando descontinuado" (0xE5) — como
    documentado na seção 7.4 —, trata-se de uma AMT 4010 e o comando 0x5B é
    usado em seguida.
    """
    from .protocol import build_command, parse_status_2018, parse_status_4010
    from .const import CMD_STATUS_FULL, CMD_STATUS_PARTIAL

    client = PanelClient(host, port, timeout=DEFAULT_REQUEST_TIMEOUT)
    try:
        await client.connect()
        try:
            response = await client.send_command(build_command(password, CMD_STATUS_PARTIAL), context="detecção de modelo")
        except PanelConnectionError as err:
            raise UpdateFailed(str(err)) from err

        if len(response.content) == 1 and response.content[0] != ACK_OK:
            # NACK — mais provável 0xE5 (comando descontinuado) em uma AMT 4010
            try:
                raise_for_ack(response)
            except NackError:
                pass
            response = await client.send_command(build_command(password, CMD_STATUS_FULL), context="detecção de modelo (4010)")
            status = parse_status_4010(response.content)
            return status.model_key, status.model_name, FAMILY_4010

        status = parse_status_2018(response.content)
        if status.model_key == MODEL_UNKNOWN:
            # Byte de modelo não reconhecido nesta família: tenta 4010 como
            # segunda hipótese antes de desistir.
            response2 = await client.send_command(build_command(password, CMD_STATUS_FULL), context="detecção de modelo (segunda tentativa)")
            status2 = parse_status_4010(response2.content)
            if status2.model_key != MODEL_UNKNOWN:
                return status2.model_key, status2.model_name, FAMILY_4010
        return status.model_key, status.model_name, FAMILY_2018
    finally:
        await client.disconnect()


async def async_detect_amt8000(host: str, port: int, password: str) -> tuple[str, str, str]:
    """"Detecta" a AMT 8000 — na prática, apenas confirma que a autenticação
    de sessão (``0xF0F0``) é aceita nesse host/porta/senha.

    Diferente de ``async_detect_model`` (que sonda automaticamente entre
    as famílias 2018/4010 por tentativa e erro), a AMT 8000 usa um
    protocolo de transporte totalmente diferente — não haveria uma forma
    segura de "tentar" esse protocolo silenciosamente durante a
    detecção automática das outras famílias sem risco de confundir o
    fluxo de detecção existente (já validado em produção para os 5
    modelos suportados). Por isso, o config_flow pede explicitamente
    para o usuário marcar "AMT 8000" em vez de incluir esta família na
    sondagem automática — ver config_flow.py.
    """
    from .panel_client_amt8000 import Amt8000AuthError, PanelClientAmt8000, PanelConnectionErrorAmt8000

    client = PanelClientAmt8000(host, port, password, timeout=DEFAULT_REQUEST_TIMEOUT)
    try:
        try:
            await client.connect()
        except PanelConnectionErrorAmt8000 as err:
            raise UpdateFailed(str(err)) from err
        except Amt8000AuthError as err:
            raise NackError(0xE1) from err  # reaproveita "Senha incorreta" na UI
        return MODEL_AMT_8000, AMT_8000_MODEL_NAME, FAMILY_8000
    finally:
        await client.disconnect()
