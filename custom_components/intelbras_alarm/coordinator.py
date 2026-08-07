"""Coordenador de atualização de dados da central de alarme Intelbras."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACK_OK,
    CMD_EEPROM_READ,
    DEFAULT_TIMEOUT_ETHERNET,
    FAMILY_2018,
    FAMILY_4010,
    FAMILY_MAX_ZONES,
    FAMILY_STATUS_CMD,
    MODEL_TABLE,
    MODEL_UNKNOWN,
    PGM_ADDRESSES,
    ZONE_NAME_BASE_ADDRESS,
    ZONE_NAME_MAX_READ,
    ZONE_NAME_RECORD_LEN,
)
from .panel_client import PanelClient, PanelConnectionError
from .protocol import (
    NackError,
    PanelStatus,
    ParsedFrame,
    cmd_arm,
    cmd_bypass,
    cmd_disarm,
    cmd_eeprom_read,
    cmd_panic,
    cmd_pgm,
    cmd_siren,
    decode_zone_names,
    parse_status,
    raise_for_ack,
)

_LOGGER = logging.getLogger(__name__)


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
        self.zone_names: dict[int, str] = {}
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

        super().__init__(
            hass,
            _LOGGER,
            name=f"Intelbras Alarm ({entry.title})",
            update_interval=timedelta(seconds=entry.options.get("polling_interval", 0.25)),
        )

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
    def supports_zone_names(self) -> bool:
        return self.family == FAMILY_4010

    @property
    def password(self) -> str:
        """Senha ISECMobile principal, usada para validar códigos digitados na UI."""
        return self._password

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
        try:
            response = await self.client.send_command(
                _build_status_frame(self._password, self.family)
            )
        except PanelConnectionError as err:
            raise UpdateFailed(str(err)) from err

        if not response.valid_checksum:
            raise UpdateFailed("Checksum inválido na resposta de status")

        try:
            status = parse_status(response.content, self.family)
        except (IndexError, ValueError) as err:
            raise UpdateFailed(f"Falha ao interpretar status: {err}") from err

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

    # ------------------------------------------------------------------
    # Comandos de alto nível usados pelas entidades
    # ------------------------------------------------------------------
    async def async_arm(self, partition: str | None, stay: bool, password: str | None = None) -> None:
        code = None if partition is None else _partition_code(partition)
        frame = cmd_arm(password or self._password, code, stay=stay)
        label = f"Ativar {_partition_label(partition)}" + (" (Stay)" if stay else "")
        await self._send_and_check(frame, label)
        key = partition or "CENTRAL"
        self.armed_home_mode[key] = stay
        await self.async_request_refresh()

    async def async_disarm(self, partition: str | None, password: str | None = None) -> None:
        code = None if partition is None else _partition_code(partition)
        frame = cmd_disarm(password or self._password, code)
        label = f"Desativar {_partition_label(partition)}"
        await self._send_and_check(frame, label)
        key = partition or "CENTRAL"
        self.armed_home_mode[key] = False
        await self.async_request_refresh()

    async def async_set_pgm(self, address: int, turn_on: bool, pgm: int | None = None) -> None:
        frame = cmd_pgm(self._password, address, turn_on)
        pgm_label = f"PGM {pgm}" if pgm is not None else f"PGM (endereço 0x{address:02X})"
        label = f"{'Ligar' if turn_on else 'Desligar'} {pgm_label}"
        await self._send_and_check(frame, label)
        await self.async_request_refresh()

    async def async_set_siren(self, turn_on: bool) -> None:
        frame = cmd_siren(self._password, turn_on)
        label = "Ligar sirene" if turn_on else "Desligar sirene"
        await self._send_and_check(frame, label)
        await self.async_request_refresh()

    async def async_panic(self, kind: int) -> None:
        frame = cmd_panic(self._password, kind)
        label = f"Pânico ({_PANIC_LABELS.get(kind, f'0x{kind:02X}')})"
        await self._send_and_check(frame, label)

    async def async_bypass_zones(self, zones_to_bypass: set[int], *, replace: bool = False) -> None:
        """Anula (bypass) as zonas indicadas.

        O comando 0x42 é absoluto (define o estado de anulação de todas as
        64 zonas do protocolo de uma vez). Por padrão (``replace=False``),
        as zonas já anuladas na última leitura de status são preservadas —
        o comando enviado é a união entre o que já estava anulado e
        ``zones_to_bypass``. Use ``replace=True`` para enviar exatamente o
        conjunto informado (desanulando qualquer zona fora dele).
        """
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

    async def async_clear_bypass(self) -> None:
        """Remove todas as anulações, reativando todas as zonas."""
        frame = cmd_bypass(self._password, {})
        await self._send_and_check(frame, "Remover todas as anulações de zona")
        await self.async_request_refresh()

    async def async_unbypass_zone(self, zone: int) -> None:
        """Reativa uma única zona, preservando as demais anulações existentes.

        Contraparte de ``async_bypass_zones`` para uma zona só (usada pelo
        botão "Reativar zona selecionada" e pelo serviço
        ``intelbras_alarm.bypass_zone`` com ``bypass: false``).
        """
        current: set[int] = set()
        if self.data is not None:
            current = {z for z, bypassed in self.data.zones_bypassed.items() if bypassed}
        _LOGGER.debug(
            "async_unbypass_zone: zona=%s, anuladas_antes=%s, estava_anulada=%s",
            zone,
            current,
            zone in current,
        )
        current.discard(zone)
        frame = cmd_bypass(self._password, {z: True for z in current})
        await self._send_and_check(frame, f"Reativar zona {zone}")
        await self.async_request_refresh()
        _LOGGER.debug(
            "async_unbypass_zone: após refresh, anuladas_agora=%s (zona %s ainda anulada? %s)",
            {z for z, b in self.data.zones_bypassed.items() if b} if self.data else "sem status",
            zone,
            self.data.zones_bypassed.get(zone) if self.data else "desconhecido",
        )

    async def _send_and_check(self, frame: bytes, action_label: str | None = None) -> None:
        # Grava a ação sendo enviada ANTES da resposta chegar, e notifica
        # os listeners imediatamente (async_update_listeners, sem esperar
        # um novo ciclo de polling) — assim o sensor "Último comando" fica
        # rastreável em duas fases: o que foi pedido, depois o que a
        # central respondeu. Ver README, seção do sensor "Último comando".
        _LOGGER.debug(
            "enviando comando: ação=%s frame=%s",
            action_label or "(sem rótulo)",
            frame.hex(" ").upper(),
        )
        if action_label:
            self.last_command_result = f"{action_label}..."
            self.last_command_action = action_label
            self.last_command_frame_hex = frame.hex(" ").upper()
            self.async_update_listeners()
        try:
            response = await self.client.send_command(frame)
        except PanelConnectionError as err:
            self.last_command_result = f"{action_label + ': ' if action_label else ''}{err}"
            if action_label:
                # Limpa a resposta do comando anterior — não houve resposta
                # nova, e deixar o valor antigo aí passaria a impressão
                # enganosa de que ele pertence a este comando que falhou.
                self.last_command_response_hex = None
            self.async_update_listeners()
            _LOGGER.debug("comando falhou (erro de conexão): ação=%s erro=%s", action_label, err)
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

    # ------------------------------------------------------------------
    # Nomes de zona (EEPROM, apenas família 4010)
    # ------------------------------------------------------------------
    async def async_refresh_zone_names(self) -> dict[int, str]:
        """Lê os nomes de todas as zonas gravados na EEPROM da central."""
        if not self.supports_zone_names:
            return {}

        names: dict[int, str] = {}
        zone = 1
        while zone <= self.max_zones:
            batch = min(12, self.max_zones - zone + 1)  # 12 zonas x 16 bytes = 192 bytes (máx. do 0x5C)
            length = batch * ZONE_NAME_RECORD_LEN
            address = ZONE_NAME_BASE_ADDRESS + (zone - 1) * ZONE_NAME_RECORD_LEN
            frame = cmd_eeprom_read(self._password, address, length)
            try:
                response = await self.client.send_command(frame)
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

    client = PanelClient(host, port, timeout=DEFAULT_TIMEOUT_ETHERNET)
    try:
        await client.connect()
        try:
            response = await client.send_command(build_command(password, CMD_STATUS_PARTIAL))
        except PanelConnectionError as err:
            raise UpdateFailed(str(err)) from err

        if len(response.content) == 1 and response.content[0] != ACK_OK:
            # NACK — mais provável 0xE5 (comando descontinuado) em uma AMT 4010
            try:
                raise_for_ack(response)
            except NackError:
                pass
            response = await client.send_command(build_command(password, CMD_STATUS_FULL))
            status = parse_status_4010(response.content)
            return status.model_key, status.model_name, FAMILY_4010

        status = parse_status_2018(response.content)
        if status.model_key == MODEL_UNKNOWN:
            # Byte de modelo não reconhecido nesta família: tenta 4010 como
            # segunda hipótese antes de desistir.
            response2 = await client.send_command(build_command(password, CMD_STATUS_FULL))
            status2 = parse_status_4010(response2.content)
            if status2.model_key != MODEL_UNKNOWN:
                return status2.model_key, status2.model_name, FAMILY_4010
        return status.model_key, status.model_name, FAMILY_2018
    finally:
        await client.disconnect()
