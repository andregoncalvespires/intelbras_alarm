"""Entidade camera: última foto de evento (AMT 8000, sensores com câmera).

EXPERIMENTAL / INCOMPLETO — ver README_DETALHADO.md, seção "AMT 8000
(experimental)" e ``coordinator.async_request_event_photo``.

⚠️ LACUNA CONHECIDA: o formato do registro de evento decodificado hoje
(``protocol_amt8000.parse_event_record``) só extrai um flag booleano
"tem foto" — o **índice** exato que a central espera de volta para
solicitar aquela foto específica (comando ``0x0BB0``) ainda não foi
identificado com confiança no formato do evento novo (``0x3900``). Por
isso, esta entidade funciona (mostra "sem imagem disponível" com
segurança) mas ainda não consegue de fato baixar uma foto real até essa
lacuna ser fechada com uma captura de tráfego real. Ver
``coordinator.async_request_event_photo`` para o restante do fluxo
(autenticação + fragmentos), também incompleto pelo mesmo motivo.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelbrasAlarmData
from .const import AMT8000_MEDIA_SUBDIR, DOMAIN, FAMILY_8000, MANUFACTURER
from .coordinator import IntelbrasAlarmCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data: IntelbrasAlarmData = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator
    if coordinator.family != FAMILY_8000:
        # Esta entidade só existe para a AMT 8000 — as demais famílias
        # não têm sensores com câmera nem protocolo de fotos.
        return
    async_add_entities([IntelbrasAmt8000EventCamera(hass, coordinator, entry)])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer=MANUFACTURER)


class IntelbrasAmt8000EventCamera(CoordinatorEntity[IntelbrasAlarmCoordinator], Camera):
    """Última foto disponível de um evento com câmera (AMT 8000).

    Salva o arquivo em ``/media/amt8000/<entry_id>/`` (diretório de mídia
    do Home Assistant) — decisão de arquitetura registrada no histórico
    do projeto — em vez de manter só em memória, para que a foto continue
    acessível (histórico) mesmo depois de um novo evento chegar.
    """

    _attr_has_entity_name = True
    _attr_name = "Última foto de evento"
    _attr_icon = "mdi:cctv"

    def __init__(
        self, hass: HomeAssistant, coordinator: IntelbrasAlarmCoordinator, entry: ConfigEntry
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_event_photo"
        self._attr_device_info = _device_info(entry)
        self._media_dir = Path(hass.config.media_dirs.get("local", hass.config.path("media"))) / AMT8000_MEDIA_SUBDIR / entry.entry_id
        self._last_fetched_key: str | None = None
        self._last_image_bytes: bytes | None = None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Devolve a última foto disponível, buscando na central se necessário.

        Procura o evento mais recente com ``foto=True`` em
        ``coordinator.recent_events``; se já foi buscado antes (mesma
        chave data/hora+partição), usa o cache em memória — só chama
        ``async_request_event_photo`` de novo para um evento novo.
        Devolve ``None`` (sem imagem) em qualquer falha, nunca levanta
        exceção — ver limitação conhecida no topo deste arquivo.
        """
        eventos_com_foto = [ev for ev in self.coordinator.recent_events if ev.get("foto")]
        if not eventos_com_foto:
            return None
        evento = eventos_com_foto[0]  # já ordenado do mais recente pro mais antigo
        chave = f"{evento['data_hora'].isoformat()}_{evento.get('particao')}"

        if chave == self._last_fetched_key and self._last_image_bytes is not None:
            return self._last_image_bytes

        # Índice a enviar para 0x0BB0 — ver lacuna conhecida no topo do
        # arquivo: ainda não temos o índice real, usamos os bytes do
        # código do evento como melhor tentativa (provavelmente
        # incorreto até isso ser confirmado por captura própria).
        photo_index = bytes.fromhex(evento["codigo_raw"]) if evento.get("codigo_raw") else b"\x00\x00"

        image_bytes = await self.coordinator.async_request_event_photo(photo_index)
        if image_bytes is None:
            return None

        self._last_fetched_key = chave
        self._last_image_bytes = image_bytes

        try:
            await self._hass.async_add_executor_job(self._save_to_media, evento, image_bytes)
        except OSError as err:
            _LOGGER.warning("AMT 8000: não foi possível salvar a foto em /media: %s", err)

        return image_bytes

    def _save_to_media(self, evento: dict, image_bytes: bytes) -> None:
        self._media_dir.mkdir(parents=True, exist_ok=True)
        filename = evento["data_hora"].strftime("%Y%m%d_%H%M%S") + ".jpg"
        (self._media_dir / filename).write_bytes(image_bytes)
