"""Entidades alarm_control_panel: central principal e partições."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import (
    CONF_CODE_REQUIRED_ARM,
    CONF_CODE_REQUIRED_DISARM,
    DEFAULT_CODE_REQUIRED_ARM,
    DEFAULT_CODE_REQUIRED_DISARM,
    DOMAIN,
    FAMILY_4010,
    MANUFACTURER,
)
from .coordinator import IntelbrasAlarmCoordinator

PARTITION_NAMES = {"A": "Partição A", "B": "Partição B", "C": "Partição C", "D": "Partição D"}

SERVICE_BYPASS_ZONE = "bypass_zone"
ATTR_ZONE = "zone"
ATTR_BYPASS = "bypass"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator

    entities: list[AlarmControlPanelEntity] = [
        IntelbrasCentralAlarmPanel(coordinator, entry)
    ]

    if coordinator.data and coordinator.data.partition_mode_enabled:
        partitions = ["A", "B", "C", "D"] if coordinator.family == FAMILY_4010 else ["A", "B"]
        for partition in partitions:
            entities.append(IntelbrasPartitionAlarmPanel(coordinator, entry, partition))

    async_add_entities(entities)

    # Serviço `intelbras_alarm.bypass_zone`, chamável de automações/scripts
    # e disponível para qualquer entidade alarm_control_panel desta central
    # (central ou partições, tanto faz — todas compartilham o mesmo
    # coordinator). Usa sempre a senha memorizada da central, como os
    # demais comandos que não são ativar/desativar (ver
    # `_BaseAlarmPanel.async_bypass_zone_service`).
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_BYPASS_ZONE,
        {
            vol.Required(ATTR_ZONE): vol.All(vol.Coerce(int), vol.Range(min=1, max=64)),
            vol.Optional(ATTR_BYPASS, default=True): cv.boolean,
        },
        "async_bypass_zone_service",
    )


def _device_info(entry: ConfigEntry, coordinator: IntelbrasAlarmCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model=entry.data.get("model_name"),
        sw_version=coordinator.data.firmware if coordinator.data else None,
    )


class _BaseAlarmPanel(CoordinatorEntity[IntelbrasAlarmCoordinator], AlarmControlPanelEntity):
    """Comportamento comum: mapeamento de status -> estado do alarm_control_panel."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(entry, coordinator)

        # Definido na configuração inicial da central (não editável depois
        # sem remover e reconfigurar a integração): se nenhuma das duas
        # opções for marcada, os comandos usam sempre a senha memorizada,
        # sem pedir nada na interface do Home Assistant.
        self._require_code_arm: bool = entry.data.get(CONF_CODE_REQUIRED_ARM, DEFAULT_CODE_REQUIRED_ARM)
        self._require_code_disarm: bool = entry.data.get(
            CONF_CODE_REQUIRED_DISARM, DEFAULT_CODE_REQUIRED_DISARM
        )
        self._attr_code_arm_required = self._require_code_arm
        if self._require_code_arm or self._require_code_disarm:
            self._attr_code_format = CodeFormat.NUMBER
        else:
            self._attr_code_format = None

    @property
    def extra_state_attributes(self) -> dict:
        """Diagnóstico comum a central e partições: bytes brutos nomeados.

        Mostra explicitamente QUAIS bytes do protocolo alimentam a
        lógica de armed/triggered para o modelo detectado — Status22 na
        2018/1016, ou Status28+29 na 4010 (partições), mais Status23/30
        (disparo). Ver README, seção "Diagnóstico".
        """
        status = self.coordinator.data
        if status is None:
            return {}
        attrs: dict = {
            f"{name}_bruto": f"0x{value:02X}" for name, value in status.partition_status_bytes.items()
        }
        attrs[f"{status.status_byte_name}_bruto"] = f"0x{status.status_byte_raw:02X}"
        attrs["partitions_armed_bruto"] = status.partitions_armed
        return attrs

    def _resolve_password(
        self, code: str | None, required: bool, partition: str | None = None
    ) -> str:
        """Decide qual senha vai no comando ISECMobile enviado à central.

        Se a ação exigir código (configurado na inclusão da integração), o
        valor digitado na UI do Home Assistant é usado **diretamente como a
        senha do comando** — não é comparado contra a senha memorizada na
        configuração. Isso permite usar uma senha diferente cadastrada na
        própria central (ex.: uma senha de usuário secundária, ou a senha
        específica de uma partição). A central valida a senha; se estiver
        errada, o comando volta com NACK "Senha incorreta"
        (``protocol.NackError``), convertido pelo coordinator em um erro
        exibido na interface do Home Assistant — só é feita uma checagem
        local de formato (4 a 6 dígitos numéricos), nunca de conteúdo.

        Quando não exigido, usa a senha configurada para ``partition`` (se
        houver uma específica cadastrada — só possível na 4010, ver
        config_flow.py) ou a senha principal, automaticamente e sem
        depender do que (se algo) foi digitado.
        """
        if not required:
            return self.coordinator.password_for_partition(partition)
        if not code or not (4 <= len(code) <= 6) or not code.isdigit():
            raise HomeAssistantError("Informe uma senha válida (4 a 6 dígitos numéricos)")
        return code

    def _compute_state(
        self, activated: bool, mode_key: str, zone_triggered: bool
    ) -> AlarmControlPanelState:
        # Requisito de negócio: se a partição/central não está ativada, o
        # estado é sempre "desarmado", mesmo que o bit de "zona disparada"
        # continue vindo em 1 da central (a central só zera esse bit após
        # nova ativação em alguns modelos).
        if not activated:
            return AlarmControlPanelState.DISARMED
        if zone_triggered:
            return AlarmControlPanelState.TRIGGERED
        if self.coordinator.armed_home_mode.get(mode_key):
            return AlarmControlPanelState.ARMED_HOME
        return AlarmControlPanelState.ARMED_AWAY

    async def async_bypass_zone_service(self, zone: int, bypass: bool = True) -> None:
        """Implementa o serviço `intelbras_alarm.bypass_zone`.

        Anula (``bypass=True``) ou reativa (``bypass=False``) uma zona
        específica pelo número, preservando as demais anulações já
        existentes. Diferente das ações de ativar/desativar, este comando
        **sempre** usa a senha memorizada da central — não é afetado pelas
        opções "Exigir senha ao ativar/desativar" (só se aplicam a
        armar/desarmar). Chamável de automações e scripts com:

        ```yaml
        service: intelbras_alarm.bypass_zone
        target:
          entity_id: alarm_control_panel.central
        data:
          zone: 5
          bypass: true
        ```
        """
        if not (1 <= zone <= self.coordinator.native_zone_count):
            raise HomeAssistantError(
                f"Zona {zone} fora do intervalo válido para este modelo "
                f"(1 a {self.coordinator.native_zone_count})"
            )
        if bypass:
            await self.coordinator.async_bypass_zones({zone})
        else:
            await self.coordinator.async_unbypass_zone(zone)


class IntelbrasCentralAlarmPanel(_BaseAlarmPanel):
    """Entidade que representa a central como um todo (todas as partições)."""

    _attr_translation_key = "central"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_central"
        self._attr_name = None  # usa o nome do dispositivo
        # Modo Stay (armed_home) só é oferecido em modelos confirmados como
        # suportando de verdade o comando 0x50 — ver coordinator.supports_stay.
        self._attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
        if coordinator.supports_stay:
            self._attr_supported_features |= AlarmControlPanelEntityFeature.ARM_HOME

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = self.coordinator.data
        if status is None:
            return None
        return self._compute_state(status.activated, "CENTRAL", status.zone_triggered)

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.data
        if status is None:
            return {}
        attrs = dict(super().extra_state_attributes)
        attrs.update(
            {
                "modelo": status.model_name,
                "firmware": status.firmware,
                "problema": status.problem,
                "sirene_ligada": status.siren_on,
                "rede_eletrica_ok": status.ac_power_ok,
                "bateria_nivel": status.battery_level,
                "relogio_sincronizado": status.panel_datetime_synced,
            }
        )
        return attrs

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        password = self._resolve_password(code, self._require_code_disarm)
        await self.coordinator.async_disarm(None, password=password)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        password = self._resolve_password(code, self._require_code_arm)
        await self.coordinator.async_arm(None, stay=False, password=password)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        if not self.coordinator.supports_stay:
            raise HomeAssistantError(
                "Este modelo não suporta ativação em modo Stay (armed_home) — "
                "confirmado apenas para AMT 4010 SMART e AMT 2018 E SMART."
            )
        password = self._resolve_password(code, self._require_code_arm)
        await self.coordinator.async_arm(None, stay=True, password=password)


class IntelbrasPartitionAlarmPanel(_BaseAlarmPanel):
    """Entidade de partição individual (disarmed/armed_away/armed_home/triggered).

    O modo Stay por partição usa um conteúdo de 2 bytes no comando 0x41
    (partição + marcador Stay) — não documentado explicitamente na seção
    7.1, mas reproduzido do fluxo Node-RED original (ver protocol.cmd_arm).
    """

    def __init__(
        self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry, partition: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._partition = partition
        self._attr_unique_id = f"{entry.entry_id}_partition_{partition.lower()}"
        self._attr_name = PARTITION_NAMES[partition]
        self._attr_translation_key = "partition"
        # Mesma restrição de modo Stay da central — ver coordinator.supports_stay.
        self._attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
        if coordinator.supports_stay:
            self._attr_supported_features |= AlarmControlPanelEntityFeature.ARM_HOME

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = self.coordinator.data
        if status is None:
            return None
        armed = status.partitions_armed.get(self._partition, False)
        return self._compute_state(armed, self._partition, status.zone_triggered)

    @property
    def extra_state_attributes(self) -> dict:
        """Além dos bytes brutos (herdados da base), identifica o bit exato desta partição."""
        attrs = dict(super().extra_state_attributes)
        status = self.coordinator.data
        if status is not None and self._partition in status.partition_bit_map:
            byte_name, bit_index = status.partition_bit_map[self._partition]
            attrs["bit_desta_particao"] = f"bit {bit_index} do {byte_name}"
        return attrs

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        password = self._resolve_password(code, self._require_code_disarm, self._partition)
        await self.coordinator.async_disarm(self._partition, password=password)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        password = self._resolve_password(code, self._require_code_arm, self._partition)
        await self.coordinator.async_arm(self._partition, stay=False, password=password)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        if not self.coordinator.supports_stay:
            raise HomeAssistantError(
                "Este modelo não suporta ativação em modo Stay (armed_home) — "
                "confirmado apenas para AMT 4010 SMART e AMT 2018 E SMART."
            )
        password = self._resolve_password(code, self._require_code_arm, self._partition)
        await self.coordinator.async_arm(self._partition, stay=True, password=password)
