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
        key="ac_power_fault",
        name="Rede elétrica",
        # PROBLEM (não mais PLUG): a pedido do usuário, o valor não é mais
        # invertido — reflete o bit 0 do Status29/36 cru (1 = falta de
        # rede elétrica = problema), então "ligado" agora significa
        # problema, não "está funcionando" (semântica de device_class
        # PROBLEM, não PLUG).
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_low",
        name="Bateria fraca",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_missing_or_reversed",
        name="Bateria ausente ou invertida",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="battery_short",
        name="Curto-circuito na bateria",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="aux_overload",
        name="Sobrecarga na saída auxiliar",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="problem",
        name="Problema na central",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="siren_wire_cut",
        name="Corte no fio da sirene",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="siren_short_circuit",
        name="Curto-circuito no fio da sirene",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="phone_line_cut",
        name="Corte na linha telefônica",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="event_communication_failure",
        name="Falha ao comunicar evento",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="partition_mode_enabled",
        name="Particionamento habilitado",
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

    for n in range(1, 5):
        entities.append(IntelbrasKeypadProblemBinarySensor(coordinator, entry, n))
        entities.append(IntelbrasReceiverProblemBinarySensor(coordinator, entry, n))

    if coordinator.family == "4010":
        for n in range(1, 5):
            entities.append(IntelbrasPgmExpanderProblemBinarySensor(coordinator, entry, n))
        for n in range(1, 7):
            entities.append(IntelbrasZoneExpanderProblemBinarySensor(coordinator, entry, n))

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
        self._attr_name = description.name
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


class IntelbrasKeypadProblemBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Problema no teclado N (Status30 2018/1016, Status37 4010).

    Expõe o tamper daquele teclado (Status32/42, bits 4-7) como atributo,
    a pedido do usuário — informação relacionada, mas de um byte diferente.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Desabilitado por padrão: nem toda instalação tem teclados/receptores
    # extras cabeados/pareados — o usuário habilita manualmente os que
    # existem de fato (Configurações → Entidades → mostrar desabilitadas).
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, keypad: int) -> None:
        super().__init__(coordinator)
        self._keypad = keypad
        self._attr_unique_id = f"{entry.entry_id}_keypad_problem_{keypad}"
        self._attr_name = f"Problema no teclado {keypad}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.keypad_problem.get(self._keypad)

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.data
        if status is None:
            return {}
        return {"tamper": status.keypad_tamper.get(self._keypad, False)}


class IntelbrasReceiverProblemBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Problema no receptor N (Status30 2018/1016, Status37 4010)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, receiver: int) -> None:
        super().__init__(coordinator)
        self._receiver = receiver
        self._attr_unique_id = f"{entry.entry_id}_receiver_problem_{receiver}"
        self._attr_name = f"Problema no receptor {receiver}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.receiver_problem.get(self._receiver)


class IntelbrasPgmExpanderProblemBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Problema no expansor de PGM N (Status38, só família 4010)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Desabilitado por padrão: nem toda 4010 tem expansoras de PGM
    # instaladas — o usuário habilita manualmente as que existem de fato.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, expander: int) -> None:
        super().__init__(coordinator)
        self._expander = expander
        self._attr_unique_id = f"{entry.entry_id}_pgm_expander_problem_{expander}"
        self._attr_name = f"Problema no expansor de PGM {expander}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.pgm_expander_problem.get(self._expander)


class IntelbrasZoneExpanderProblemBinarySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], BinarySensorEntity):
    """Problema no expansor de zonas N (Status38/39, só família 4010)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Mesmo raciocínio do expansor de PGM: nem toda instalação tem
    # expansoras de zona.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, expander: int) -> None:
        super().__init__(coordinator)
        self._expander = expander
        self._attr_unique_id = f"{entry.entry_id}_zone_expander_problem_{expander}"
        self._attr_name = f"Problema no expansor de zonas {expander}"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        if status is None:
            return None
        return status.zone_expander_problem.get(self._expander)


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
        self._attr_entity_registry_enabled_default = coordinator.zone_enabled_by_default(zone)

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
        attrs: dict = {
            "violada": status.zones_violated.get(self._zone, False),
            "anulada_bypass": status.zones_bypassed.get(self._zone, False),
        }
        # Só inclui os atributos abaixo se a central realmente reporta esse
        # dado para esta zona específica — algumas faixas de zona não têm
        # leitura de bateria/tamper/curto disponível no protocolo (ex.: a
        # 4010 nunca reporta bateria para as zonas 1-16, que são sempre
        # cabeadas, nunca sem fio; mostrar "False" ali seria enganoso, como
        # se fosse um dado monitorado e sempre OK, em vez de simplesmente
        # não aplicável).
        if self._zone in status.zones_low_battery:
            attrs["bateria_baixa"] = status.zones_low_battery[self._zone]
        if self._zone in status.zones_tamper:
            attrs["tamper"] = status.zones_tamper[self._zone]
        if self._zone in status.zones_short_circuit:
            attrs["curto_circuito"] = status.zones_short_circuit[self._zone]
        if self._zone in status.zones_comm_failure:
            # Só populado na AMT 8000 (sensores sem fio/RF) — ver
            # protocol_amt8000.py. Vazio {} nas demais famílias, então
            # este atributo simplesmente não aparece para elas.
            attrs["falha_comunicacao_rf"] = status.zones_comm_failure[self._zone]

        # AMT 2018 E SMART: atributos extras só disponíveis pra zonas
        # 25-48 (a central trata 1-24 como sempre cabeadas) — ver
        # protocol.parse_status_2018_esmart_extra, não validado contra
        # hardware real. Mesmo critério acima: só inclui se a chave
        # existir (resposta longa o bastante para alcançar o dado).
        extra = self.coordinator.esmart_extra
        if extra is not None:
            if self._zone in extra.zones_wireless:
                attrs["sem_fio"] = extra.zones_wireless[self._zone]
            if self._zone in extra.zones_tamper_esmart:
                attrs["tamper_esmart"] = extra.zones_tamper_esmart[self._zone]
            if self._zone in extra.zones_short_circuit_esmart:
                attrs["curto_circuito_esmart"] = extra.zones_short_circuit_esmart[self._zone]
            if self._zone in extra.zones_battery_low_esmart:
                attrs["bateria_baixa_esmart"] = extra.zones_battery_low_esmart[self._zone]
            if self._zone in extra.zones_supervised:
                attrs["supervisionada"] = extra.zones_supervised[self._zone]
            if self._zone in extra.zones_supervision_failure:
                attrs["falha_supervisao"] = extra.zones_supervision_failure[self._zone]
            if self._zone in extra.zones_device_model:
                attrs["modelo_dispositivo"] = extra.zones_device_model[self._zone]
        return attrs
