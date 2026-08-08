"""Entidades sensor: nível de bateria, contadores de zona e diagnóstico de comando."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import DOMAIN, MANUFACTURER
from .coordinator import IntelbrasAlarmCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    async_add_entities(
        [
            IntelbrasBatterySensor(coordinator, entry),
            IntelbrasZoneCountSensor(
                coordinator, entry, key="open", name="Zonas abertas", icon="mdi:door-open"
            ),
            IntelbrasZoneCountSensor(
                coordinator,
                entry,
                key="violated",
                name="Zonas violadas",
                icon="mdi:alert-circle-outline",
            ),
            IntelbrasZoneCountSensor(
                coordinator,
                entry,
                key="bypassed",
                name="Zonas anuladas",
                icon="mdi:door-closed-lock",
            ),
            IntelbrasLastCommandResultSensor(coordinator, entry),
        ]
    )


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasBatterySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Nível estimado da bateria interna da central (0/25/50/75/100 %)."""

    _attr_has_entity_name = False
    _attr_name = "Bateria"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_battery_level"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.battery_level


_ZONE_COUNT_FIELDS = {
    "open": "zones_open",
    "violated": "zones_violated",
    "bypassed": "zones_bypassed",
}


class IntelbrasZoneCountSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Contador de zonas em determinado estado (abertas/violadas/anuladas).

    Equivalente aos sensores de contagem existentes no fluxo Node-RED
    original; útil para automações e para um resumo rápido no dashboard
    sem precisar somar manualmente os `binary_sensor` de zona.
    """

    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "zonas"
    _attr_state_class = "measurement"

    def __init__(
        self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, key: str, name: str, icon: str
    ) -> None:
        super().__init__(coordinator)
        self._field = _ZONE_COUNT_FIELDS[key]
        self._attr_unique_id = f"{entry.entry_id}_zone_count_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int | None:
        status = self.coordinator.data
        if status is None:
            return None
        zone_map: dict[int, bool] = getattr(status, self._field)
        # Só conta zonas dentro do nº nativo do modelo (evita contar bytes
        # de zonas não existentes na central real).
        native = self.coordinator.native_zone_count
        return sum(1 for zone, value in zone_map.items() if value and zone <= native)

    @property
    def extra_state_attributes(self) -> dict:
        """Lista as zonas específicas, igual ao padrão do fluxo Node-RED original."""
        status = self.coordinator.data
        if status is None:
            return {}
        zone_map: dict[int, bool] = getattr(status, self._field)
        native = self.coordinator.native_zone_count
        zones = sorted(zone for zone, value in zone_map.items() if value and zone <= native)
        attrs: dict = {"zonas": zones}
        if self.coordinator.zone_names:
            attrs["zonas_nomes"] = [
                f"{zone:02d} - {self.coordinator.zone_names.get(zone, f'Zona {zone:02d}')}"
                for zone in zones
            ]
        return attrs


class IntelbrasLastCommandResultSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Descrição textual do resultado do último comando enviado à central.

    Reflete diretamente as respostas ACK/NACK documentadas na seção 6.1
    (ex.: "OK", "Senha incorreta", "Zonas abertas", "Comando descontinuado")
    — equivalente às mensagens de log/diagnóstico existentes no fluxo
    Node-RED original.
    """

    _attr_has_entity_name = False
    _attr_name = "Último comando"
    _attr_icon = "mdi:message-text-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_last_command_result"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str | None:
        return self.coordinator.last_command_result

    @property
    def extra_state_attributes(self) -> dict:
        """Sequência completa da última resposta de status + rastro do último comando real.

        Dois grupos de atributos deliberadamente separados:
        - ``ultima_resposta_status_bruta``: a cada ciclo de polling (padrão
          0,25s) — muda rápido demais para acompanhar um comando específico.
        - ``ultimo_comando_*``: só atualiza quando um comando de verdade é
          enviado (armar, desarmar, PGM, sirene, pânico, bypass) — nunca
          pela consulta de status. Fica parado até o próximo comando real,
          dando tempo de analisar com calma qual foi a ação, o frame
          enviado e a resposta específica da central para ela.
        """
        attrs: dict = {}
        if self.coordinator.last_status_raw is not None:
            attrs["ultima_resposta_status_bruta"] = self.coordinator.last_status_raw
        if self.coordinator.last_command_action is not None:
            attrs["ultimo_comando_finalidade"] = self.coordinator.last_command_action
        if self.coordinator.last_command_frame_hex is not None:
            attrs["ultimo_comando_enviado"] = self.coordinator.last_command_frame_hex
        if self.coordinator.last_command_response_hex is not None:
            attrs["ultimo_comando_resposta"] = self.coordinator.last_command_response_hex
        return attrs
