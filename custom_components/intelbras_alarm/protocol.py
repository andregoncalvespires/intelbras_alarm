"""Implementação do protocolo ISECNet / ISECMobile da Intelbras.

Baseado no documento oficial "Descrição de Comandos de Protocolo ISECnet
Centrais de Alarmes – Intelbras Receptor IP" (AMT2018 E/EG e AMT4010 Smart,
Revisão 15) e validado com capturas reais de tráfego.

Estrutura do frame (ver seção 6 do documento):

    [Nº Bytes] [0xE9] [0x21] [Senha ASCII 4..6] [Comando 1..2] [Conteúdo 0..52] [0x21] [Checksum]
               \\_______________________________ ISECMobile _______________________________/
    \\__________________________ ISECNet ("Conteúdo" do comando 0xE9) __________________________/

``Nº Bytes`` conta os bytes de 0xE9 até o fim do frame ISECMobile (inclusive),
sem contar a si próprio nem o checksum.

O checksum não está documentado explicitamente no PDF, mas foi confirmado por
engenharia reversa (bate com 13 dos 14 exemplos do documento; o único que não
bate tem um erro de digitação conhecido, ver revisão 06 do próprio documento
que já corrigiu "checksums dos exemplos" antes) e por implementações de
terceiros de código aberto:

    checksum = NOT(XOR de todos os bytes do frame, do Nº Bytes até o Conteúdo)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .const import ACK_OK, NACK_MESSAGES

FRAME_DELIMITER = 0x21
ISEC_COMMAND = 0xE9


class ProtocolError(Exception):
    """Erro genérico de protocolo (frame malformado, checksum inválido etc.)."""


class NackError(Exception):
    """A central respondeu com NACK a um comando."""

    def __init__(self, code: int) -> None:
        self.code = code
        self.message = NACK_MESSAGES.get(code, f"NACK desconhecido (0x{code:02X})")
        super().__init__(self.message)


def checksum(data: bytes) -> int:
    """Calcula o checksum ISECNet: NOT(XOR de todos os bytes)."""
    x = 0
    for b in data:
        x ^= b
    return (~x) & 0xFF


def parse_hex_bytes(text: str) -> bytes:
    """Converte uma string de bytes em hex livre em ``bytes``.

    Usado pelo serviço de diagnóstico ``send_raw_command`` — aceita
    espaços, vírgulas ou ponto-e-vírgula como separador, e prefixo ``0x``
    opcional por byte, pra reduzir erro de digitação de quem está testando
    comandos manualmente. Ex.: ``"08 E9 21"``, ``"0x08,0xE9;0x21"`` e
    ``"08E921"`` (sem separador nenhum) todos funcionam.
    """
    cleaned = text.strip()
    for sep in (",", ";"):
        cleaned = cleaned.replace(sep, " ")
    tokens = [t for t in cleaned.split() if t]
    # Sem separador nenhum (ex.: "08E921") — sobra um único "token" colado;
    # quebra em pares de 2 caracteres nesse caso específico.
    if len(tokens) == 1 and len(tokens[0]) > 2 and not tokens[0].lower().startswith("0x"):
        only = tokens[0]
        if len(only) % 2 != 0:
            raise ValueError(f"Quantidade ímpar de dígitos hex: {text!r}")
        tokens = [only[i : i + 2] for i in range(0, len(only), 2)]
    result = bytearray()
    for tok in tokens:
        tok = tok.strip()
        if tok.lower().startswith("0x"):
            tok = tok[2:]
        if not tok:
            continue
        try:
            value = int(tok, 16)
        except ValueError as err:
            raise ValueError(f"Byte inválido: {tok!r} (use hex, ex.: 08 ou 0x08)") from err
        if not (0 <= value <= 0xFF):
            raise ValueError(f"Byte fora do intervalo 0x00-0xFF: {tok!r}")
        result.append(value)
    return bytes(result)


def build_command(password: str, command: int, content: bytes = b"") -> bytes:
    """Monta um frame ISECNet/ISECMobile completo pronto para envio."""
    if not (4 <= len(password) <= 6):
        raise ValueError("A senha deve ter entre 4 e 6 dígitos")
    isec_mobile = (
        bytes([FRAME_DELIMITER])
        + password.encode("ascii")
        + bytes([command])
        + content
        + bytes([FRAME_DELIMITER])
    )
    body = bytes([ISEC_COMMAND]) + isec_mobile
    num_bytes = len(body)
    if num_bytes > 255:
        raise ValueError("Conteúdo do comando excede o tamanho máximo do frame")
    frame = bytes([num_bytes]) + body
    return frame + bytes([checksum(frame)])


@dataclass
class ParsedFrame:
    """Resultado da leitura de um frame de resposta da central."""

    command: int
    content: bytes
    valid_checksum: bool
    raw: bytes = field(repr=False)


def parse_frame(raw: bytes) -> ParsedFrame:
    """Interpreta um frame bruto recebido da central (sem framing extra)."""
    if len(raw) < 3:
        raise ProtocolError(f"Frame muito curto para ser válido: {raw.hex()}")
    num_bytes = raw[0]
    expected_len = 1 + num_bytes + 1  # nº bytes + (comando+conteúdo) + checksum
    if len(raw) < expected_len:
        raise ProtocolError(
            f"Frame incompleto: esperado {expected_len} bytes, recebido {len(raw)}"
        )
    raw = raw[:expected_len]
    command = raw[1]
    content = raw[2 : 1 + num_bytes]
    received_checksum = raw[-1]
    calculated = checksum(raw[:-1])
    return ParsedFrame(
        command=command,
        content=content,
        valid_checksum=(calculated == received_checksum),
        raw=raw,
    )


def raise_for_ack(parsed: ParsedFrame) -> None:
    """Levanta NackError se a resposta curta não for ACK (0xFE)."""
    if not parsed.content:
        raise ProtocolError("Resposta vazia, esperava ACK/NACK")
    code = parsed.content[0]
    if code != ACK_OK:
        raise NackError(code)


# ---------------------------------------------------------------------------
# Construtores de comando de alto nível
# ---------------------------------------------------------------------------
def cmd_arm(password: str, partition: int | None = None, stay: bool = False) -> bytes:
    """Monta o comando 0x41 (Ativação).

    O campo <Conteúdo> documentado (seção 7.1) só detalha explicitamente o
    caso "sem partição": NULL/0x41/0x42/0x43/0x44 para escolher a
    partição, OU 0x50 sozinho para ativar em modo Stay a central inteira.
    A doc não cobre o caso "Stay de uma partição específica" — mas o fluxo
    Node-RED original usado antes desta integração (comportamento validado
    em campo) monta, nesse caso, um conteúdo de **2 bytes**: a partição
    seguida do marcador Stay (ex.: partição A em Stay = ``[0x41, 0x50]``
    como conteúdo, além do byte de comando 0x41). Reproduzido aqui.
    """
    from .const import CMD_ARM, PARTITION_STAY

    content = b""
    if partition is not None:
        content += bytes([partition])
    if stay:
        content += bytes([PARTITION_STAY])
    return build_command(password, CMD_ARM, content)


def cmd_disarm(password: str, partition: int | None = None) -> bytes:
    from .const import CMD_DISARM

    content = bytes([partition]) if partition is not None else b""
    return build_command(password, CMD_DISARM, content)


def cmd_pgm(password: str, address: int, turn_on: bool) -> bytes:
    from .const import CMD_PGM, PGM_OFF, PGM_ON

    sub = PGM_ON if turn_on else PGM_OFF
    return build_command(password, CMD_PGM, bytes([sub, address]))


def cmd_siren(password: str, turn_on: bool) -> bytes:
    from .const import CMD_SIREN_OFF, CMD_SIREN_ON

    return build_command(password, CMD_SIREN_ON if turn_on else CMD_SIREN_OFF)


def cmd_panic(password: str, kind: int) -> bytes:
    from .const import CMD_PANIC

    return build_command(password, CMD_PANIC, bytes([kind]))


def cmd_bypass(password: str, bypassed_zones: dict[int, bool]) -> bytes:
    """Monta o comando 0x42 (Bypass/Anulação de Zonas, seção 7.7).

    É um comando **absoluto**: o conteúdo de 8 bytes representa o estado
    final desejado de anulação de todas as 64 zonas do protocolo (bit 1 =
    anulada, bit 0 = ativada). Zonas omitidas de ``bypassed_zones`` (ou com
    valor ``False``) ficam ativadas — por isso, para anular zonas
    preservando anulações já existentes, o chamador deve incluir o estado
    atual de todas as zonas já anuladas (ver
    ``IntelbrasAlarmCoordinator.async_bypass_zones``).
    """
    from .const import CMD_BYPASS

    content = bytearray(8)
    for zone, bypassed in bypassed_zones.items():
        if not bypassed or not (1 <= zone <= 64):
            continue
        byte_idx = (zone - 1) // 8
        bit_idx = (zone - 1) % 8
        content[byte_idx] |= 1 << bit_idx
    return build_command(password, CMD_BYPASS, bytes(content))


def cmd_status(password: str, family: str) -> bytes:
    from .const import FAMILY_STATUS_CMD

    return build_command(password, FAMILY_STATUS_CMD[family])


def cmd_eeprom_read(password: str, address: int, length: int) -> bytes:
    from .const import CMD_EEPROM_READ

    return build_command(
        password,
        CMD_EEPROM_READ,
        bytes([(address >> 8) & 0xFF, address & 0xFF, length & 0xFF]),
    )


# ---------------------------------------------------------------------------
# Parsing dos frames de status (comandos 0x5A e 0x5B)
#
# As funções abaixo seguem a numeração <StatusNN> do documento oficial
# (seções 7.4 e 7.5). ``content`` é o array de status já sem Nº Bytes,
# Comando e Checksum (ou seja, content[0] == Status01).
# ---------------------------------------------------------------------------
def _bits_to_zone_map(
    content: bytes,
    first_status_index: int,
    n_bytes: int,
    max_zone: int,
    zone_start: int = 1,
) -> dict[int, bool]:
    """Converte ``n_bytes`` bytes de bitmap (8 zonas cada) em {zona: bool}.

    ``zone_start`` permite deslocar a numeração quando o bloco de status não
    começa na zona 1 (ex.: bateria baixa de sensores sem fio na família 4010,
    que só é reportada a partir da zona 17).
    """
    result: dict[int, bool] = {}
    for byte_offset in range(n_bytes):
        status_idx = first_status_index + byte_offset  # 1-based
        if status_idx - 1 >= len(content):
            break
        value = content[status_idx - 1]
        for bit in range(8):
            zone = zone_start + byte_offset * 8 + bit
            if zone > max_zone:
                continue
            result[zone] = bool((value >> bit) & 1)
    return result


def _format_panel_datetime(
    content: bytes, *, hh: int, mm: int, dd: int, mo: int, yy: int
) -> str | None:
    """Converte os 5 bytes de data/hora em ``"dd/mm/aaaa hh:mm"``.

    IMPORTANTE — histórico desta função: a documentação oficial (seção
    7.4/7.5, ex.: "0x12 representa 12 horas") sugere que cada byte é BCD
    (um dígito decimal por nibble). Uma versão anterior desta integração
    implementou exatamente isso via ``_bcd_to_int``. Bytes reais capturados
    pelo usuário provaram que essa leitura está ERRADA: o byte de minuto
    ``0x2E`` decodificado como BCD dá 34 (`(2×10)+14`, um cálculo que só
    "funciona" porque nunca se valida se o nibble baixo é um dígito
    decimal de verdade — 0xE=14 não é), mas o minuto real no momento da
    captura era 46 — exatamente o valor **bruto** do byte (``0x2E`` = 46
    em decimal). O mesmo padrão se repetiu com um byte de hora
    (``0x16`` bruto = 22, batendo com a hora real; BCD teria dado 16,
    errado). Também bate exatamente com o fluxo Node-RED original, que
    nunca fez nenhuma conversão BCD para estes campos (só
    ``padZero(byte)`` direto). Corrigido para usar o valor bruto do byte.
    """
    try:
        idx = [hh, mm, dd, mo, yy]
        if max(idx) >= len(content):
            return None
        hour = content[hh]
        minute = content[mm]
        day = content[dd]
        month = content[mo]
        year = 2000 + content[yy]
        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 1 <= day <= 31 and 1 <= month <= 12):
            return None
        return f"{day:02d}/{month:02d}/{year:04d} {hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        return None


def _bits_to_map(byte_value: int, numbers: list[int]) -> dict[int, bool]:
    """Mapeia os bits 0..N-1 de ``byte_value`` para os rótulos em ``numbers``.

    Usado para leituras não contíguas (ex.: zonas 1-8 e 11-18, pulando 9-10
    — assim como documentado nos Status34/35 e Status44 da central).
    """
    return {numbers[bit]: bool((byte_value >> bit) & 0x01) for bit in range(len(numbers))}


@dataclass
class PanelStatus:
    """Representação normalizada do status da central, família-agnóstica."""

    model_key: str
    model_name: str
    family: str
    firmware: str
    zones_open: dict[int, bool]
    zones_violated: dict[int, bool]
    zones_bypassed: dict[int, bool]
    zones_low_battery: dict[int, bool]
    partition_mode_enabled: bool
    partitions_armed: dict[str, bool]
    activated: bool
    zone_triggered: bool
    trigger_bit_latched: bool  # bit 6 bruto do Status23/30, ANTES de combinar com a sirene (ver zone_triggered)
    zone_open_flag: bool  # bit 2 do Status23/30: "alguma zona aberta" (flag agregada, não por zona)
    status_byte_raw: int  # valor cru do Status23 (2018/1016) ou Status30 (4010), p/ diagnóstico
    status_byte_name: str  # "status23" ou "status30" — para rotular o atributo acima dinamicamente
    partition_status_bytes: dict[str, int]  # nome->valor bruto: {"status22": 0x..} ou {"status28": 0x.., "status29": 0x..}
    partition_bit_map: dict[str, tuple[str, int]]  # partição -> (nome do byte, índice do bit) usado por ela
    siren_on: bool
    problem: bool
    ac_power_fault: bool  # bit0 do Status29/36 cru — 1 = falta de rede elétrica (problema)
    battery_low: bool
    battery_missing_or_reversed: bool
    battery_short: bool
    aux_overload: bool
    battery_level: int
    pgm_state: dict[int, bool]
    panel_datetime_str: str | None  # "dd/mm/aaaa hh:mm" já formatado, decodificado de BCD.
    # Faz parte normal da comparação de igualdade (usada por
    # always_update=False, ver __init__ do coordinator) — de propósito:
    # é um dado real que a central está reportando, então uma mudança
    # de minuto genuinamente reflete a central respondendo algo
    # diferente, mesmo que nenhum sensor tenha mudado — cadência baixa
    # o suficiente (no máximo 1x/minuto, para as famílias 2018/4010,
    # que só têm precisão de minuto mesmo) para não valer a pena
    # excluir. Only a AMT 8000 precisava de tratamento à parte, ver
    # protocol_amt8000.py — corrigido lá, não aqui, truncando pra
    # minuto antes de chegar neste campo (ela reporta segundo, o que
    # sem esse truncamento causaria até 60 atualizações por minuto).
    siren_wire_cut: bool
    siren_short_circuit: bool
    phone_line_cut: bool
    event_communication_failure: bool
    keypad_problem: dict[int, bool]  # {1..4: bool}
    receiver_problem: dict[int, bool]  # {1..4: bool}
    keypad_tamper: dict[int, bool]  # {1..4: bool} — atributo das entidades de problema no teclado
    zones_tamper: dict[int, bool]  # zonas com leitura de tamper disponível (1-8 e 11-18 na 2018/1016; 1-8 na 4010)
    zones_short_circuit: dict[int, bool]  # mesmo alcance de zonas_tamper
    pgm_expander_problem: dict[int, bool]  # {1..4: bool} — só 4010, vazio na 2018/1016
    zone_expander_problem: dict[int, bool]  # {1..6: bool} — só 4010, vazio na 2018/1016
    # Campo adicionado para a AMT 8000 (ver protocol_amt8000.py): falha de
    # comunicação por zona sem fio (RF). Fica sempre vazio {} nas famílias
    # 2018/4010, que não têm esse dado — dataclass reaproveitada tal como
    # está entre as três famílias (evita duplicar praticamente todas as
    # entidades sensor/binary_sensor entre elas).
    zones_comm_failure: dict[int, bool] = field(default_factory=dict)


def parse_status_2018(content: bytes) -> PanelStatus:
    """Parseia a resposta do comando 0x5A (43 bytes) — família 2018/1016."""
    from .const import MODEL_TABLE, MODEL_UNKNOWN

    zones_open = _bits_to_zone_map(content, 1, 6, 48)
    zones_violated = _bits_to_zone_map(content, 7, 6, 48)
    zones_bypassed = _bits_to_zone_map(content, 13, 6, 48)
    zones_low_battery = _bits_to_zone_map(content, 39, 5, 40)

    model_byte = content[18] if len(content) > 18 else None
    model_key, model_name, family, _, _ = MODEL_TABLE.get(
        model_byte, (MODEL_UNKNOWN, "Desconhecido", "2018", 48, 2)
    )
    fw_byte = content[19] if len(content) > 19 else 0
    firmware = f"{(fw_byte >> 4) & 0x0F}.{fw_byte & 0x0F}"

    status21 = content[20] if len(content) > 20 else 0
    status22 = content[21] if len(content) > 21 else 0
    status23 = content[22] if len(content) > 22 else 0
    status29 = content[28] if len(content) > 28 else 0
    status30_problems = content[29] if len(content) > 29 else 0  # teclado/receptor
    status32 = content[31] if len(content) > 31 else 0  # tamper teclado
    status33 = content[32] if len(content) > 32 else 0
    status34 = content[33] if len(content) > 33 else 0  # tamper zonas 1-8
    status35 = content[34] if len(content) > 34 else 0  # tamper zonas 11-18
    status36 = content[35] if len(content) > 35 else 0  # curto zonas 1-8
    status37 = content[36] if len(content) > 36 else 0  # curto zonas 11-18
    status38 = content[37] if len(content) > 37 else 0

    partition_mode_enabled = bool(status21 & 0x01)
    partitions_armed = {
        "A": bool(status22 & 0x01),
        "B": bool((status22 >> 1) & 0x01),
    }
    partition_status_bytes = {"status22": status22}
    partition_bit_map: dict[str, tuple[str, int]] = {
        "A": ("status22", 0),
        "B": ("status22", 1),
    }
    # Status23 (2018/1016) / Status30 (4010): regra confirmada pelo usuário
    # a partir de captura de bytes reais (não mais leitura literal da
    # tabela de valores enumerados da doc, seção 7.4 — na prática é uma
    # máscara de bits de verdade):
    #   bit 0        -> parte de "problema na central" (junto com bit 5)
    #   bit 2        -> alguma zona aberta
    #   bit 3        -> central ativada
    #   bit 5        -> parte de "problema na central" (junto com bit 0)
    #   bit 6        -> "disparo" — mas ver ressalva abaixo, é um bit
    #                   LATCHED (fica em 1 até a MESMA partição ser
    #                   reativada), não um indicador de disparo ao vivo.
    # "Ativada" da CENTRAL usa o bit 3 deste byte (bits 0 do Status22/28 e
    # 1 do Status22/28, ou 0/1 do Status29, continuam sendo a fonte de
    # "ativada" de cada PARTIÇÃO individualmente — ver partitions_armed).
    activated = bool((status23 >> 3) & 0x01)
    zone_open_flag = bool((status23 >> 2) & 0x01)
    problem = bool(status23 & 0x01) and bool((status23 >> 4) & 0x01)
    # Sirene: bit 2 do Status38 (NÃO bit 1 do Status23 — essa era a leitura
    # anterior, incorreta; corrigida a partir da documentação oficial,
    # seção 7.5/página 11: "<Status38>: Bit 2: Status sirene").
    siren_on = bool((status38 >> 2) & 0x01)
    # "Disparo real": o bit 6 do Status23 é uma memória (latched) que só
    # zera quando a MESMA partição que disparou é reativada — se outra
    # partição for ativada nesse meio-tempo, o bit 6 continua em 1 e
    # geraria um falso "triggered" nela. Capturado e confirmado pelo
    # usuário em campo (ver histórico deste arquivo). A sirene realmente
    # tocando (Status38 bit 2) é o sinal de que o disparo ainda está
    # ativo — combinado aqui para que "zone_triggered" só valha para um
    # disparo genuíno em andamento, não uma memória antiga.
    zone_triggered = bool((status23 >> 6) & 0x01) and siren_on
    trigger_bit_latched = bool((status23 >> 6) & 0x01)

    # Nível de bateria: fiel à lógica do fluxo Node-RED original — o gate
    # correto é "bateria ausente ou invertida" (Status29 bit2), não
    # "bateria em curto" (bit3) sozinho. A versão anterior só checava o
    # bit3, então uma bateria ausente (bit2) continuava sendo lida como se
    # tivesse carga. Qualquer um dos dois problemas força 0%, já que os
    # dois tornam a leitura do nível pouco confiável.
    battery_missing_or_reversed = bool((status29 >> 2) & 0x01)
    battery_short = bool((status29 >> 3) & 0x01)
    battery_level = 0
    if not battery_missing_or_reversed and not battery_short and len(content) > 30:
        battery_level = {0x0F: 100, 0x07: 75, 0x03: 50, 0x01: 25, 0x00: 0}.get(
            content[30] & 0x0F, 0
        )

    pgm_state = {
        1: bool((status38 >> 6) & 0x01),
        2: bool((status38 >> 5) & 0x01),
    }

    # Problema no teclado 1-4 / receptor 1-4 (Status30, seção 7.4/pág.10)
    keypad_problem = {n: bool((status30_problems >> (n - 1)) & 0x01) for n in range(1, 5)}
    receiver_problem = {n: bool((status30_problems >> (n - 1 + 4)) & 0x01) for n in range(1, 5)}
    # Tamper no teclado 1-4 (Status32 bits 4-7)
    keypad_tamper = {n: bool((status32 >> (n - 1 + 4)) & 0x01) for n in range(1, 5)}
    # Tamper/curto-circuito nas zonas — Status34/35 e 36/37 pulam as zonas
    # 9 e 10 (assim mesmo na documentação oficial, não é engano nosso).
    zones_tamper = {**_bits_to_map(status34, list(range(1, 9))), **_bits_to_map(status35, list(range(11, 19)))}
    zones_short_circuit = {
        **_bits_to_map(status36, list(range(1, 9))),
        **_bits_to_map(status37, list(range(11, 19))),
    }

    return PanelStatus(
        model_key=model_key,
        model_name=model_name,
        family=family,
        firmware=firmware,
        zones_open=zones_open,
        zones_violated=zones_violated,
        zones_bypassed=zones_bypassed,
        zones_low_battery=zones_low_battery,
        partition_mode_enabled=partition_mode_enabled,
        partitions_armed=partitions_armed,
        activated=activated,
        zone_triggered=zone_triggered,
        trigger_bit_latched=trigger_bit_latched,
        zone_open_flag=zone_open_flag,
        status_byte_raw=status23,
        status_byte_name="status23",
        partition_status_bytes=partition_status_bytes,
        partition_bit_map=partition_bit_map,
        siren_on=siren_on,
        problem=problem,
        ac_power_fault=bool(status29 & 0x01),
        battery_low=bool((status29 >> 1) & 0x01),
        battery_missing_or_reversed=battery_missing_or_reversed,
        battery_short=battery_short,
        aux_overload=bool((status29 >> 4) & 0x01),
        battery_level=battery_level,
        pgm_state=pgm_state,
        panel_datetime_str=_format_panel_datetime(content, hh=23, mm=24, dd=25, mo=26, yy=27),
        siren_wire_cut=bool(status33 & 0x01),
        siren_short_circuit=bool((status33 >> 1) & 0x01),
        phone_line_cut=bool((status33 >> 2) & 0x01),
        event_communication_failure=bool((status33 >> 3) & 0x01),
        keypad_problem=keypad_problem,
        receiver_problem=receiver_problem,
        keypad_tamper=keypad_tamper,
        zones_tamper=zones_tamper,
        zones_short_circuit=zones_short_circuit,
        pgm_expander_problem={},
        zone_expander_problem={},
    )


@dataclass
class ESmartExtraStatus:
    """Dados adicionais presentes só na resposta 0x5D da AMT 2018 E SMART
    (``const.CMD_STATUS_ESMART``), além dos campos padrão já cobertos por
    ``PanelStatus``/``parse_status_2018``.

    Nada aqui é garantido — a resposta real varia de tamanho (já
    observamos uma captura real com só 95 bytes de conteúdo, bem menos
    que os ~204 necessários pra cobrir tudo). Cada campo fica ``None``
    (ou os dicionários ficam vazios) se a resposta não for longa o
    bastante para alcançá-lo — nunca inventamos um valor.

    Extraído por engenharia reversa do app oficial (`Amt2018ESmart.
    updateZonesDevicesStatus()`/`updateGeneralNetworkStatus()`/
    `updateStatusAttributes()`/`defineStay()`), com um exemplo de captura
    real cruzado (checksum e byte de modelo confirmados, mas curto
    demais pra validar os valores das seções abaixo). Ver
    README_DETALHADO.md, seção "AMT 2018 E Smart — dados adicionais".
    """

    # content[92] (byte 94 na numeração do app) — Stay reportado pela
    # própria central (diferente do nosso controle local de "o último
    # comando enviado foi Stay", usado por todos os outros modelos).
    stay_a_reported: bool | None = None
    stay_b_reported: bool | None = None

    # Só zonas 25-48 têm esses dados no app oficial (zonas 1-24 são
    # sempre fiadas nessa central; 25-48 são a faixa sem fio/expansão).
    zones_wireless: dict[int, bool] = field(default_factory=dict)
    zones_tamper_esmart: dict[int, bool] = field(default_factory=dict)
    zones_short_circuit_esmart: dict[int, bool] = field(default_factory=dict)
    zones_battery_low_esmart: dict[int, bool] = field(default_factory=dict)
    zones_supervised: dict[int, bool] = field(default_factory=dict)
    zones_supervision_failure: dict[int, bool] = field(default_factory=dict)
    zones_device_model: dict[int, str] = field(default_factory=dict)  # "XAS"/"IVP"

    # Rede (content[134:162], bytes 136-163 na numeração do app)
    data_network_type: str | None = None  # "GPRS"/"3G"/"4G"
    ip1_ethernet_online: bool | None = None
    ip2_ethernet_online: bool | None = None
    cloud_ethernet_online: bool | None = None
    ip1_cellular_online: bool | None = None
    ip2_cellular_online: bool | None = None
    cloud_cellular_online: bool | None = None
    ip_address: str | None = None
    netmask: str | None = None
    gateway: str | None = None
    dns1: str | None = None
    dns2: str | None = None
    mac_address: str | None = None

    # Celular (content[162:202], bytes 164-203 na numeração do app)
    cellular_module_present: bool | None = None
    cellular_module_type: str | None = None  # "XG 2G"/"XG 3G"/"XG 4G"
    cellular_signal_percent: int | None = None
    chip_in_use: int | None = None
    carrier: str | None = None
    chip_id: str | None = None
    imei: str | None = None


def parse_status_2018_esmart_extra(content: bytes) -> ESmartExtraStatus:
    """Extrai os dados adicionais da resposta 0x5D da AMT 2018 E SMART.

    Sempre recebe ``content`` inteiro (pode ter de 43 a ~204+ bytes) —
    cada seção só é preenchida se ``content`` for longo o bastante para
    alcançá-la, do contrário fica com os valores padrão (``None``/dict
    vazio) da dataclass.
    """
    extra = ESmartExtraStatus()

    def bit(idx: int, n: int) -> bool | None:
        """Bit ``n`` (0=LSB) do byte em ``content[idx]``, ou ``None`` se
        ``content`` não alcançar esse índice."""
        if idx >= len(content):
            return None
        return bool((content[idx] >> n) & 1)

    # --- Stay reportado pela central (content[92]) ---
    stay_byte = 92
    if stay_byte < len(content):
        extra.stay_a_reported = bit(stay_byte, 0)
        extra.stay_b_reported = bit(stay_byte, 1)

    # --- Zonas 25-48: bitmaps de 3 bytes cada (zonas 25-48 = 24 zonas =
    # 3 bytes de 8 bits), começando no offset-base de cada campo + o
    # grupo de 8 zonas (0,1,2) dentro da faixa 25-48. ---
    ZONE_FIRST = 25
    ZONE_LAST = 48
    campos_bitmap = [
        ("zones_wireless", 62),
        ("zones_tamper_esmart", 68),
        ("zones_short_circuit_esmart", 74),
        ("zones_supervised", 130),  # "modo supervisão" (base 132 na doc)
        ("zones_supervision_failure", 95),
    ]
    for nome_campo, base in campos_bitmap:
        destino: dict[int, bool] = {}
        for zona in range(ZONE_FIRST, ZONE_LAST + 1):
            grupo = (zona - 1) // 8  # 0, 1 ou 2 dentro da faixa 25-48
            idx = base + grupo
            valor = bit(idx, (zona - 1) % 8)
            if valor is not None:
                destino[zona] = valor
        setattr(extra, nome_campo, destino)

    # Bateria usa lógica invertida no app (bit '0' = ok, '1' = baixa) —
    # ver docstring da dataclass. Convertido aqui pra "True = bateria
    # baixa", consistente com zones_low_battery já usado no resto da
    # integração.
    destino_bateria: dict[int, bool] = {}
    for zona in range(ZONE_FIRST, ZONE_LAST + 1):
        grupo = (zona - 1) // 8
        idx = 80 + grupo
        valor = bit(idx, (zona - 1) % 8)
        if valor is not None:
            destino_bateria[zona] = valor  # bit=1 já significa "baixa" (ver bit())
    extra.zones_battery_low_esmart = destino_bateria

    # Modelo do dispositivo por zona: "XAS" (bit=0) ou "IVP" (bit=1)
    destino_modelo: dict[int, str] = {}
    for zona in range(ZONE_FIRST, ZONE_LAST + 1):
        grupo = (zona - 1) // 8
        idx = 98 + grupo
        valor = bit(idx, (zona - 1) % 8)
        if valor is not None:
            destino_modelo[zona] = "IVP" if valor else "XAS"
    extra.zones_device_model = destino_modelo

    # --- Rede (content[134] em diante) ---
    if 134 < len(content):
        extra.data_network_type = {0: "GPRS", 1: "3G"}.get(content[134], "4G")
    if 135 < len(content):
        conexoes = content[135]
        extra.ip1_ethernet_online = bool((conexoes >> 0) & 1)
        extra.ip2_ethernet_online = bool((conexoes >> 1) & 1)
        extra.cloud_ethernet_online = bool((conexoes >> 2) & 1)
        extra.ip1_cellular_online = bool((conexoes >> 4) & 1)
        extra.ip2_cellular_online = bool((conexoes >> 5) & 1)
        extra.cloud_cellular_online = bool((conexoes >> 6) & 1)

    def ipv4(base: int) -> str | None:
        fim = base + 4
        if fim > len(content):
            return None
        return ".".join(str(b) for b in content[base:fim])

    extra.ip_address = ipv4(136)
    extra.netmask = ipv4(140)
    extra.gateway = ipv4(144)
    extra.dns1 = ipv4(148)
    extra.dns2 = ipv4(152)
    if 162 <= len(content):
        extra.mac_address = ":".join(f"{b:02X}" for b in content[156:162])

    # --- Celular/SIM (content[162] em diante) ---
    if 162 < len(content):
        extra.cellular_module_present = content[162] != 0
    if extra.cellular_module_present and 163 < len(content):
        extra.cellular_module_type = {1: "XG 2G", 2: "XG 3G", 3: "XG 4G"}.get(content[163])
        if 164 < len(content):
            extra.cellular_signal_percent = content[164]
        if 165 < len(content):
            extra.chip_in_use = content[165]
        if 166 < len(content):
            extra.carrier = {0: "Claro", 1: "Oi", 2: "Tim", 3: "Vivo"}.get(content[166], "Desconhecida")
        if 187 <= len(content):
            extra.chip_id = "".join(chr(b) for b in content[167:187] if 32 <= b < 127)
        if 202 <= len(content):
            extra.imei = "".join(chr(b) for b in content[187:202] if 32 <= b < 127)

    return extra


def parse_status_4010(content: bytes) -> PanelStatus:
    """Parseia a resposta do comando 0x5B (até 54 bytes) — família 4010."""
    from .const import MODEL_TABLE, MODEL_UNKNOWN

    zones_open = _bits_to_zone_map(content, 1, 8, 64)
    zones_violated = _bits_to_zone_map(content, 9, 8, 64)
    zones_bypassed = _bits_to_zone_map(content, 17, 8, 64)
    zones_low_battery = _bits_to_zone_map(content, 47, 6, 64, zone_start=17)

    model_byte = content[24] if len(content) > 24 else None
    model_key, model_name, family, _, _ = MODEL_TABLE.get(
        model_byte, (MODEL_UNKNOWN, "Desconhecido", "4010", 64, 4)
    )
    fw_byte = content[25] if len(content) > 25 else 0
    firmware = f"{(fw_byte >> 4) & 0x0F}.{fw_byte & 0x0F}"

    status27 = content[26] if len(content) > 26 else 0
    status28 = content[27] if len(content) > 27 else 0
    status29 = content[28] if len(content) > 28 else 0
    status30 = content[29] if len(content) > 29 else 0
    status36 = content[35] if len(content) > 35 else 0
    status37_problems = content[36] if len(content) > 36 else 0  # teclado/receptor
    status38 = content[37] if len(content) > 37 else 0  # expansores PGM/zona 1-4
    status39 = content[38] if len(content) > 38 else 0  # expansores zona 5-6
    status42 = content[41] if len(content) > 41 else 0  # tamper teclado
    status43 = content[42] if len(content) > 42 else 0
    status44 = content[43] if len(content) > 43 else 0  # tamper zonas 1-8
    status45 = content[44] if len(content) > 44 else 0  # curto zonas 1-8
    status46 = content[45] if len(content) > 45 else 0
    status53 = content[52] if len(content) > 52 else 0
    status54 = content[53] if len(content) > 53 else 0

    partition_mode_enabled = bool(status27 & 0x01)
    partitions_armed = {
        "A": bool(status28 & 0x01),
        "B": bool((status28 >> 1) & 0x01),
        "C": bool(status29 & 0x01),
        "D": bool((status29 >> 1) & 0x01),
    }
    partition_status_bytes = {"status28": status28, "status29": status29}
    partition_bit_map: dict[str, tuple[str, int]] = {
        "A": ("status28", 0),
        "B": ("status28", 1),
        "C": ("status29", 0),
        "D": ("status29", 1),
    }
    # "Ativada" da CENTRAL usa o bit 3 do Status30 — mesma regra confirmada
    # com o usuário, ver o comentário detalhado em parse_status_2018.
    # Cada PARTIÇÃO continua usando seu próprio bit em Status28/29
    # (partitions_armed).
    activated = bool((status30 >> 3) & 0x01)
    zone_open_flag = bool((status30 >> 2) & 0x01)
    problem = bool(status30 & 0x01) and bool((status30 >> 4) & 0x01)
    # Sirene: bit 3 do Status46 (não bit 2, como documentação e uma
    # correção anterior indicavam incorretamente — confirmado pelo
    # usuário especificamente para a família 4010; a 2018/1016 continua
    # usando o bit 2 do Status38, que está correto e não muda).
    siren_on = bool((status46 >> 3) & 0x01)
    # "Disparo real": mesmo raciocínio do parse_status_2018 — o bit 6 do
    # Status30 fica latched até a mesma partição ser reativada; combinado
    # com a sirene realmente tocando para não confundir memória antiga com
    # disparo em andamento.
    zone_triggered = bool((status30 >> 6) & 0x01) and siren_on
    trigger_bit_latched = bool((status30 >> 6) & 0x01)

    # Nível de bateria: mesmo raciocínio do parse_status_2018 — gate por
    # "ausente/invertida" (bit2) OU "curto" (bit3), não só curto.
    battery_missing_or_reversed = bool((status36 >> 2) & 0x01)
    battery_short = bool((status36 >> 3) & 0x01)
    battery_level = 0
    if not battery_missing_or_reversed and not battery_short and len(content) > 40:
        battery_level = {0x0F: 100, 0x07: 75, 0x03: 50, 0x01: 25, 0x00: 0}.get(
            content[40] & 0x0F, 0
        )

    pgm_state = {
        1: bool((status46 >> 6) & 0x01),
        2: bool((status46 >> 5) & 0x01),
        3: bool((status46 >> 4) & 0x01),
    }
    for bit in range(8):
        pgm_state[4 + bit] = bool((status53 >> bit) & 0x01)
    for bit in range(8):
        pgm_state[12 + bit] = bool((status54 >> bit) & 0x01)

    keypad_problem = {n: bool((status37_problems >> (n - 1)) & 0x01) for n in range(1, 5)}
    receiver_problem = {n: bool((status37_problems >> (n - 1 + 4)) & 0x01) for n in range(1, 5)}
    keypad_tamper = {n: bool((status42 >> (n - 1 + 4)) & 0x01) for n in range(1, 5)}
    # Só zonas 1-8 têm tamper/curto documentados para a 4010 (sem
    # equivalente às 11-18 da família 2018/1016).
    zones_tamper = _bits_to_map(status44, list(range(1, 9)))
    zones_short_circuit = _bits_to_map(status45, list(range(1, 9)))
    pgm_expander_problem = {n: bool((status38 >> (n - 1)) & 0x01) for n in range(1, 5)}
    zone_expander_problem = {n: bool((status38 >> (n - 1 + 4)) & 0x01) for n in range(1, 5)}
    zone_expander_problem[5] = bool(status39 & 0x01)
    zone_expander_problem[6] = bool((status39 >> 1) & 0x01)

    return PanelStatus(
        model_key=model_key,
        model_name=model_name,
        family=family,
        firmware=firmware,
        zones_open=zones_open,
        zones_violated=zones_violated,
        zones_bypassed=zones_bypassed,
        zones_low_battery=zones_low_battery,
        partition_mode_enabled=partition_mode_enabled,
        partitions_armed=partitions_armed,
        activated=activated,
        zone_triggered=zone_triggered,
        trigger_bit_latched=trigger_bit_latched,
        zone_open_flag=zone_open_flag,
        status_byte_raw=status30,
        status_byte_name="status30",
        partition_status_bytes=partition_status_bytes,
        partition_bit_map=partition_bit_map,
        siren_on=siren_on,
        problem=problem,
        ac_power_fault=bool(status36 & 0x01),
        battery_low=bool((status36 >> 1) & 0x01),
        battery_missing_or_reversed=battery_missing_or_reversed,
        battery_short=battery_short,
        aux_overload=bool((status36 >> 4) & 0x01),
        battery_level=battery_level,
        pgm_state=pgm_state,
        panel_datetime_str=_format_panel_datetime(content, hh=30, mm=31, dd=32, mo=33, yy=34),
        siren_wire_cut=bool(status43 & 0x01),
        siren_short_circuit=bool((status43 >> 1) & 0x01),
        phone_line_cut=bool((status43 >> 2) & 0x01),
        event_communication_failure=bool((status43 >> 3) & 0x01),
        keypad_problem=keypad_problem,
        receiver_problem=receiver_problem,
        keypad_tamper=keypad_tamper,
        zones_tamper=zones_tamper,
        zones_short_circuit=zones_short_circuit,
        pgm_expander_problem=pgm_expander_problem,
        zone_expander_problem=zone_expander_problem,
    )


def parse_status(content: bytes, family: str) -> PanelStatus:
    from .const import FAMILY_2018

    if family == FAMILY_2018:
        return parse_status_2018(content)
    return parse_status_4010(content)


# ---------------------------------------------------------------------------
# Nomes de zona (EEPROM, família 4010) — mapa confirmado por captura real
# ---------------------------------------------------------------------------
def decode_zone_names(eeprom_data: bytes, zone_offset: int) -> dict[int, str]:
    """Decodifica registros de 16 bytes ASCII terminados em NUL.

    ``eeprom_data`` já deve estar sem o byte <Dado01> (índice do usuário).
    ``zone_offset`` é o número da primeira zona contida neste bloco (1-based).
    """
    from .const import ZONE_NAME_RECORD_LEN

    names: dict[int, str] = {}
    for i in range(0, len(eeprom_data), ZONE_NAME_RECORD_LEN):
        record = eeprom_data[i : i + ZONE_NAME_RECORD_LEN]
        if len(record) < ZONE_NAME_RECORD_LEN:
            break
        raw = record.split(b"\x00", 1)[0]
        try:
            name = raw.decode("ascii", errors="ignore").strip()
        except UnicodeDecodeError:
            name = ""
        zone = zone_offset + (i // ZONE_NAME_RECORD_LEN)
        names[zone] = name if (name and not _is_uninitialized_pattern(raw)) else f"Zona {zone:02d}"
    return names


def decode_user_names(eeprom_data: bytes, user_offset: int) -> dict[int, str]:
    """Decodifica nomes de usuário — mesmo formato de registro de
    ``decode_zone_names`` (16 bytes ASCII terminados em NUL), mas sem
    rótulo de reposição: usuário sem nome configurado (ou com o padrão
    de fábrica não programado) simplesmente não entra no dict, em vez
    de ganhar um nome genérico tipo "Usuário 05" — mesmo critério já
    usado por ``protocol_legacy_eeprom.parse_nomes()`` para usuários
    (diferente do critério para zonas, onde um rótulo genérico ajuda a
    identificar fisicamente qual zona é qual mesmo sem nome).
    """
    from .const import USER_NAME_RECORD_LEN

    names: dict[int, str] = {}
    for i in range(0, len(eeprom_data), USER_NAME_RECORD_LEN):
        record = eeprom_data[i : i + USER_NAME_RECORD_LEN]
        if len(record) < USER_NAME_RECORD_LEN:
            break
        raw = record.split(b"\x00", 1)[0]
        try:
            name = raw.decode("ascii", errors="ignore").strip()
        except UnicodeDecodeError:
            name = ""
        if name and not _is_uninitialized_pattern(raw):
            names[user_offset + (i // USER_NAME_RECORD_LEN)] = name
    return names


def _is_uninitialized_pattern(raw: bytes) -> bool:
    """Detecta o padrão de fábrica (EEPROM nunca programada pelo instalador).

    Zonas sem nome configurado retornam bytes ASCII sequenciais (ex.:
    ``ABCDEFGHIJKLMN``), confirmado em captura real — não é um nome válido.
    """
    if len(raw) < 2:
        return False
    return all(raw[i] + 1 == raw[i + 1] for i in range(len(raw) - 1))


# ---------------------------------------------------------------------------
# EEPROM — log de eventos (comando 0x5C, endereço 0x1800, registros de 8
# bytes cada). Estrutura de bits e tabela de códigos confirmadas por
# captura real e cruzadas com a tela de configuração de eventos do
# software oficial "Receptor IP" da Intelbras — ver README_DETALHADO.md.
# ---------------------------------------------------------------------------

# byte do registro (campo "codigo_raw" de parse_event_record) -> (código de
# 4 dígitos exibido no app/Receptor IP, descrição oficial). Só inclui os
# bytes brutos que já foram observados e confirmados em captura real — um
# código de evento cujo byte bruto ainda não foi visto aparece como
# "Código desconhecido (N)" em vez de arriscar um palpite errado.
EVENT_CODE_TABLE: dict[int, tuple[str, str]] = {
    0: ("3401", "Ativação pelo usuário"),
    128: ("1401", "Desativação pelo usuário"),
    1: ("3456", "Ativação parcial"),
    2: ("3130", "Restauração de disparo de zona"),
    130: ("1130", "Disparo de zona"),
    42: ("3147", "Restauração da supervisão Smart"),
    170: ("1147", "Falha da supervisão Smart"),
    43: ("3422", "Desacionamento de PGM"),
    171: ("1422", "Acionamento de PGM"),
    139: ("1570", "Anulação temporária de zona"),
    160: ("1410", "Acesso remoto pelo software de download/upload"),
    163: ("1602", "Teste periódico"),
    137: ("1333", "Problema em teclado ou receptor"),
    167: ("3301", "Restauração falha na rede elétrica"),
    13: ("1625", "Data e hora foram reiniciadas"),
    143: ("1311", "Bateria principal ausente ou invertida"),
    # Os 5 abaixo foram confirmados posteriormente, num trabalho paralelo
    # de captura própria (mesma metodologia dos 17 originais: captura real
    # cruzada com a tela do app AMT Remoto Desktop) — inclui a correção de
    # que o byte 45 na verdade mapeia para 3531, não 3333 (o 3333 correto
    # é o byte 9; a atribuição original do 45 estava errada).
    9: ("3333", "Restauração problema em teclado ou receptor"),
    45: ("3531", "Dispositivo Encontrado"),
    47: ("3361", "Keep alive ethernet recuperado"),
    158: ("1354", "Falha ao comunicar evento"),
    165: ("1621", "Reset do buffer de eventos"),
    175: ("1361", "Falha keep alive ethernet"),
    # Os 4 abaixo foram confirmados diretamente pelo usuário, lendo o
    # log de eventos de uma central real (AMT 1016 NET, firmware 3.1) e
    # comparando com o que o próprio app mostra pra cada um. 3 batem
    # exatamente com descrições que já tínhamos catalogado (só
    # atribuindo o byte bruto que faltava); o quarto (byte 15) não
    # corresponde a nenhum código de 4 dígitos já confirmado — o número
    # "1303" aqui é uma extrapolação nossa (mesmo padrão de agrupamento
    # dos outros "13xx" de bateria), não confirmada contra a tela
    # oficial do app — possível particularidade de firmwares antigos,
    # como o usuário observou.
    141: ("1301", "Falha na rede elétrica"),
    142: ("1302", "Bateria principal baixa ou em curto-circuito"),
    14: ("3302", "Restauração bat. princ. baixa ou em curto-circuito"),
    15: ("1303", "Bateria principal pendente"),
}

_EVENT_PARTITION_LETTERS = {0: "-", 1: "A", 2: "B", 3: "C", 4: "D"}


def parse_event_record(record: bytes) -> dict | None:
    """Decodifica um registro de 8 bytes do log de eventos (EEPROM 0x1800+).

    Estrutura confirmada por captura real: os 8 bytes são invertidos e
    tratados como uma sequência única de 64 bits, com os campos abaixo
    lidos em faixas de bits específicas (não são bytes alinhados). Ver
    README_DETALHADO.md para o significado de cada faixa.

    Devolve ``None`` para registros vazios/não inicializados (mês ou dia
    fora do intervalo válido — nunca gravados pela central ainda), em vez
    de inventar uma data inválida.
    """
    if len(record) != 8:
        raise ValueError(f"Registro de evento deve ter 8 bytes, recebeu {len(record)}")

    bits = "".join(f"{b:08b}" for b in reversed(record))

    def campo(inicio: int, fim: int) -> int:
        return int(bits[inicio:fim], 2)

    ano = campo(1, 8)
    dia = campo(10, 15)
    hora = campo(15, 20)
    minuto = campo(20, 26)
    segundo = campo(26, 32)
    mes = campo(32, 36)
    zona_usuario = campo(36, 48)
    codigo_raw = campo(48, 56)
    particao_bruta = campo(58, 64)
    if particao_bruta > 9:
        particao_bruta -= 6

    from datetime import datetime

    try:
        data_hora = datetime(2000 + ano, mes, dia, hora, minuto, segundo)
    except ValueError:
        return None  # registro vazio/não inicializado — não é um evento real

    codigo_app, descricao = EVENT_CODE_TABLE.get(
        codigo_raw, (None, f"Código desconhecido ({codigo_raw})")
    )

    return {
        "data_hora": data_hora,
        "zona_usuario": zona_usuario,
        "particao": _EVENT_PARTITION_LETTERS.get(particao_bruta, str(particao_bruta)),
        "codigo_raw": codigo_raw,
        "codigo_app": codigo_app,
        "descricao": descricao,
    }

