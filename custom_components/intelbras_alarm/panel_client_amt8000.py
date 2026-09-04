"""Cliente TCP assíncrono e persistente para a central AMT 8000.

EXPERIMENTAL / EM DESENVOLVIMENTO — ver protocol_amt8000.py e
README_DETALHADO.md, seção "AMT 8000 (experimental)".

Espelha a estrutura de ``panel_client.py`` (conexão aberta uma vez e
mantida; comandos serializados por um lock), mas com duas diferenças
importantes:

1. Framing diferente na leitura da resposta: o "Nº Bytes" do ISECMobile
   fica na posição 0; aqui, o byte de tamanho (``LEN``) fica na posição 5,
   e o cabeçalho antes dele é fixo (6 bytes) — ver ``protocol_amt8000.py``.
2. A conexão exige autenticação de sessão (comando ``0xF0F0``) uma única
   vez logo após conectar — refeita automaticamente sempre que a conexão
   precisar ser reaberta (queda, timeout etc.), de forma transparente para
   quem chama ``send_command``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .const import DEFAULT_REQUEST_TIMEOUT
from .protocol_amt8000 import (
    Amt8000AuthError,
    ParsedFrameAmt8000,
    ProtocolAmt8000Error,
    cmd_auth,
    parse_frame,
)

_LOGGER = logging.getLogger(__name__)

# Código de resposta observado no fluxo de referência para falha de
# autenticação (comando 0xF0FD, conteúdo iniciando em 0x1F) — ver
# Autenticação() no fluxo Node-RED original. Ainda não confirmado com
# captura própria contra hardware real.
_AUTH_FAIL_OPCODE = (0xF0, 0xFD)


class PanelConnectionErrorAmt8000(Exception):
    """Falha ao conectar, autenticar ou comunicar com a central AMT 8000."""


class PanelClientAmt8000:
    """Mantém uma conexão TCP persistente e autenticada com a central AMT 8000."""

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        enabled: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._authenticated = False
        self._enabled = enabled

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            await self.disconnect()

    async def connect(self) -> None:
        if self._connected or not self._enabled:
            return
        async with self._lock:
            if self._connected:
                return
            await self._connect_and_authenticate_locked()

    async def disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        self._connected = False
        self._authenticated = False
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = None
        self._writer = None

    async def _connect_and_authenticate_locked(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
            self._connected = True
            _LOGGER.debug("AMT 8000: conectado em %s:%s", self._host, self._port)
        except (OSError, asyncio.TimeoutError) as err:
            self._connected = False
            raise PanelConnectionErrorAmt8000(
                f"Não foi possível conectar a {self._host}:{self._port}: {err}"
            ) from err

        auth_response = await self._raw_send_locked(cmd_auth(self._password), context="autenticação")
        if auth_response.opcode == _AUTH_FAIL_OPCODE:
            await self._close_locked()
            raise Amt8000AuthError("Senha rejeitada pela central AMT 8000")
        self._authenticated = True
        _LOGGER.debug("AMT 8000: sessão autenticada")

    async def send_command(
        self,
        frame: bytes,
        context: str | None = None,
        on_sent: Callable[[], None] | None = None,
    ) -> ParsedFrameAmt8000:
        """Envia um frame já pronto (ver ``protocol_amt8000.py``) e aguarda a resposta.

        Reconecta e reautentica automaticamente se a conexão tiver caído —
        nunca fecha e reabre a cada requisição enquanto a sessão estiver
        saudável (mesma filosofia de ``panel_client.PanelClient``).
        """
        if not self._enabled:
            raise PanelConnectionErrorAmt8000("Comunicação com a central está desativada")

        async with self._lock:
            if not self._connected or not self._authenticated:
                await self._connect_and_authenticate_locked()
            return await self._raw_send_locked(
                frame, context=context, on_sent=on_sent
            )

    async def _raw_send_locked(
        self,
        frame: bytes,
        context: str | None = None,
        on_sent: Callable[[], None] | None = None,
    ) -> ParsedFrameAmt8000:
        """Envia ``frame`` e lê a resposta — assume o lock já adquirido."""
        label = f" [{context}]" if context else ""
        assert self._writer is not None
        assert self._reader is not None
        try:
            _LOGGER.debug("AMT 8000: enviando%s: frame=%s", label, frame.hex(" ").upper())
            if on_sent is not None:
                on_sent()
            self._writer.write(frame)
            await self._writer.drain()

            # Cabeçalho fixo de 6 bytes (ver protocol_amt8000.parse_frame);
            # o 6º byte (índice 5) é o LEN, a partir do qual sabemos
            # exatamente quanto falta ler (opcode + conteúdo + checksum).
            try:
                header = await asyncio.wait_for(
                    self._reader.readexactly(6), timeout=self._timeout
                )
            except asyncio.TimeoutError as err:
                await self._close_locked()
                raise PanelConnectionErrorAmt8000(
                    f"Falha de comunicação com a AMT 8000{label}: tempo limite "
                    f"excedido ({self._timeout}s) — nenhum byte de resposta chegou"
                ) from err

            length = header[5]
            try:
                remainder = await asyncio.wait_for(
                    self._reader.readexactly(length + 1), timeout=self._timeout
                )
            except asyncio.TimeoutError as err:
                await self._close_locked()
                raise PanelConnectionErrorAmt8000(
                    f"Falha de comunicação com a AMT 8000{label}: tempo limite "
                    f"excedido ({self._timeout}s) — central prometeu {length + 1} "
                    f"bytes após o cabeçalho, mas não terminou de enviar a tempo"
                ) from err
            raw = header + remainder
        except asyncio.IncompleteReadError as err:
            await self._close_locked()
            raise PanelConnectionErrorAmt8000(
                f"Falha de comunicação com a AMT 8000{label}: conexão encerrada antes "
                f"da resposta completa (esperado {err.expected}, recebido "
                f"{len(err.partial)} bytes: {err.partial.hex(' ').upper()})"
            ) from err
        except OSError as err:
            await self._close_locked()
            detail = str(err) or err.__class__.__name__
            raise PanelConnectionErrorAmt8000(
                f"Falha de comunicação com a AMT 8000{label}: {detail}"
            ) from err

        try:
            return parse_frame(raw)
        except ProtocolAmt8000Error as err:
            raise PanelConnectionErrorAmt8000(f"{err}{label}") from err
