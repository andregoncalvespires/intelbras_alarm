"""Entidades sensor: nível de bateria, contadores de zona e diagnóstico de comando."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import (
    CONF_RECEPTOR_IP_ENABLED,
    DEFAULT_RECEPTOR_IP_ENABLED,
    DOMAIN,
    MANUFACTURER,
    MODEL_2018_SMART,
)
from .coordinator import IntelbrasAlarmCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    entities = [
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
        IntelbrasZoneCountSensor(
            coordinator,
            entry,
            key="low_battery",
            name="Zonas com bateria baixa",
            icon="mdi:battery-alert-variant-outline",
        ),
        IntelbrasLastCommandResultSensor(coordinator, entry),
        IntelbrasRecentEventsSensor(coordinator, entry),
        IntelbrasReceptorLastEventSensor(coordinator, entry),
        IntelbrasReceptorHeartbeatSensor(coordinator, entry),
    ]
    # Só a AMT 2018 E SMART manda esses dados (resposta 0x5D) — ver
    # protocol.parse_status_2018_esmart_extra e
    # README_DETALHADO.md.
    if coordinator.model_key == MODEL_2018_SMART:
        entities.append(IntelbrasESmartNetworkSensor(coordinator, entry))
        entities.append(IntelbrasESmartCellularSensor(coordinator, entry))
    # Tensão da fonte/bateria — só quando a senha de leitura de 6
    # dígitos está configurada E a família tem offset confirmado (ver
    # coordinator.supports_voltage_reading e const.VOLTAGE_OFFSETS).
    if coordinator.supports_voltage_reading:
        entities.append(IntelbrasSourceVoltageSensor(coordinator, entry))
        entities.append(IntelbrasBatteryVoltageSensor(coordinator, entry))
    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasBatterySensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Nível estimado da bateria interna da central (0/25/50/75/100 %)."""

    _attr_has_entity_name = True
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


class IntelbrasSourceVoltageSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Tensão da fonte de alimentação (comando ``[1, 0x17]`` dentro do
    ``0xE7``, ver ``coordinator.supports_voltage_reading``).

    Atualizada a cada 5 minutos, num agendamento próprio, **não** a cada
    ciclo do polling rápido de status (ver ``coordinator.async_refresh_voltage``
    e ``__init__.py``) — evita autenticações repetidas desnecessárias.
    """

    _attr_has_entity_name = True
    _attr_name = "Tensão da fonte"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tensao_fonte"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.tensao_fonte


class IntelbrasBatteryVoltageSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Tensão da bateria interna (comando ``[1, 0x17]`` dentro do ``0xE7``,
    ver ``coordinator.supports_voltage_reading``).

    Mesma cadência de atualização de ``IntelbrasSourceVoltageSensor`` (5
    em 5 minutos) — as duas vêm juntas na mesma resposta.
    """

    _attr_has_entity_name = True
    _attr_name = "Tensão da bateria"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tensao_bateria"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.tensao_bateria


_ZONE_COUNT_FIELDS = {
    "open": "zones_open",
    "violated": "zones_violated",
    "bypassed": "zones_bypassed",
    "low_battery": "zones_low_battery",
}


class IntelbrasZoneCountSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Contador de zonas em determinado estado (abertas/violadas/anuladas).

    Equivalente aos sensores de contagem existentes no fluxo Node-RED
    original; útil para automações e para um resumo rápido no dashboard
    sem precisar somar manualmente os `binary_sensor` de zona.
    """

    _attr_has_entity_name = True
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

    _attr_has_entity_name = True
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


class IntelbrasRecentEventsSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Eventos mais recentes lidos do log de eventos da central (EEPROM).

    Só é útil em modelos/firmwares com acesso ao comando 0x5C (ver
    ``coordinator.supports_extended_eeprom``) **ou** ao protocolo legado
    opcional (ver ``coordinator.supports_legacy_eeprom``) — nos demais,
    fica sempre indisponível, já que a leitura nunca é tentada.
    Atualizado pelo serviço ``intelbras_alarm.read_events`` (ver
    alarm_control_panel.py), não pelo polling normal — chamar esse
    serviço é o que dispara a leitura.

    O estado é só o evento mais recente, resumido (cabe folgado no limite
    de 255 caracteres de um estado do Home Assistant); a lista completa
    dos ``EVENT_ENTITY_RECENT_COUNT`` mais recentes (com todos os campos
    decodificados) fica nos atributos. O serviço em si devolve TODOS os
    eventos lidos (até 256) na resposta da chamada — só a entidade fica
    limitada, para não gerar um atributo enorme.
    """

    _attr_has_entity_name = True
    _attr_name = "Últimos eventos"
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_recent_events"
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return self.coordinator.supports_extended_eeprom or self.coordinator.supports_legacy_eeprom

    @property
    def native_value(self) -> str | None:
        eventos = self.coordinator.recent_events
        if not eventos:
            return "Nenhum evento lido ainda"
        ev = eventos[0]
        data_hora = ev["data_hora"].strftime("%d/%m/%Y %H:%M:%S")
        cod = ev["codigo_app"] or f"?{ev['codigo_raw']}"
        # Mantém dentro do limite de 255 caracteres de um estado do HA —
        # folgado aqui, mas evita qualquer risco se a descrição crescer.
        texto = f"{data_hora} · {cod} · {ev['descricao']}"
        return texto[:255]

    @property
    def extra_state_attributes(self) -> dict:
        eventos = self.coordinator.recent_events
        return {
            "eventos": [
                {
                    "data_hora": ev["data_hora"].strftime("%d/%m/%Y %H:%M:%S"),
                    "zona_usuario": ev["zona_usuario"],
                    "particao": ev["particao"],
                    "codigo": ev["codigo_app"] or f"desconhecido ({ev['codigo_raw']})",
                    "descricao": ev["descricao"],
                }
                for ev in eventos
            ]
        }


class IntelbrasReceptorLastEventSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Último evento recebido via Receptor IP — a central empurra sozinha,
    em tempo real, sem a integração precisar perguntar (ver receptor_ip.py).

    Diferente de "Últimos eventos" (que só existe em alguns
    modelos/firmwares e depende de chamar o serviço `read_events` para
    atualizar), esta entidade só existe se o Receptor IP estiver
    **habilitado** na configuração — e atualiza sozinha, assim que a
    central manda algo, sem precisar de nenhuma ação do usuário.

    Estado: descrição do evento concatenada com partição e zona/usuário,
    quando fazem sentido pro evento em questão (nem todo evento tem os
    três — ex.: "Teste periódico" não tem zona nem partição). Código e
    data/hora ficam nos atributos, como pedido.
    """

    _attr_has_entity_name = True
    _attr_name = "Último evento (Receptor IP)"
    _attr_icon = "mdi:access-point-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_receptor_last_event"
        self._attr_device_info = _device_info(entry)
        self._enabled = entry.data.get(CONF_RECEPTOR_IP_ENABLED, DEFAULT_RECEPTOR_IP_ENABLED)

    @property
    def available(self) -> bool:
        return self._enabled

    @property
    def native_value(self) -> str | None:
        evento = self.coordinator.receptor_last_event
        if evento is None:
            return "Nenhum evento recebido ainda"
        partes = [evento["descricao"]]
        if evento["particao"] != "-":
            partes.append(f"Partição {evento['particao']}")
        if evento["zona_usuario"] > 0:
            # Usa o nome (zona ou usuário) quando temos — ver
            # coordinator.on_receptor_event() e const.RECEPTOR_IP_EVENT_SUBJECT.
            # Sem nome disponível (não é um evento de zona/usuário, ou não
            # temos esse nome carregado), mostra só o número, como sempre.
            nome = evento.get("nome")
            partes.append(nome if nome else f"Zona/Usuário {evento['zona_usuario']}")
        # Mantém dentro do limite de 255 caracteres de um estado do HA —
        # folgado aqui, mas evita qualquer risco se a descrição crescer.
        return " — ".join(partes)[:255]

    @property
    def extra_state_attributes(self) -> dict:
        evento = self.coordinator.receptor_last_event
        if evento is None:
            return {}
        attrs: dict = {
            "codigo": evento["codigo"],
            "conta": evento["conta"],
            "particao": evento["particao"],
            "zona_usuario": evento["zona_usuario"],
            "nome": evento.get("nome"),
        }
        if evento["data_hora_evento"] is not None:
            attrs["data_hora_evento"] = evento["data_hora_evento"].strftime("%d/%m/%Y %H:%M:%S")
        return attrs


class IntelbrasReceptorHeartbeatSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Data/hora do último "sinal de vida" recebido via Receptor IP.

    Atualiza tanto em um heartbeat "puro" (comando 0xF7, que não carrega
    nenhuma data/hora própria) quanto em qualquer evento recebido — os
    dois indicam igualmente que a conexão está viva. A data/hora usada é
    sempre a **deste servidor** (Home Assistant), não a da central — o
    0xF7 não tem campo de data/hora nenhum, e essa foi a escolha
    confirmada com o usuário (mesmo critério dos scripts de referência
    testados antes desta funcionalidade ser incorporada à integração).
    """

    _attr_has_entity_name = True
    _attr_name = "Último sinal de vida (Receptor IP)"
    _attr_icon = "mdi:heart-pulse"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_receptor_last_heartbeat"
        self._attr_device_info = _device_info(entry)
        self._enabled = entry.data.get(CONF_RECEPTOR_IP_ENABLED, DEFAULT_RECEPTOR_IP_ENABLED)

    @property
    def available(self) -> bool:
        return self._enabled

    @property
    def native_value(self):
        return self.coordinator.receptor_last_heartbeat


class IntelbrasESmartNetworkSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Diagnóstico de rede — só existe na AMT 2018 E SMART.

    Extraído da resposta de status 0x5D (``const.CMD_STATUS_ESMART``),
    bytes 136-163 na numeração do app oficial — ver
    ``protocol.parse_status_2018_esmart_extra`` e README_DETALHADO.md,
    seção "AMT 2018 E Smart — dados adicionais". A resposta real varia
    de tamanho; se vier curta demais para alcançar essa seção, o estado
    fica ``None`` e os atributos ficam ausentes — nunca inventamos um
    valor. **Não validado contra hardware real.**
    """

    _attr_has_entity_name = True
    _attr_name = "Rede (diagnóstico)"
    _attr_icon = "mdi:ip-network-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_esmart_network"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str | None:
        extra = self.coordinator.esmart_extra
        return extra.data_network_type if extra else None

    @property
    def extra_state_attributes(self) -> dict:
        extra = self.coordinator.esmart_extra
        if extra is None:
            return {}
        return {
            "ip1_ethernet_online": extra.ip1_ethernet_online,
            "ip2_ethernet_online": extra.ip2_ethernet_online,
            "cloud_ethernet_online": extra.cloud_ethernet_online,
            "ip1_celular_online": extra.ip1_cellular_online,
            "ip2_celular_online": extra.ip2_cellular_online,
            "cloud_celular_online": extra.cloud_cellular_online,
            "endereco_ip": extra.ip_address,
            "mascara_rede": extra.netmask,
            "gateway": extra.gateway,
            "dns1": extra.dns1,
            "dns2": extra.dns2,
            "endereco_mac": extra.mac_address,
        }


class IntelbrasESmartCellularSensor(CoordinatorEntity[IntelbrasAlarmCoordinator], SensorEntity):
    """Diagnóstico do módulo celular/SIM — só existe na AMT 2018 E SMART.

    Mesma origem/ressalvas de ``IntelbrasESmartNetworkSensor`` — bytes
    164-203 na numeração do app oficial. Chip ID (ICCID) e IMEI ficam
    nos atributos por serem identificadores mais sensíveis, não no
    estado principal da entidade.
    """

    _attr_has_entity_name = True
    _attr_name = "Módulo celular (diagnóstico)"
    _attr_icon = "mdi:sim"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_esmart_cellular"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str | None:
        extra = self.coordinator.esmart_extra
        if extra is None or not extra.cellular_module_present:
            return None
        return extra.cellular_module_type

    @property
    def extra_state_attributes(self) -> dict:
        extra = self.coordinator.esmart_extra
        if extra is None:
            return {}
        return {
            "modulo_presente": extra.cellular_module_present,
            "sinal_celular_percent": extra.cellular_signal_percent,
            "chip_em_uso": extra.chip_in_use,
            "operadora": extra.carrier,
            "chip_id": extra.chip_id,
            "imei": extra.imei,
        }


