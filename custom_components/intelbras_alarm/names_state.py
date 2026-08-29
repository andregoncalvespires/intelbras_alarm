"""Persistência dos nomes de zona/usuário lidos da EEPROM, para
sobreviver a reinícios do Home Assistant sem precisar reconsultar a
central toda vez.

BUG REAL corrigido (relatado pelo usuário): antes desta persistência,
``coordinator.zone_names``/``user_names`` só existiam na memória do
processo — qualquer reinício do Home Assistant os zerava, e a
sincronização automática só rodava se a conexão com a central já
estivesse habilitada naquele exato momento do (re)carregamento. Sequência
observada: conexão desligada → reinício do HA → religar a conexão →
nomes nunca mais eram buscados automaticamente (nada disparava uma nova
sincronização ao religar), e as entidades caíam de volta nos nomes
genéricos ("Zona 01" etc.), mesmo com os nomes reais ainda intactos na
EEPROM da central.

Usa ``homeassistant.helpers.storage.Store`` (mesmo padrão já usado em
``connection_state.py``) — um arquivo JSON próprio em ``.storage/``,
independente de ``ConfigEntry.data``/``options`` (evitaria disparar uma
recarga completa da entrada a cada sincronização, se fosse guardado em
``options``).
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_STORAGE_VERSION = 1


def _store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}_{entry_id}_names")


async def async_load_names(
    hass: HomeAssistant, entry_id: str
) -> tuple[dict[int, str], dict[int, str]] | None:
    """Devolve ``(zone_names, user_names)`` salvos, ou ``None`` se nunca
    houve uma sincronização bem-sucedida antes (primeira configuração de
    verdade) — usado para decidir se vale a pena tentar uma sincronização
    automática no (re)carregamento (só quando não há nada salvo ainda) ou
    simplesmente carregar o que já se sabe, sem arriscar sobrescrever com
    uma tentativa que pode falhar/ser pulada (ex.: conexão desligada).
    """
    data = await _store(hass, entry_id).async_load()
    if data is None:
        return None
    zone_names = {int(k): v for k, v in data.get("zone_names", {}).items()}
    user_names = {int(k): v for k, v in data.get("user_names", {}).items()}
    return zone_names, user_names


async def async_save_names(
    hass: HomeAssistant,
    entry_id: str,
    zone_names: dict[int, str],
    user_names: dict[int, str],
) -> None:
    """Salva os nomes atuais para sobreviver a um reinício.

    Chamado após toda sincronização bem-sucedida (automática na primeira
    configuração, ou manual via o botão "Sincronizar nomes de zona") —
    vira a nova "última versão conhecida boa", usada em qualquer
    (re)carregamento futuro em vez de reconsultar a central.
    """
    await _store(hass, entry_id).async_save(
        {
            "zone_names": {str(k): v for k, v in zone_names.items()},
            "user_names": {str(k): v for k, v in user_names.items()},
        }
    )
