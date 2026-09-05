"""Entidades button: sincronizar nomes de zona (4010), pânico e anulação de zonas."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    entities.append(IntelbrasBypassOpenOrViolatedZonesButton(coordinator, entry))
    entities.append(IntelbrasClearBypassButton(coordinator, entry))

    if coordinator.supports_extended_eeprom or coordinator.supports_legacy_eeprom:
        entities.append(IntelbrasSyncZoneNamesButton(coordinator, entry))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class _IntelbrasButtonBase(ButtonEntity):
    """Base comum: disponibilidade acompanha o coordinator.

    Sem isso, um botão continuava aparecendo "disponível" mesmo com o
    switch "Conexão com a central" desligado (ou qualquer outra falha de
    comunicação) — podendo levar o usuário a pressionar um comando que na
    prática não seria entregue. Ligado a ``coordinator.last_update_success``
    (o mesmo sinal que todas as outras entidades baseadas em
    ``CoordinatorEntity`` já usam), sem herdar de ``CoordinatorEntity``
    propriamente (esses botões não exibem dados do coordinator, só agem).

    ⚠️ Bug real corrigido (relatado pelo usuário): ``available`` acima já
    calculava o valor certo, mas nada disparava um novo
    ``async_write_ha_state()`` quando ``last_update_success`` mudava — a
    entidade ficava com o estado antigo travado até o próximo motivo
    qualquer de reescrita. Efeito observado: reiniciar o Home Assistant
    com a conexão desligada deixava os botões corretamente indisponíveis
    de início, mas religar a conexão depois não trazia eles de volta —
    e, na direção contrária, desligar a conexão com o Home Assistant já
    rodando nem sequer os deixava indisponíveis, já que não havia essa
    notificação em nenhuma das duas pontas. ``CoordinatorEntity`` resolve
    isso registrando um listener em ``async_added_to_hass()``
    (``BaseCoordinatorEntity`` em ``update_coordinator.py`` do próprio
    Home Assistant) — replicado abaixo manualmente, sem herdar a classe
    inteira (mesmo motivo do parágrafo acima). Seguro mesmo com
    ``update_interval=None`` do coordinator: ``async_add_listener()``
    chama ``_schedule_refresh()``, mas essa função já retorna
    imediatamente sem fazer nada quando ``update_interval`` é ``None``
    (confirmado direto no código-fonte do Home Assistant instalado) —
    não reabre a porta para o bug de agendamento sub-segundo já corrigido.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success


class IntelbrasSyncZoneNamesButton(_IntelbrasButtonBase):
    """Rebusca os nomes de zona gravados na EEPROM da central (somente 4010).

    Útil quando os nomes das zonas são alterados pelo teclado da central
    depois da configuração inicial da integração.
    """

    _attr_name = "Sincronizar nomes de zona"
    _attr_icon = "mdi:sync"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_sync_zone_names"

    async def async_press(self) -> None:
        await self._coordinator.async_refresh_zone_names()


class IntelbrasPanicButton(_IntelbrasButtonBase):
    """Dispara um dos quatro tipos de pânico suportados pelo comando 0x45."""

    def __init__(
        self,
        coordinator: IntelbrasAlarmCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        code: int,
        icon: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._code = code
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self._coordinator.async_panic(self._code)


class IntelbrasBypassOpenZonesButton(_IntelbrasButtonBase):
    """Anula (bypass) todas as zonas atualmente abertas (comando 0x42).

    Equivalente ao atalho existente no fluxo Node-RED original: útil para
    armar a central rapidamente com uma zona conhecida aberta (ex.: uma
    janela para ventilação), sem precisar anular zona a zona pelo teclado.
    Anulações já existentes em outras zonas são preservadas.
    """

    _attr_name = "Anular zonas abertas"
    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_bypass_open_zones"

    async def async_press(self) -> None:
        await self._coordinator.async_bypass_open_zones()


class IntelbrasBypassViolatedZonesButton(_IntelbrasButtonBase):
    """Anula (bypass) todas as zonas atualmente violadas (comando 0x42).

    Útil após um disparo, para conseguir rearmar a central sem que a zona
    que causou o disparo impeça a ativação (NACK 0xE4 "Zonas abertas").
    Anulações já existentes em outras zonas são preservadas.
    """

    _attr_name = "Anular zonas violadas"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_bypass_violated_zones"

    async def async_press(self) -> None:
        await self._coordinator.async_bypass_violated_zones()


class IntelbrasBypassOpenOrViolatedZonesButton(_IntelbrasButtonBase):
    """Anula, numa única operação, todas as zonas abertas OU violadas.

    Diferente de apertar os dois botões separados em sequência: o comando
    0x42 é absoluto (redefine a anulação das 64 zonas de uma vez), então a
    segunda anulação apagaria o efeito da primeira se cada botão calculasse
    seu alvo de forma independente. Este botão une os dois conjuntos antes
    de montar um único comando.
    """

    _attr_name = "Anular zonas abertas ou violadas"
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_bypass_open_or_violated_zones"

    async def async_press(self) -> None:
        await self._coordinator.async_bypass_open_or_violated_zones()


class IntelbrasClearBypassButton(_IntelbrasButtonBase):
    """Remove TODAS as anulações de zona (reativa todas as zonas de uma vez)."""

    _attr_name = "Remover todas as anulações de zona"
    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_clear_bypass"

    async def async_press(self) -> None:
        await self._coordinator.async_clear_bypass()
