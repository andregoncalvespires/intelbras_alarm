"""Servidor "Receptor IP" — recebe eventos que a central empurra sozinha.

Diferente do resto desta integração (onde NÓS somos o cliente, conectando
na central e perguntando o status), aqui os papéis se invertem: a central
é configurada — **fora desta integração**, no teclado ou no app oficial,
tela "Configurar central" → conta/monitoramento IP — para se conectar
NELA MESMA no endereço/porta que definimos aqui. A partir daí, ela empurra
eventos sozinha, em tempo real, sem precisarmos ficar perguntando.

Protocolo documentado na seção 8 ("Comandos do Receptor IP") do documento
oficial *"Descrição de Comandos de Protocolo ISECnet Centrais de Alarmes
– Intelbras Receptor IP"*, válido para AMT2018E, AMT2018EG, AMT 1016 NET
e AMT 4010 SMART (os mesmos modelos já suportados pelo resto desta
integração, com a mesma estrutura de protocolo para todos — ao contrário
da leitura de EEPROM, aqui não há variação por modelo/firmware).

Reaproveita ``protocol.parse_frame()``/``protocol.checksum()`` — o
framing ``[Nº Bytes][Comando][Conteúdo][Checksum]`` e o algoritmo de
checksum (complemento do XOR de tudo, incluindo o byte de tamanho) são
exatamente os mesmos do restante do protocolo ISECNet, confirmado
batendo os exemplos do documento oficial byte a byte.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Callable

from .const import RECEPTOR_IP_EVENT_TABLE
from .protocol import ProtocolError, parse_frame

_LOGGER = logging.getLogger(__name__)

ACK_FRAME = bytes([0xFE])

CMD_CONNECT_INFO = 0x94  # a central informa conta/canal/MAC ao conectar
CMD_EVENT_NO_DATE = 0xB0  # evento sem data/hora embutida (16 bytes de conteúdo)
CMD_EVENT_WITH_DATE = 0xB4  # evento com data/hora embutida (28 bytes de conteúdo)
CMD_HEARTBEAT = 0xF7  # "sinal de vida" — 1 byte sozinho, sem framing, sem conteúdo

# A central se desconecta sozinha se não conseguir confirmação da central
# receptora dentro de um tempo (30s Ethernet / 60s GPRS, conforme o
# documento) — mas o documento não especifica quanto tempo NÓS devemos
# esperar pelo handshake inicial (comando 0x94) antes de desistir de uma
# conexão que nunca se identifica. Usamos um valor próprio, conservador.
HANDSHAKE_TIMEOUT = 15  # segundos
# Tempo sem receber nada (nem heartbeat) antes de considerarmos a conexão
# morta e fechá-la — bem acima do que se espera de intervalo entre
# heartbeats em uso normal, só para liberar recursos de conexões mortas.
IDLE_TIMEOUT = 180  # segundos


def _decode_digits(content: bytes, start: int, count: int) -> str:
    """Decodifica ``count`` bytes no esquema Contact-ID usado neste
    protocolo: um dígito decimal por byte, onde o dígito 0 é enviado como
    ``0x0A`` em vez de ``0x00`` (confirmado em três fontes independentes:
    o documento oficial, um projeto open-source de terceiros, e dois
    scripts de referência testados em hardware real pelo usuário desta
    integração).
    """
    digitos = []
    for i in range(count):
        b = content[start + i]
        digitos.append("0" if b == 0x0A else str(b))
    return "".join(digitos)


def parse_connect_info(content: bytes) -> dict:
    """Decodifica o conteúdo do comando 0x94 (identificação ao conectar)."""
    canal_byte = content[0] if content else 0
    canal = {0x45: "Ethernet", 0x47: "GPRS SIM1", 0x48: "GPRS SIM2"}.get(
        canal_byte, f"desconhecido (0x{canal_byte:02X})"
    )
    conta = content[1:3].hex().upper() if len(content) >= 3 else ""
    mac_sufixo = content[3:6].hex(":").upper() if len(content) >= 6 else ""
    return {"canal": canal, "conta": conta, "mac_sufixo": mac_sufixo}


_RECEPTOR_PARTITION_LETTERS = {0: "-", 1: "A", 2: "B", 3: "C", 4: "D"}


def parse_event(content: bytes, with_date: bool) -> dict:
    """Decodifica o conteúdo de um evento (comando 0xB0 ou 0xB4).

    Layout confirmado batendo o exemplo do documento oficial byte a byte:
    ``[CH/IP(1)][Conta(4)][M(1)][T(1)][Qualificador(1)][Código(3)]
    [Partição(2)][Zona/Usuário(3)]`` — 16 bytes no total (0xB0). O 0xB4
    acrescenta mais 12 bytes no final: data/hora do evento (6 bytes, um
    valor bruto por campo — dia/mês/ano/hora/min/seg, NÃO o esquema de
    dígito-por-byte usado no resto do frame) seguidos da data/hora atual
    da central (mesmo formato, não usada por esta integração).
    """
    if len(content) < 16:
        raise ProtocolError(f"Conteúdo de evento curto demais: {len(content)} bytes")

    conta = _decode_digits(content, 1, 4)
    qualificador = _decode_digits(content, 7, 1)
    codigo_evento = _decode_digits(content, 8, 3)
    particao_num = int(_decode_digits(content, 11, 2))
    zona_usuario = int(_decode_digits(content, 13, 3))

    codigo_completo = qualificador + codigo_evento
    descricao = RECEPTOR_IP_EVENT_TABLE.get(
        codigo_completo, f"Código desconhecido ({codigo_completo})"
    )

    resultado = {
        "conta": conta,
        "codigo": codigo_completo,
        "descricao": descricao,
        "particao": _RECEPTOR_PARTITION_LETTERS.get(particao_num, str(particao_num)),
        "zona_usuario": zona_usuario,
        "data_hora_evento": None,
    }

    if with_date and len(content) >= 22:
        dia, mes, ano, hora, minuto, segundo = content[16:22]
        try:
            resultado["data_hora_evento"] = datetime(2000 + ano, mes, dia, hora, minuto, segundo)
        except ValueError:
            pass  # valor bruto inválido — mantém None, não interrompe o processamento

    return resultado


class ReceptorIPServer:
    """Servidor TCP que fica escutando a central se conectar e empurrar eventos.

    Aceita conexões **só** do IP configurado como endereço da central (a
    mesma opção já usada para a conexão de cliente) — o protocolo em si
    não tem nenhuma autenticação própria (nem senha, nem token), então
    essa checagem de IP é a única proteção contra qualquer outra coisa na
    rede local se passar pela central.
    """

    def __init__(
        self,
        host: str,
        port: int,
        expected_panel_ip: str,
        on_event: Callable[[dict], Awaitable[None] | None],
        on_heartbeat: Callable[[], Awaitable[None] | None],
    ) -> None:
        self._host = host
        self._port = port
        self._expected_panel_ip = expected_panel_ip
        self._on_event = on_event
        self._on_heartbeat = on_heartbeat
        self._server: asyncio.base_events.Server | None = None

    async def async_start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self._host, self._port
        )
        _LOGGER.info(
            "Receptor IP: escutando em %s:%s (só aceita conexões de %s)",
            self._host,
            self._port,
            self._expected_panel_ip,
        )

    async def async_stop(self) -> None:
        if self._server is not None:
            self._server.close()
            # Mesma correção de PanelClient._close_locked() (ver comentário
            # lá) — timeout de proteção pra não travar o descarregamento
            # da integração indefinidamente se o fechamento não for
            # confirmado a tempo (aqui é menos crítico, já que é um
            # socket de escuta nosso, não uma conexão com a central, mas
            # aplicado por precaução/consistência).
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=3)
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Fechamento do servidor Receptor IP não confirmado em 3s "
                    "— seguindo em frente mesmo assim"
                )
            self._server = None
            _LOGGER.info("Receptor IP: servidor encerrado")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else None

        if peer_ip != self._expected_panel_ip:
            _LOGGER.warning(
                "Receptor IP: conexão recusada de %s (só aceita %s)",
                peer_ip,
                self._expected_panel_ip,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return

        _LOGGER.debug("Receptor IP: central conectada de %s", peer_ip)
        handshake_ok = False
        try:
            while True:
                timeout = HANDSHAKE_TIMEOUT if not handshake_ok else IDLE_TIMEOUT
                try:
                    header = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
                except asyncio.IncompleteReadError:
                    break  # conexão encerrada pela central
                except asyncio.TimeoutError:
                    _LOGGER.debug(
                        "Receptor IP: %s sem enviar nada por %ss, encerrando conexão",
                        peer_ip,
                        timeout,
                    )
                    break

                if header == bytes([CMD_HEARTBEAT]):
                    writer.write(ACK_FRAME)
                    await writer.drain()
                    await _maybe_await(self._on_heartbeat())
                    continue

                # Qualquer outra coisa é o byte de "Nº Bytes" de um frame
                # completo [Nº Bytes][Comando][Conteúdo][Checksum] — mesmo
                # framing usado no resto do protocolo ISECNet.
                num_bytes = header[0]
                try:
                    resto = await asyncio.wait_for(
                        reader.readexactly(num_bytes + 1), timeout=timeout
                    )
                except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                    _LOGGER.debug(
                        "Receptor IP: %s — frame incompleto, encerrando conexão", peer_ip
                    )
                    break

                raw = header + resto
                try:
                    parsed = parse_frame(raw)
                except ProtocolError as err:
                    _LOGGER.warning(
                        "Receptor IP: frame inválido de %s (%s): %s",
                        peer_ip,
                        err,
                        raw.hex(" ").upper(),
                    )
                    continue
                if not parsed.valid_checksum:
                    _LOGGER.warning(
                        "Receptor IP: checksum inválido de %s: %s",
                        peer_ip,
                        raw.hex(" ").upper(),
                    )
                    continue

                writer.write(ACK_FRAME)
                await writer.drain()

                if parsed.command == CMD_CONNECT_INFO:
                    info = parse_connect_info(parsed.content)
                    _LOGGER.info(
                        "Receptor IP: central identificada — conta=%s canal=%s",
                        info["conta"],
                        info["canal"],
                    )
                    handshake_ok = True
                elif parsed.command in (CMD_EVENT_NO_DATE, CMD_EVENT_WITH_DATE):
                    evento = parse_event(
                        parsed.content, with_date=(parsed.command == CMD_EVENT_WITH_DATE)
                    )
                    handshake_ok = True  # um evento também confirma que é a central de verdade
                    await _maybe_await(self._on_event(evento))
                else:
                    _LOGGER.debug(
                        "Receptor IP: comando 0x%02X de %s reconhecido (ACK enviado), "
                        "sem processamento específico: %s",
                        parsed.command,
                        peer_ip,
                        parsed.content.hex(" ").upper(),
                    )
        except (ConnectionResetError, OSError) as err:
            _LOGGER.debug("Receptor IP: conexão com %s encerrada (%s)", peer_ip, err)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            _LOGGER.debug("Receptor IP: central desconectada (%s)", peer_ip)


async def _maybe_await(value):
    """Permite que on_event/on_heartbeat sejam funções normais OU corrotinas."""
    if value is not None and hasattr(value, "__await__"):
        await value
