"""Integração Home Assistant para centrais de alarme Intelbras (ISECNet/ISECMobile)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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

        if coordinator.supports_extended_eeprom:
            try:
                await coordinator.async_refresh_zone_names()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Não foi possível buscar os nomes de zona na configuração inicial; "
                    "use o botão de sincronização para tentar novamente."
                )
    else:
        # Não chamamos async_config_entry_first_refresh(): ele levantaria
        # ConfigEntryNotReady (pois o client recusa comandos desabilitado),
        # o que impediria até a criação do próprio switch de conexão — e o
        # usuário ficaria sem forma de religar pela UI. Em vez disso, a
        # entrada é configurada normalmente, sem dados iniciais; as demais
        # entidades ficam "indisponíveis" até o switch ser ligado.
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


