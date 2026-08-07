"""Cliente TCP assíncrono e persistente para a central de alarme Intelbras.

A conexão é aberta uma única vez e mantida aberta; só é refeita se cair
(erro de socket, timeout ou reset pela central). Todas as requisições são
serializadas por um lock, pois o protocolo é estritamente requisição/resposta
(a central nunca envia nada sem antes receber um comando do "mestre").
"""
from __future__ import annotations

import asyncio
import logging

from .const import DEFAULT_TIMEOUT_ETHERNET
from .protocol import ParsedFrame, ProtocolError, parse_frame

_LOGGER = logging.getLogger(__name__)


class PanelConnectionError(Exception):
    """Falha ao conectar ou comunicar com a central."""


class PanelClient:
    """Mantém uma conexão TCP persistente com a central e serializa comandos."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = DEFAULT_TIMEOUT_ETHERNET,
        enabled: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._enabled = enabled  # controlado pelo switch de conexão

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        """Liga/desliga a comunicação com a central (switch de manutenção)."""
        self._enabled = enabled
        if not enabled:
            await self.disconnect()

    async def connect(self) -> None:
        if self._connected or not self._enabled:
            return
        async with self._lock:
            if self._connected:
                return
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._timeout,
                )
                self._connected = True
                _LOGGER.debug("Conectado à central em %s:%s", self._host, self._port)
            except (OSError, asyncio.TimeoutError) as err:
                self._connected = False
                raise PanelConnectionError(
                    f"Não foi possível conectar a {self._host}:{self._port}: {err}"
                ) from err

    async def disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        self._connected = False
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = None
        self._writer = None

    async def send_command(self, frame: bytes) -> ParsedFrame:
        """Envia um frame já pronto e aguarda a resposta correspondente.

        Reabre a conexão automaticamente se ela tiver caído; nunca fecha e
        reabre a cada requisição enquanto a conexão estiver saudável.
        """
        if not self._enabled:
            raise PanelConnectionError("Comunicação com a central está desativada")

        async with self._lock:
            if not self._connected:
                await self._connect_locked()

            assert self._writer is not None
            assert self._reader is not None
            try:
                self._writer.write(frame)
                await self._writer.drain()
                # O primeiro byte do frame de resposta é o "Nº Bytes"; a partir
                # dele sabemos exatamente quantos bytes ainda faltam ler
                # (comando + conteúdo + checksum), evitando misturar respostas.
                header = await asyncio.wait_for(
                    self._reader.readexactly(1), timeout=self._timeout
                )
                num_bytes = header[0]
                remainder = await asyncio.wait_for(
                    self._reader.readexactly(num_bytes + 1), timeout=self._timeout
                )
                raw = header + remainder
            except asyncio.TimeoutError as err:
                await self._close_locked()
                raise PanelConnectionError(
                    f"Falha de comunicação com a central: tempo limite excedido "
                    f"({self._timeout}s) aguardando resposta"
                ) from err
            except asyncio.IncompleteReadError as err:
                await self._close_locked()
                raise PanelConnectionError(
                    "Falha de comunicação com a central: conexão encerrada antes da "
                    f"resposta completa (esperado {err.expected}, recebido "
                    f"{len(err.partial)} bytes)"
                ) from err
            except OSError as err:
                await self._close_locked()
                detail = str(err) or err.__class__.__name__
                raise PanelConnectionError(
                    f"Falha de comunicação com a central: {detail}"
                ) from err

        try:
            return parse_frame(raw)
        except ProtocolError as err:
            raise PanelConnectionError(str(err)) from err

    async def _connect_locked(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            self._connected = True
            _LOGGER.debug("(Re)conectado à central em %s:%s", self._host, self._port)
        except asyncio.TimeoutError as err:
            self._connected = False
            raise PanelConnectionError(
                f"Não foi possível conectar a {self._host}:{self._port}: "
                f"tempo limite excedido ({self._timeout}s)"
            ) from err
        except OSError as err:
            self._connected = False
            detail = str(err) or err.__class__.__name__
            raise PanelConnectionError(
                f"Não foi possível conectar a {self._host}:{self._port}: {detail}"
            ) from err
