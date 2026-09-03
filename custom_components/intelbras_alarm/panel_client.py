"""Cliente TCP assíncrono e persistente para a central de alarme Intelbras.

A conexão é aberta uma única vez e mantida aberta; só é refeita se cair
(erro de socket, timeout ou reset pela central). Todas as requisições são
serializadas por um lock, pois o protocolo é estritamente requisição/resposta
(a central nunca envia nada sem antes receber um comando do "mestre").
"""
from __future__ import annotations

import asyncio
import logging

from .const import DEFAULT_REQUEST_TIMEOUT
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
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
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
            # CORREÇÃO (bug real, confirmado em produção): antes,
            # `wait_closed()` não tinha nenhum timeout de proteção. A
            # central é um dispositivo embarcado com pilha TCP simples —
            # se ela não confirmar o fechamento da conexão de forma limpa
            # (não manda o FIN/ACK esperado, por exemplo), essa chamada
            # podia travar **indefinidamente**, sem nunca lançar exceção
            # nem retornar. Como isso acontece dentro de
            # `async_unload_entry()` (recarregar a integração, ou
            # reconfigurar via opções — que dispara um recarregamento
            # automático), uma trava aqui impedia o descarregamento de
            # terminar, deixando as entidades indisponíveis até um
            # reinício completo do Home Assistant (só isso mata a tarefa
            # travada à força, no nível do processo). Confirmado pelo
            # usuário: a correção resolveu os dois cenários relatados
            # (recarregar a integração; reconfigurar pra adicionar a
            # senha de leitura de mensagens).
            #
            # Corrigido dando um prazo curto pra esperar o fechamento
            # "limpo" — se não vier a tempo, desiste de esperar e segue
            # em frente mesmo assim (o objeto writer/reader já está sendo
            # descartado de qualquer jeito; uma nova conexão será aberta
            # do zero na próxima vez que for necessário).
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=3)
            except OSError:
                pass
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Fechamento da conexão com a central não confirmado em 3s "
                    "(central pode não responder ao fechamento de forma limpa) "
                    "— seguindo em frente mesmo assim, sem travar o "
                    "recarregamento da integração"
                )
        self._reader = None
        self._writer = None

    def transaction(self) -> asyncio.Lock:
        """Context manager que mantém o lock adquirido por toda a duração
        de um bloco ``async with``, para sequências de comandos que
        precisam ser tratadas como **uma transação atômica** — ex.:
        autenticação seguida de consulta em protocolos com sessão
        (``0xE7``, usado tanto na leitura de tensão quanto na leitura
        legada de nomes/eventos).

        BUG REAL corrigido (achado via análise cruzada de log + revisão
        de arquitetura, com ajuda de outra IA consultada pelo usuário):
        antes desta correção, cada etapa de uma sequência assim (ex.:
        autenticar, esperar, consultar) chamava ``send_command()``
        normalmente — que adquire e libera o lock a cada chamada
        individual. Isso deixava uma janela real (o ``asyncio.sleep()``
        entre as etapas) em que o polling rápido de status (a cada
        0,25s) podia se intercalar NO MEIO da troca autenticada,
        possivelmente confundindo o estado de sessão da central e
        causando lentidão/timeout nas respostas seguintes — bate com o
        padrão observado em produção: timeouts na consulta de status
        aconteciam sistematicamente no mesmo instante exato de cada
        ciclo de 5 minutos da consulta de tensão, não distribuídos
        aleatoriamente.

        Uso:
            async with client.transaction():
                r1 = await client.send_command_in_transaction(frame1, context="...")
                await asyncio.sleep(...)
                r2 = await client.send_command_in_transaction(frame2, context="...")

        Devolve o próprio ``asyncio.Lock`` — ele já é usável diretamente
        como context manager assíncrono; não precisa de um wrapper
        próprio.
        """
        return self._lock

    async def send_command(self, frame: bytes, context: str | None = None) -> ParsedFrame:
        """Envia um frame já pronto e aguarda a resposta correspondente.

        Reabre a conexão automaticamente se ela tiver caído; nunca fecha e
        reabre a cada requisição enquanto a conexão estiver saudável.

        ``context`` é só um rótulo textual opcional (ex.: "Ativar Partição
        A", "consulta de status") usado para enriquecer as mensagens de
        erro e os logs — não afeta o comportamento do envio em si.

        Para sequências de múltiplos comandos que precisam ser tratadas
        como uma transação atômica (não podem ser interrompidas por
        outro comando no meio), ver ``transaction()`` e
        ``send_command_in_transaction()`` em vez desta função.
        """
        if not self._enabled:
            raise PanelConnectionError("Comunicação com a central está desativada")
        async with self._lock:
            return await self._send_command_locked(frame, context)

    async def send_command_in_transaction(
        self, frame: bytes, context: str | None = None
    ) -> ParsedFrame:
        """Igual a ``send_command()``, mas **não adquire o lock sozinho**
        — só deve ser chamado de dentro de um bloco
        ``async with client.transaction():``, que já garante que o lock
        está mantido para toda a sequência. Chamar isso fora desse
        contexto quebra a serialização (dois comandos concorrentes
        poderiam se misturar no mesmo socket) — ver ``transaction()``
        para o motivo desta função existir.
        """
        if not self._enabled:
            raise PanelConnectionError("Comunicação com a central está desativada")
        return await self._send_command_locked(frame, context)

    async def _send_command_locked(self, frame: bytes, context: str | None = None) -> ParsedFrame:
        """Lógica real de envio — assume que o lock já está adquirido
        por quem chamou (``send_command()`` ou
        ``send_command_in_transaction()``, nunca diretamente)."""
        label = f" [{context}]" if context else ""

        if not self._connected:
            await self._connect_locked()

        assert self._writer is not None
        assert self._reader is not None
        try:
            # Log só AQUI (depois de conseguir a vez na fila do lock),
            # de propósito — reflete o momento em que o comando
            # realmente saiu pela conexão, não o momento em que quem
            # chamou send_command() decidiu mandar. Se o log fosse
            # colocado antes do "async with self._lock", uma requisição
            # que precisasse esperar (ex.: uma consulta de status já em
            # andamento) apareceria no log como enviada muito antes do
            # que aconteceu de verdade — gerando sequências
            # aparentemente fora de ordem (relatado pelo usuário).
            _LOGGER.debug("enviando comando%s: frame=%s", label, frame.hex(" ").upper())
            self._writer.write(frame)
            await self._writer.drain()
            # O primeiro byte do frame de resposta é o "Nº Bytes"; a partir
            # dele sabemos exatamente quantos bytes ainda faltam ler
            # (comando + conteúdo + checksum), evitando misturar respostas.
            # A leitura é feita em duas etapas (cabeçalho, depois o
            # resto) de propósito: se o timeout estourar na segunda
            # etapa, pelo menos sabemos quantos bytes a central chegou
            # a PROMETER (o cabeçalho já foi lido) — informação melhor
            # que nada para o log, mesmo sem saber quantos bytes do
            # "resto" chegaram de fato (isso exigiria um loop de
            # leitura manual, que não temos hoje).
            try:
                header = await asyncio.wait_for(
                    self._reader.readexactly(1), timeout=self._timeout
                )
            except asyncio.TimeoutError as err:
                await self._close_locked()
                raise PanelConnectionError(
                    f"Falha de comunicação com a central{label}: tempo limite "
                    f"excedido ({self._timeout}s) — nenhum byte de resposta "
                    f"chegou (nem o cabeçalho)"
                ) from err

            num_bytes = header[0]
            try:
                remainder = await asyncio.wait_for(
                    self._reader.readexactly(num_bytes + 1), timeout=self._timeout
                )
            except asyncio.TimeoutError as err:
                await self._close_locked()
                raise PanelConnectionError(
                    f"Falha de comunicação com a central{label}: tempo limite "
                    f"excedido ({self._timeout}s) — central prometeu "
                    f"{num_bytes + 1} bytes após o cabeçalho, mas não terminou "
                    f"de enviar a tempo"
                ) from err
            raw = header + remainder
        except asyncio.IncompleteReadError as err:
            await self._close_locked()
            raise PanelConnectionError(
                f"Falha de comunicação com a central{label}: conexão encerrada "
                f"antes da resposta completa (esperado {err.expected}, recebido "
                f"{len(err.partial)} bytes: {err.partial.hex(' ').upper()})"
            ) from err
        except OSError as err:
            await self._close_locked()
            detail = str(err) or err.__class__.__name__
            raise PanelConnectionError(
                f"Falha de comunicação com a central{label}: {detail}"
            ) from err

        try:
            return parse_frame(raw)
        except ProtocolError as err:
            raise PanelConnectionError(f"{err}{label}") from err

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
