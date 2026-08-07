"""Persistência leve do estado do switch de conexão (liga/desliga central).

Usa ``homeassistant.helpers.storage.Store`` (um arquivo JSON próprio em
``.storage/``) em vez de ``ConfigEntry.options``, para que ligar/desligar
esse switch não dispare uma recarga completa da entrada de configuração
(como aconteceria se fosse guardado em ``options``, via
``add_update_listener``) — é só um "lembrete" de qual era o último estado
antes do Home Assistant ter sido reiniciado.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1


def _store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}_{entry_id}_connection_enabled")


async def async_load_connection_enabled(hass: HomeAssistant, entry_id: str) -> bool:
    """Retorna o último estado salvo do switch de conexão (padrão: ligado)."""
    data = await _store(hass, entry_id).async_load()
    if data is None:
        return True
    return bool(data.get("enabled", True))


async def async_save_connection_enabled(hass: HomeAssistant, entry_id: str, enabled: bool) -> None:
    """Salva o estado atual do switch de conexão para sobreviver a um reinício."""
    await _store(hass, entry_id).async_save({"enabled": enabled})
