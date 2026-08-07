"""Sensores binários: zonas e diagnósticos da central."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import DOMAIN, MANUFACTURER
from .coordinator import IntelbrasAlarmCoordinator

DIAGNOSTIC_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="ac_power_ok",
        translation_key="ac_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_missing_or_reversed",
        translation_key="battery_missing",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_short",
        translation_key="battery_short",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="aux_overload",
        translation_key="aux_overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="siren_wire_cut",
        translation_key="siren_wire_cut",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="siren_short_circuit",
        translation_key="siren_short_circuit",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="phone_line_cut",
        translation_key="phone_line_cut",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="event_communication_failure",
        translation_key="event_communication_failure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="partition_mode_enabled",
        translation_key="partitioned",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# O sinal já vem normalizado como "há rede elétrica" (True = OK) diretamente
# de protocol.py — nenhuma chave precisa de inversão aqui.
INVERTED_KEYS: set[str] = set()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator

    entities: list[BinarySensorEntity] = [
        IntelbrasDiagnosticBinarySensor(coordinator, entry, description)
        for description in DIAGNOSTIC_SENSORS
    ]
    entities.append(IntelbrasTriggeredBinarySensor(coordinator, entry))
    entities.append(IntelbrasZoneOpenFlagBinarySensor(coordinator, entry))

    for zone in range(1, coordinator.native_zone_count + 1):
        entities.append(IntelbrasZoneBinarySensor(coordinator, entry, zone))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasDiagnosticBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Sensores de diagnóstico geral da central (rede, bateria, problemas)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IntelbrasAlarmCoordinator,
        entry: ConfigEntry,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        value = getattr(self.coordinator.data, self.entity_description.key)
        return not value if self.entity_description.key in INVERTED_KEYS else value


class IntelbrasTriggeredBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """"Central disparada".

    Liga quando o bit 6 do Status23 (2018/1016) ou Status30 (4010) está em
    1 **E** a sirene está realmente tocando (Status38/46, bit 2). O bit 6
    sozinho é "latched": fica em 1 até a MESMA partição que disparou ser
    reativada — se outra partição for armada nesse meio-tempo, o bit 6
    continua em 1 e geraria um falso "disparada" nela (confirmado pelo
    usuário com captura real de bytes). Exigir a sirene tocando também
    filtra esse falso positivo, já que uma memória antiga de disparo não
    tem a sirene ativa.
    """

    _attr_has_entity_name = True
    _attr_name = "Central disparada"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_triggered"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.zone_triggered

    @property
    def extra_state_attributes(self) -> dict:
        """Expõe os dois sinais separadamente, para diagnóstico sem log.

        ``bit_6_latched`` é o valor bruto (pode ficar "preso" em 1 — ver
        docstring da classe); ``sirene_ligada`` é a condição extra que
        filtra esse problema; o estado do sensor (``is_on``) é a junção
        dos dois. Visível em Configurações → Entidades → "Central
        disparada" → engrenagem → Informações/Detalhes.
        """
        status = self.coordinator.data
        if status is None:
            return {}
        return {
            f"{status.status_byte_name}_bruto": f"0x{status.status_byte_raw:02X}",
            "bit_6_latched": status.trigger_bit_latched,
            "sirene_ligada": status.siren_on,
        }


class IntelbrasZoneOpenFlagBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """"Alguma zona aberta" — flag agregada do bit 2 do Status23/30.

    Diferente do sensor de contagem "Zonas abertas" (que soma o bitmap
    zona a zona) e dos `binary_sensor` individuais por zona — este reflete
    diretamente um único bit do byte de status, sem cruzar com o bitmap.
    Regra confirmada pelo usuário a partir de captura real de bytes.
    """

    _attr_has_entity_name = True
    _attr_name = "Alguma zona aberta"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_zone_open_flag"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.zone_open_flag

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.data
        if status is None:
            return {}
        return {f"{status.status_byte_name}_bruto": f"0x{status.status_byte_raw:02X}"}


class IntelbrasZoneBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Estado (aberta/fechada) de uma zona, com atributos extras de diagnóstico.

    A documentação distingue "zona aberta" (estado físico atual do sensor) de
    "zona violada" (o evento de alarme que essa zona gerou) e "zona anulada"
    (bypass). Para manter uma entidade por zona, expomos "aberta" como estado
    principal (mais próximo do conceito de um binary_sensor door/window) e os
    demais como atributos.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone}"
        self._attr_device_info = _device_info(entry)

    @property
    def name(self) -> str:
        custom_name = self.coordinator.zone_names.get(self._zone)
        return custom_name or f"Zona {self._zone:02d}"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.zones_open.get(self._zone)

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.data
        if status is None:
            return {}
        return {
            "violada": status.zones_violated.get(self._zone, False),
            "anulada_bypass": status.zones_bypassed.get(self._zone, False),
            "bateria_baixa": status.zones_low_battery.get(self._zone, False),
        }
