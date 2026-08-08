"""Entidades switch: PGMs, sirene e conexão com a central."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import DOMAIN, MANUFACTURER, PGM_ADDRESSES
from .coordinator import IntelbrasAlarmCoordinator
from .panel_client import PanelClient


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    client = data.client

    entities: list[SwitchEntity] = [
        IntelbrasSirenSwitch(coordinator, entry),
        IntelbrasConnectionSwitch(client, coordinator, entry),
    ]
    for pgm in range(1, coordinator.pgm_count + 1):
        entities.append(IntelbrasPgmSwitch(coordinator, entry, pgm))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasPgmSwitch(CoordinatorEntity[IntelbrasAlarmCoordinator], SwitchEntity):
    """PGM da central, controlada pelo comando 0x50 (liga/desliga)."""

    _attr_has_entity_name = False

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, pgm: int) -> None:
        super().__init__(coordinator)
        self._pgm = pgm
        self._address = PGM_ADDRESSES[pgm]
        self._attr_unique_id = f"{entry.entry_id}_pgm_{pgm}"
        self._attr_name = f"PGM {pgm}"
        self._attr_device_info = _device_info(entry)
        self._attr_icon = "mdi:electric-switch"
        # PGM 1-3 existem na maioria das instalações (onboard); PGM 4-19 só
        # existem se houver expansoras físicas (a central não informa
        # quantas estão instaladas). Para não poluir a lista de entidades
        # com 16 switches provavelmente inúteis, a funcionalidade continua
        # existindo (entidade é criada), mas some PGM 4-19 desabilitados
        # por padrão — o usuário habilita manualmente as que se aplicam à
        # sua instalação (Configurações → Entidades → mostrar desabilitadas).
        self._attr_entity_registry_enabled_default = pgm <= 3

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pgm_state.get(self._pgm)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_pgm(self._address, True, pgm=self._pgm)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_pgm(self._address, False, pgm=self._pgm)


class IntelbrasSirenSwitch(CoordinatorEntity[IntelbrasAlarmCoordinator], SwitchEntity):
    """Liga/desliga a sirene (comandos 0x43/0x63)."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:bullhorn"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_siren"
        self._attr_name = "Sirene"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.siren_on

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_siren(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_siren(False)


class IntelbrasConnectionSwitch(SwitchEntity):
    """Liga/desliga a comunicação TCP com a central (manutenção/testes).

    Não herda de CoordinatorEntity de propósito: precisa continuar
    disponível e responsiva mesmo quando o coordinator está em falha
    (é exatamente essa a entidade usada para reativar a comunicação).

    O estado é persistido (ver ``connection_state.py``) para que, se o
    usuário desligar este switch e reiniciar o Home Assistant em seguida,
    a integração volte já desligada — sem tentar abrir nenhuma conexão
    com a central automaticamente (ver ``__init__.py``).
    """

    _attr_has_entity_name = False
    _attr_icon = "mdi:lan-connect"
    _attr_entity_registry_enabled_default = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, client: PanelClient, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry
    ) -> None:
        self._client = client
        self._coordinator = coordinator
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_connection"
        self._attr_name = "Conexão com a central"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._client.enabled

    @property
    def available(self) -> bool:
        return True

    async def async_turn_on(self, **kwargs) -> None:
        from .connection_state import async_save_connection_enabled

        await self._client.set_enabled(True)
        await async_save_connection_enabled(self.hass, self._entry_id, True)
        self.async_write_ha_state()
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        from .connection_state import async_save_connection_enabled

        await self._client.set_enabled(False)
        await async_save_connection_enabled(self.hass, self._entry_id, False)
        self.async_write_ha_state()
