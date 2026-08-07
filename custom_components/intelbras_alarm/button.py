"""Entidades button: sincronizar nomes de zona (4010) e pânico."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntelbrasAlarmData
from .const import DOMAIN, MANUFACTURER, PANIC_AUDIBLE, PANIC_FIRE, PANIC_MEDICAL, PANIC_SILENT
from .coordinator import IntelbrasAlarmCoordinator

PANIC_BUTTONS = (
    ("panic_silent", "Pânico silencioso", PANIC_SILENT, "mdi:shield-alert"),
    ("panic_audible", "Pânico audível", PANIC_AUDIBLE, "mdi:alarm-light"),
    ("panic_medical", "Emergência médica", PANIC_MEDICAL, "mdi:medical-bag"),
    ("panic_fire", "Incêndio", PANIC_FIRE, "mdi:fire"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator

    entities: list[ButtonEntity] = [
        IntelbrasPanicButton(coordinator, entry, key, name, code, icon)
        for key, name, code, icon in PANIC_BUTTONS
    ]
    entities.append(IntelbrasBypassOpenZonesButton(coordinator, entry))
    entities.append(IntelbrasBypassViolatedZonesButton(coordinator, entry))
    entities.append(IntelbrasClearBypassButton(coordinator, entry))

    if coordinator.supports_zone_names:
        entities.append(IntelbrasSyncZoneNamesButton(coordinator, entry))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasSyncZoneNamesButton(ButtonEntity):
    """Rebusca os nomes de zona gravados na EEPROM da central (somente 4010).

    Útil quando os nomes das zonas são alterados pelo teclado da central
    depois da configuração inicial da integração.
    """

    _attr_has_entity_name = True
    _attr_name = "Sincronizar nomes de zona"
    _attr_icon = "mdi:sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_sync_zone_names"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_refresh_zone_names()


class IntelbrasPanicButton(ButtonEntity):
    """Dispara um dos quatro tipos de pânico suportados pelo comando 0x45."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: IntelbrasAlarmCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        code: int,
        icon: str,
    ) -> None:
        self._coordinator = coordinator
        self._code = code
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_panic(self._code)


class IntelbrasBypassOpenZonesButton(ButtonEntity):
    """Anula (bypass) todas as zonas atualmente abertas (comando 0x42).

    Equivalente ao atalho existente no fluxo Node-RED original: útil para
    armar a central rapidamente com uma zona conhecida aberta (ex.: uma
    janela para ventilação), sem precisar anular zona a zona pelo teclado.
    Anulações já existentes em outras zonas são preservadas.
    """

    _attr_has_entity_name = True
    _attr_name = "Anular zonas abertas"
    _attr_icon = "mdi:door-open"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_bypass_open_zones"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_bypass_open_zones()


class IntelbrasBypassViolatedZonesButton(ButtonEntity):
    """Anula (bypass) todas as zonas atualmente violadas (comando 0x42).

    Útil após um disparo, para conseguir rearmar a central sem que a zona
    que causou o disparo impeça a ativação (NACK 0xE4 "Zonas abertas").
    Anulações já existentes em outras zonas são preservadas.
    """

    _attr_has_entity_name = True
    _attr_name = "Anular zonas violadas"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_bypass_violated_zones"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_bypass_violated_zones()


class IntelbrasClearBypassButton(ButtonEntity):
    """Remove TODAS as anulações de zona (reativa todas as zonas de uma vez)."""

    _attr_has_entity_name = True
    _attr_name = "Remover todas as anulações de zona"
    _attr_icon = "mdi:restore"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_clear_bypass"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        await self._coordinator.async_clear_bypass()
