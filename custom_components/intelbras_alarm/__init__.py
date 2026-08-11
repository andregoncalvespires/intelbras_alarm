"""Integração Home Assistant para centrais de alarme Intelbras (ISECNet/ISECMobile)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .connection_state import async_load_connection_enabled
from .const import CONF_MODEL, CONF_PARTITION_PASSWORDS, CONF_PASSWORD, DEFAULT_REQUEST_TIMEOUT, DOMAIN
from .coordinator import IntelbrasAlarmCoordinator
from .panel_client import PanelClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
]


@dataclass
class IntelbrasAlarmData:
    client: PanelClient
    coordinator: IntelbrasAlarmCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # O estado do switch "Conexão com a central" é lido ANTES de qualquer
    # tentativa de comunicação — se o usuário desligou esse switch antes de
    # reiniciar o Home Assistant, a integração deve respeitar essa escolha
    # e não abrir nenhum socket com a central neste (re)carregamento.
    connection_enabled = await async_load_connection_enabled(hass, entry.entry_id)

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

        if coordinator.supports_zone_names:
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

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = IntelbrasAlarmData(client=client, coordinator=coordinator)

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
        await data.client.disconnect()
    return unload_ok

