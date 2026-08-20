"""Implementação do protocolo próprio (autenticado) da central AMT 8000.

EXPERIMENTAL / EM DESENVOLVIMENTO — ver README_DETALHADO.md, seção "AMT 8000
(experimental)". Diferente do ISECMobile/ISECNet usado pelas famílias 2018 e
4010 (``protocol.py``), a AMT 8000 usa um framing próprio, com autenticação
de sessão antes de qualquer comando:

    [0x00 0x00] [srcId0 srcId1] [0x00] [LEN] [opcode_hi opcode_lo] [conteúdo...] [checksum]

``LEN`` conta os bytes de ``opcode_hi`` até o fim do conteúdo (inclusive),
sem contar o checksum. ``srcId`` é um par fixo (``0x00 0x01``) observado em
toda transação — provável identificador de versão do protocolo.

Todos os opcodes, o algoritmo de checksum e os offsets do blob de status e
do registro de evento foram extraídos por engenharia reversa do app oficial
AMT Remoto (androguard, classes ``ProtocoloServidorAmt8000``, ``Amt8000`` e
``Translate8000Events``, v3.4.2.2) e cruzados com uma implementação de
terceiros testada em campo pelo usuário (fluxo Node-RED, firmware 2.1.5).

Checksum: XOR de todos os bytes do frame (do primeiro ``0x00`` até o fim do
conteúdo, exclusive o próprio checksum), complementado (``^ 0xFF``) —
confirmado byte a byte contra o método ``checkSum()`` do app oficial.

⚠️ NENHUM offset ou opcode aqui foi validado por captura de tráfego própria
contra hardware real ainda — ver README_DETALHADO.md para o que falta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import (
    AMT8000_CMD_ARM_DISARM,
    AMT8000_CMD_AUTH,
    AMT8000_CMD_BYPASS,
    AMT8000_CMD_DISCONNECT,
    AMT8000_CMD_EVENT_BUFFER_INDEX,
    AMT8000_CMD_PANIC,
    AMT8000_CMD_PGM,
    AMT8000_CMD_PHOTO_REQUEST,
    AMT8000_CMD_READ_EVENTS,
    AMT8000_CMD_STATUS,
    AMT8000_CMD_SYNC_NOME_CENTRAL,
    AMT8000_CMD_SYNC_PARTICAO,
    AMT8000_CMD_SYNC_PGM,
    AMT8000_CMD_SYNC_SIRENE,
    AMT8000_CMD_SYNC_TECLADO,
    AMT8000_CMD_SYNC_USUARIO,
    AMT8000_CMD_SYNC_ZONA,
    AMT8000_SRC_ID,
    AMT_8000_MODEL_NAME,
    FAMILY_8000,
    MODEL_AMT_8000,
)
from .protocol import PanelStatus

_SYNC_OPCODE_BY_KIND = {
    "central": AMT8000_CMD_SYNC_NOME_CENTRAL,
    "usuario": AMT8000_CMD_SYNC_USUARIO,
    "zona": AMT8000_CMD_SYNC_ZONA,
    "particao": AMT8000_CMD_SYNC_PARTICAO,
    "pgm": AMT8000_CMD_SYNC_PGM,
    "teclado": AMT8000_CMD_SYNC_TECLADO,
    "sirene": AMT8000_CMD_SYNC_SIRENE,
}


class ProtocolAmt8000Error(Exception):
    """Erro genérico de protocolo (frame malformado, checksum inválido etc.)."""


class Amt8000AuthError(Exception):
    """A central rejeitou a autenticação (senha incorreta ou sessão expirada)."""


def checksum(data: bytes) -> int:
    """XOR de todos os bytes, complementado (``^ 0xFF``) — ver docstring do módulo."""
    x = 0
    for b in data:
        x ^= b
    return (x ^ 0xFF) & 0xFF


def _build_frame(opcode: tuple[int, int], content: bytes = b"") -> bytes:
    """Monta um frame completo pronto para envio (ver docstring do módulo)."""
    src0, src1 = AMT8000_SRC_ID
    op_hi, op_lo = opcode
    body = bytes([op_hi, op_lo]) + content
    length = len(body)
    if length > 255:
        raise ValueError("Conteúdo do comando AMT 8000 excede o tamanho máximo do frame")
    frame = bytes([0x00, 0x00, src0, src1, 0x00, length]) + body
    return frame + bytes([checksum(frame)])


@dataclass
class ParsedFrameAmt8000:
    """Resultado da leitura de um frame de resposta da central."""

    opcode: tuple[int, int]
    content: bytes
    valid_checksum: bool
    raw: bytes = field(repr=False)


def parse_frame(raw: bytes) -> ParsedFrameAmt8000:
    """Interpreta um frame bruto recebido da central.

    Layout de resposta assumido igual ao de requisição (mesmo cabeçalho de
    6 bytes antes do opcode) — ainda não confirmado por captura própria.
    """
    if len(raw) < 8:
        raise ProtocolAmt8000Error(f"Frame AMT 8000 muito curto para ser válido: {raw.hex()}")
    length = raw[5]
    expected_len = 6 + length + 1  # cabeçalho + (opcode+conteúdo) + checksum
    if len(raw) < expected_len:
        raise ProtocolAmt8000Error(
            f"Frame AMT 8000 incompleto: esperado {expected_len} bytes, recebido {len(raw)}"
        )
    raw = raw[:expected_len]
    opcode = (raw[6], raw[7])
    content = raw[8 : 6 + length]
    received_checksum = raw[-1]
    calculated = checksum(raw[:-1])
    return ParsedFrameAmt8000(
        opcode=opcode,
        content=content,
        valid_checksum=(calculated == received_checksum),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Construtores de comando
# ---------------------------------------------------------------------------
def cmd_auth(password: str) -> bytes:
    """Monta o comando de autenticação (``0xF0F0``).

    Conteúdo = ``[0x03]`` (sub-comando) + 6 dígitos da senha (nibbles hex;
    dígito ``0`` vira ``0x0A`` — mesma convenção já usada no Receptor IP
    e no protocolo legado ``0xE7`` (Contact-ID), **não** a do ISECMobile
    principal (``protocol.py``), que embute a senha em ASCII puro — são
    protocolos diferentes, cada um com sua própria codificação;
    preenchido com ``0x01`` até completar 6 posições) + ``[0x01, 0x00]``
    (marcador final) — layout confirmado byte a byte contra
    ``Amt8000.autenticaConexaoRemota`` do app oficial (checksum de
    referência ``0xF9`` para a senha de teste ``786531``, validado nesta
    implementação).
    """
    if not password.isdigit() or not (1 <= len(password) <= 6):
        raise ValueError("A senha da AMT 8000 deve ter de 1 a 6 dígitos numéricos")
    digits = [10 if d == "0" else int(d) for d in password]
    digits += [0x01] * (6 - len(digits))  # preenchimento — ver Amt8000.autenticaConexaoRemota
    content = bytes([0x03]) + bytes(digits) + bytes([0x01, 0x00])
    return _build_frame(AMT8000_CMD_AUTH, content)


def cmd_status() -> bytes:
    return _build_frame(AMT8000_CMD_STATUS)


def cmd_arm_disarm(partition: int, mode: int) -> bytes:
    """Monta o comando de arme/desarme/stay (``0x401E``) para uma partição (1-16).

    ``partition=0`` é usado pelo fluxo de referência para "central inteira"
    — reproduzido aqui, ainda não confirmado por captura própria.
    """
    return _build_frame(AMT8000_CMD_ARM_DISARM, bytes([partition & 0xFF, mode & 0xFF]))


def cmd_bypass(zone: int, enable: bool) -> bytes:
    """Monta o comando de bypass individual (``0x401F``) — zona + flag on/off.

    Diferente do protocolo ISECMobile (comando absoluto sobre as 64
    zonas), a AMT 8000 anula/reativa **uma zona por vez**, confirmado no
    código-fonte do app oficial (``Amt8000.comandBypassAmt8000``).
    """
    return _build_frame(AMT8000_CMD_BYPASS, bytes([zone & 0xFF, 1 if enable else 0]))


def cmd_pgm(pgm: int, turn_on: bool) -> bytes:
    return _build_frame(AMT8000_CMD_PGM, bytes([pgm & 0xFF, 1 if turn_on else 0]))


def cmd_panic(kind: int) -> bytes:
    return _build_frame(AMT8000_CMD_PANIC, bytes([kind & 0xFF]))


def cmd_event_buffer_index() -> bytes:
    """Solicita o índice atual do buffer circular de eventos (``0x3003``)."""
    return _build_frame(AMT8000_CMD_EVENT_BUFFER_INDEX, bytes([0x00]))


def cmd_read_events(indices: list[int]) -> bytes:
    """Lê eventos do buffer circular pelos índices informados (``0x3900``).

    Cada índice é enviado como par de bytes alto/baixo (buffer de até
    ``AMT8000_EVENT_BUFFER_SIZE`` posições) — até
    ``AMT8000_EVENT_READ_BATCH`` índices por chamada, conforme o app
    oficial.
    """
    content = bytearray()
    for idx in indices:
        content.append((idx >> 8) & 0xFF)
        content.append(idx & 0xFF)
    return _build_frame(AMT8000_CMD_READ_EVENTS, bytes(content))


def cmd_photo_request(photo_index: bytes) -> bytes:
    """Monta o comando de solicitação de fragmento de foto (``0x0BB0``).

    ``photo_index`` são os bytes de índice devolvidos no evento com
    ``foto=True`` (ver ``parse_event_record``) — formato exato do
    conteúdo ainda não confirmado por captura própria; ver LEIA_ME de
    fotos (documentação anexada ao projeto) para o fluxo geral
    (autenticar → 0x0BB0 → ler fragmentos → 0xF0F1).
    """
    return _build_frame(AMT8000_CMD_PHOTO_REQUEST, photo_index)


def cmd_disconnect() -> bytes:
    return _build_frame(AMT8000_CMD_DISCONNECT)


def cmd_sync_names(kind: str, indices: list[int]) -> bytes:
    """Monta o comando de leitura de nomes (``COMANDO_SYNC_*``).

    ``kind`` é uma das chaves de ``_SYNC_OPCODE_BY_KIND`` ("zona",
    "usuario", "particao", "pgm", "teclado", "sirene", "central").
    ``indices`` é a lista de posições a consultar (1-based) — a
    implementação atual do coordinator sempre passa uma lista de 1
    elemento (ver decisão de arquitetura: leitura 1 por vez nesta
    primeira versão, não em lote de 10 como o app oficial).
    """
    if kind not in _SYNC_OPCODE_BY_KIND:
        raise ValueError(f"Tipo de sincronismo de nome desconhecido: {kind!r}")
    return _build_frame(_SYNC_OPCODE_BY_KIND[kind], bytes(idx & 0xFF for idx in indices))


# ---------------------------------------------------------------------------
# Parsing do status completo (0x0B4A)
#
# Offsets relativos ao início do CONTEÚDO da resposta (``content[0]`` é o
# byte 0 do blob de status, delta "+7" do fluxo de referência já removido
# aqui — lá, o delta compensava o cabeçalho bruto do socket, que
# ``parse_frame`` acima já retira). Bits nomeados conforme o fluxo de
# referência (nomes curtos/em português no original; mantidos como
# comentário ao lado de cada campo por rastreabilidade).
# ---------------------------------------------------------------------------
def _bits(content: bytes, base_offset: int, n_bytes: int, count: int) -> dict[int, bool]:
    """Extrai ``count`` bits (1 por zona/partição) a partir de ``n_bytes``
    bytes começando em ``base_offset``, LSB primeiro — mesma convenção do
    fluxo de referência."""
    result: dict[int, bool] = {}
    n = 0
    for i in range(n_bytes):
        if base_offset + i >= len(content):
            break
        byte_val = content[base_offset + i]
        for j in range(8):
            n += 1
            if n > count:
                return result
            result[n] = bool((byte_val >> j) & 1)
    return result


def _bcd(value: int) -> int:
    return ((value & 0xF0) >> 4) * 10 + (value & 0x0F)


def parse_status(content: bytes) -> PanelStatus:
    """Interpreta o blob de status completo (~152 bytes) devolvido por ``0x0B4A``."""
    def b(offset: int) -> int:
        return content[offset] if offset < len(content) else 0

    zones_open = _bits(content, 39, 8, 64)  # zone_
    zones_violated = _bits(content, 47, 8, 64)  # violated_
    zones_bypassed = _bits(content, 55, 8, 64)  # anulated_
    zones_comm_failure = _bits(content, 74, 8, 64)  # comunication_failure
    zones_tamper = _bits(content, 90, 8, 64)  # tamper_
    zones_low_battery = _bits(content, 106, 8, 64)  # lowbattery_

    firmware = f"{b(2)}.{b(3)}.{b(4)}"

    status21 = b(21)
    # activated: NOT bit5 de status21 (convenção invertida, confirmada no
    # fluxo de referência: bit5=0 -> central ativada)
    activated = not bool((status21 >> 5) & 1)

    # Partições: 1 BYTE por partição (não 1 bit), offset base 23, bit0 de
    # cada byte, invertido (0 = armada) — 17 posições no fluxo de
    # referência (0..16); mapeado aqui como partição "0" = central/geral e
    # 1..16 = partições individuais.
    partitions_armed: dict[str, bool] = {}
    for i in range(17):
        offset = 23 + i - 1
        if offset < 0 or offset >= len(content):
            continue
        armed = not bool((content[offset] >> 0) & 1)
        partitions_armed[str(i)] = armed

    status72 = b(72)
    ac_power_fault = bool((status72 >> 0) & 1)  # ~acpower no fluxo de referência -> aqui já é "falta"
    battery_low = bool((status72 >> 1) & 1)
    battery_short = bool((status72 >> 3) & 1)
    event_communication_failure = bool((status72 >> 5) & 1)  # fce

    aux_overload = bool((b(37) >> 4) & 1)  # s_aux

    battery_raw = b(135)
    battery_level = {0x04: 100, 0x03: 66, 0x02: 33, 0x01: 0}.get(battery_raw, 0)
    battery_missing_or_reversed = battery_raw == 0x01

    siren_on = bool((b(47) >> 2) & 1)  # ss
    pgm_state = {
        1: bool((b(47) >> 6) & 1),
        2: bool((b(47) >> 5) & 1),
        3: bool((b(47) >> 4) & 1),
    }

    siren_short_circuit = bool((b(44) >> 1) & 1)  # sc
    siren_wire_cut = bool((b(44) >> 0) & 1)  # scf

    # Data/hora da central — BCD, offsets 65 (dia) a 70 (segundo). Ao
    # contrário do fluxo de referência (que zera/ignora o segundo só para
    # evitar ruído de diff num comparador de buffer bruto — ver histórico
    # do projeto), aqui lemos com precisão total: o Home Assistant já
    # trata atualização de estado por valor computado, não por buffer.
    panel_datetime_str: str | None = None
    try:
        year = 2000 + _bcd(b(67))
        month = _bcd(b(66))
        day = _bcd(b(65))
        hour = _bcd(b(68))
        minute = _bcd(b(69))
        second = _bcd(b(70))
        panel_datetime_str = datetime(year, month, day, hour, minute, second).strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except ValueError:
        panel_datetime_str = None

    zone_triggered = any(zones_violated.values())

    return PanelStatus(
        model_key=MODEL_AMT_8000,
        model_name=AMT_8000_MODEL_NAME,
        family=FAMILY_8000,
        firmware=firmware,
        zones_open=zones_open,
        zones_violated=zones_violated,
        zones_bypassed=zones_bypassed,
        zones_low_battery=zones_low_battery,
        partition_mode_enabled=True,
        partitions_armed=partitions_armed,
        activated=activated,
        zone_triggered=zone_triggered,
        trigger_bit_latched=zone_triggered,
        zone_open_flag=any(zones_open.values()),
        status_byte_raw=status21,
        status_byte_name="status21",
        partition_status_bytes={},
        partition_bit_map={},
        siren_on=siren_on,
        problem=ac_power_fault or battery_low or battery_short or event_communication_failure,
        ac_power_fault=ac_power_fault,
        battery_low=battery_low,
        battery_missing_or_reversed=battery_missing_or_reversed,
        battery_short=battery_short,
        aux_overload=aux_overload,
        battery_level=battery_level,
        pgm_state=pgm_state,
        panel_datetime_str=panel_datetime_str,
        siren_wire_cut=siren_wire_cut,
        siren_short_circuit=siren_short_circuit,
        phone_line_cut=False,  # não aplicável (rede é sempre Ethernet nesta central)
        event_communication_failure=event_communication_failure,
        keypad_problem={},
        receiver_problem={},
        keypad_tamper={},
        zones_tamper=zones_tamper,
        zones_short_circuit={},
        pgm_expander_problem={},
        zone_expander_problem={},
        zones_comm_failure=zones_comm_failure,
    )


# ---------------------------------------------------------------------------
# Parsing de registro de evento (0x3900) — offsets confirmados em
# Translate8000Events.class (app oficial). ``fields`` é a lista de bytes
# de UM registro de evento, na ordem devolvida pela central.
# ---------------------------------------------------------------------------
_EVENT_CODE_DESCRIPTIONS: dict[str, str] = {
    # Tabela deliberadamente vazia por ora — a AMT 8000 usa o mesmo
    # dicionário de códigos Contact-ID já usado pelo Receptor IP
    # (const.RECEPTOR_IP_EVENT_TABLE); o coordinator faz esse cruzamento
    # ao montar o dicionário final do evento, para não duplicar a tabela.
}


def parse_event_record(fields: list[int]) -> dict | None:
    """Interpreta um registro de evento (ver offsets no módulo).

    ``fields`` deve ter ao menos 15 posições (índices 0-14 usados). Datas
    fora do intervalo válido (registro vazio/não inicializado do buffer
    circular) devolvem ``None``, mesmo padrão de ``protocol.parse_event_record``.
    """
    if len(fields) < 15:
        return None

    def hx(idx: int) -> int:
        return fields[idx] if idx < len(fields) else 0

    try:
        year = 2000 + hx(2)
        month = hx(3)
        day = hx(4)
        hour = hx(5)
        minute = hx(6)
        second = hx(7)
        data_hora = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None

    evento_hi = (hx(8) >> 4) & 0x0F
    evento_lo = hx(8) & 0x0F
    codigo_raw = f"{evento_hi:X}{evento_lo:X}{hx(9):02X}"

    zona_usuario = ((hx(11) & 0x0F) << 8) | hx(12)
    particao = hx(13)
    tem_foto = hx(14) > 0

    return {
        "data_hora": data_hora,
        "codigo_raw": codigo_raw,
        "codigo_app": None,  # preenchido pelo coordinator via RECEPTOR_IP_EVENT_TABLE
        "zona_usuario": zona_usuario,
        "particao": particao,
        "descricao": "",  # idem
        "foto": tem_foto,
    }
