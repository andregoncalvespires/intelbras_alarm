"""Integração Home Assistant para centrais de alarme Intelbras (ISECNet/ISECMobile)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .connection_state import async_load_connection_enabled
from .const import (
    CONF_MODEL,
    CONF_PARTITION_PASSWORDS,
    CONF_PASSWORD,
    CONF_RECEPTOR_IP_ENABLED,
    CONF_RECEPTOR_IP_PORT,
    DEFAULT_RECEPTOR_IP_ENABLED,
    DEFAULT_RECEPTOR_IP_PORT,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
    FAMILY_8000,
)
from .coordinator import IntelbrasAlarmCoordinator
from .panel_client import PanelClient
from .panel_client_amt8000 import PanelClientAmt8000
from .receptor_ip import ReceptorIPServer

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
]


@dataclass
class IntelbrasAlarmData:
    client: PanelClient | PanelClientAmt8000
    coordinator: IntelbrasAlarmCoordinator
    receptor_server: ReceptorIPServer | None = None


async def _async_retry(
    func, *, tentativas: int = 5, espera_segundos: float = 3.0, descricao: str
) -> bool:
    """Tenta ``func()`` (uma corrotina) até ``tentativas`` vezes, com uma
    pequena pausa entre cada uma — sem loop eterno, propositalmente (ver
    pedido do usuário: garantir os dados sem insistir indefinidamente).

    Usado para leituras únicas feitas na configuração inicial (ex.: nomes
    de zona/usuário) que podem falhar por instabilidade momentânea da
    conexão logo após o Home Assistant subir — comum o suficiente para
    justificar mais de uma tentativa, mas sem sentido tentar para sempre
    se a central genuinamente não está respondendo.

    Devolve ``True`` se alguma tentativa teve sucesso, ``False`` se todas
    falharam (never levanta exceção — quem chama decide o que fazer/logar
    com o resultado).
    """
    for tentativa in range(1, tentativas + 1):
        try:
            await func()
            return True
        except Exception as err:  # noqa: BLE001
            if tentativa == tentativas:
                _LOGGER.warning(
                    "%s: falhou após %d tentativas (%s)",
                    descricao,
                    tentativas,
                    err,
                )
                return False
            _LOGGER.debug(
                "%s: tentativa %d/%d falhou (%s), tentando de novo em %.0fs",
                descricao,
                tentativa,
                tentativas,
                err,
                espera_segundos,
            )
            await asyncio.sleep(espera_segundos)
    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # O estado do switch "Conexão com a central" é lido ANTES de qualquer
    # tentativa de comunicação — se o usuário desligou esse switch antes de
    # reiniciar o Home Assistant, a integração deve respeitar essa escolha
    # e não abrir nenhum socket com a central neste (re)carregamento.
    connection_enabled = await async_load_connection_enabled(hass, entry.entry_id)

    family = entry.data["family"]
    client: PanelClient | PanelClientAmt8000
    if family == FAMILY_8000:
        # EXPERIMENTAL — ver protocol_amt8000.py e panel_client_amt8000.py.
        client = PanelClientAmt8000(
            entry.data["host"],
            entry.data["port"],
            entry.data[CONF_PASSWORD],
            timeout=DEFAULT_REQUEST_TIMEOUT,
            enabled=connection_enabled,
        )
    else:
        client = PanelClient(
            entry.data["host"],
            entry.data["port"],
            timeout=DEFAULT_REQUEST_TIMEOUT,
            enabled=connection_enabled,
        )

    coordinator = IntelbrasAlarmCoordinator(
        hass,
        entry,
        client,
        password=entry.data[CONF_PASSWORD],
        family=entry.data["family"],
        model_key=entry.data[CONF_MODEL],
        partition_passwords=entry.data.get(CONF_PARTITION_PASSWORDS),
    )

    if connection_enabled:
        await coordinator.async_config_entry_first_refresh()

        if coordinator.supports_extended_eeprom or coordinator.supports_legacy_eeprom:
            await _async_retry(
                coordinator.async_refresh_zone_names,
                descricao="Busca de nomes de zona/usuário na configuração inicial",
            )

        if coordinator.supports_voltage_reading:
            try:
                await coordinator.async_refresh_voltage()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Não foi possível ler a tensão da fonte/bateria na configuração "
                    "inicial; nova tentativa em 5 minutos."
                )

    if coordinator.supports_voltage_reading:
        # Tensão da fonte/bateria (comando [1, 0x17] dentro do 0xE7, ver
        # coordinator.async_refresh_voltage) — deliberadamente fora do
        # polling rápido de status: exige autenticação própria a cada
        # leitura, então roda só a cada 5 minutos, num agendamento
        # próprio, independente do DataUpdateCoordinator principal.
        #
        # Registrado AQUI, fora do "if connection_enabled" acima (bug
        # real corrigido, relatado pelo usuário): se a conexão estivesse
        # desligada neste (re)carregamento, o timer nunca chegava a ser
        # criado — e religar o switch depois não resolvia, porque não
        # havia timer nenhum para retomar. async_refresh_voltage() já
        # verifica client.enabled sozinho e sai em silêncio quando
        # desligado, então é seguro sempre agendar aqui.
        async def _async_refresh_voltage_periodico(now) -> None:
            await coordinator.async_refresh_voltage()

        entry.async_on_unload(
            async_track_time_interval(hass, _async_refresh_voltage_periodico, timedelta(minutes=5))
        )
    else:
        # Não chamamos async_config_entry_first_refresh(): ele levantaria
        # ConfigEntryNotReady (pois o client recusa comandos desabilitado),
        # o que impediria até a criação do próprio switch de conexão — e o
        # usuário ficaria sem forma de religar pela UI. Em vez disso, a
        # entrada é configurada normalmente, sem dados iniciais; as demais
        # entidades ficam "indisponíveis" até o switch ser ligado.
        #
        # coordinator.pause_polling() AQUI é essencial (bug real corrigido,
        # ver docstring do método): sem isso, o primeiro listener adicionado
        # quando as entidades forem criadas logo abaixo
        # (`async_forward_entry_setups`) já dispararia o agendamento normal
        # de consultas — e cada uma falharia instantaneamente (switch
        # desligado), criando o mesmo laço de CPU alta desde a primeira
        # inicialização, sem nem precisar desligar o switch manualmente.
        coordinator.pause_polling()
        _LOGGER.info(
            "Conexão com a central Intelbras está desativada (switch); "
            "pulando a consulta inicial de status"
        )

    # Receptor IP (opcional, desligado por padrão): servidor que fica
    # esperando a CENTRAL se conectar NELE, empurrando eventos em tempo
    # real — papéis invertidos em relação à conexão normal desta
    # integração. Configurado na própria central (fora daqui), apontando
    # para o IP do Home Assistant e a porta definida abaixo. Ver
    # receptor_ip.py e o README, seção "Receptor IP".
    receptor_server: ReceptorIPServer | None = None
    if entry.data.get(CONF_RECEPTOR_IP_ENABLED, DEFAULT_RECEPTOR_IP_ENABLED):
        receptor_server = ReceptorIPServer(
            host="0.0.0.0",
            port=entry.data.get(CONF_RECEPTOR_IP_PORT, DEFAULT_RECEPTOR_IP_PORT),
            expected_panel_ip=entry.data["host"],
            on_event=coordinator.on_receptor_event,
            on_heartbeat=coordinator.on_receptor_heartbeat,
        )
        try:
            await receptor_server.async_start()
        except OSError as err:
            _LOGGER.error(
                "Receptor IP: não foi possível abrir a porta %s (%s) — o restante da "
                "integração continua funcionando normalmente, só a recepção de eventos "
                "em tempo real fica indisponível. Verifique se a porta já está em uso "
                "ou se precisa ser exposta (Docker/HAOS).",
                entry.data.get(CONF_RECEPTOR_IP_PORT, DEFAULT_RECEPTOR_IP_PORT),
                err,
            )
            receptor_server = None

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = IntelbrasAlarmData(
        client=client, coordinator=coordinator, receptor_server=receptor_server
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarrega a entrada quando as opções (ex.: intervalo de polling) mudam."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data: IntelbrasAlarmData = hass.data[DOMAIN].pop(entry.entry_id)
        if data.receptor_server is not None:
            await data.receptor_server.async_stop()
        await data.client.disconnect()
    return unload_ok


