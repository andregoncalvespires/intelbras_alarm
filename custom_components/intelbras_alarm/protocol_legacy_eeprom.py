"""Protocolo legado de leitura de EEPROM (comando ``0xE7``) — nomes de
zona/usuário e log de eventos, para modelos/firmwares que **não**
alcançam o limiar do comando moderno ``0x5C`` (ver
``coordinator.supports_extended_eeprom``).

Confirmado funcionando de ponta a ponta em hardware real (AMT 1016 NET,
firmware 3.1) — autenticação bem-sucedida (``status: 0x50``) seguida de
leitura completa de nomes de zona, usuário, receptor/teclado e do log de
eventos, com texto legível batendo com os nomes reais configurados na
central. Extraído por engenharia reversa do APK oficial (`AMT Mobile`
v3.4.2.2), decompilando ``ProtocoloReceptorIP.montarComandoIdentify()``,
``.readEEPROM()``, ``.calcularCRC()``, ``SincronizarNomes.run()`` e
``BaixarEventos.run()`` — cruzado e validado contra uma leitura real
completa fornecida pelo usuário.

⚠️ Diferente do restante do protocolo ISECMobile (``protocol.py``): usa
seu próprio esquema de senha (dígitos convertidos, ver
``montar_comando_autenticar``) e seu próprio algoritmo de CRC (não é o
CRC16 padrão nenhum — tem uma peculiaridade de "pular os 2 primeiros
deslocamentos", replicada byte a byte do bytecode decompilado).

Os endereços/paginação (``NAMES_*``/``EVENTS_*`` abaixo) vêm de
constantes literais encontradas no código decompilado
(``SincronizarNomes.syncNames()``/``BaixarEventos``) — confirmados
funcionando na AMT 1016 NET testada; ainda não confirmados
independentemente para os demais modelos que também caem fora do
limiar do ``0x5C`` (AMT 2018 EG/4010 SMART em firmwares antigos) — a
suposição é que compartilham o mesmo layout de EEPROM, por virem do
mesmo trecho de código do app, não específico de modelo.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import checksum, parse_event_record

# ---------------------------------------------------------------------
# Paginação (constantes literais do app oficial, confirmadas na AMT 1016
# NET real) -- ver docstring do módulo.
# ---------------------------------------------------------------------
NAMES_START = 2048
NAMES_PAGE = 189
NAMES_END = 4316
NAMES_LAST = 67

EVENTS_START = 6144
EVENTS_PAGE = 189
EVENTS_END = 8034
EVENTS_LAST = 159

NAME_RECORD_SIZE = 16
EVENT_RECORD_SIZE = 8
NAME_TABLE_CAPACITY = 64  # a tabela de zonas/usuários é sempre
# dimensionada para 64 posições na EEPROM, independente de quantas a
# central realmente usa -- por isso usuários começam sempre no offset
# fixo NAME_TABLE_CAPACITY * NAME_RECORD_SIZE, não em "número de zonas".

DELAY_ENTRE_REQUISICOES = 0.15  # segundos -- mesmo valor usado no
# script de referência que validou este protocolo contra hardware real;
# evita sobrecarregar a central com requisições em sequência rápida
# demais.


def calcular_crc(valores: list[int]) -> int:
    """CRC próprio deste protocolo — NÃO é CRC16 padrão nenhum.

    Porte literal, byte a byte, de ``ProtocoloReceptorIP.calcularCRC()``
    (bytecode do app oficial decompilado) — tem uma peculiaridade real:
    os dois primeiros bytes só são carregados num registrador de 24 bits
    (nas posições alta/média), SEM passar pelo laço de 8 deslocamentos
    de CRC — só a partir do terceiro byte em diante que o deslocamento
    de fato acontece. Validado contra 5 pares (entrada, CRC) reais
    conhecidos antes de ser usado aqui.
    """
    lista = [v & 0xFF for v in valores] + [0, 0]
    acumulador = 0
    contador = 0
    for byte in lista:
        deslocamento = (2 - contador) * 8
        mascara = (~(0xFF << deslocamento)) & 0xFFFFFFFF
        acumulador = (acumulador & mascara) | ((byte << deslocamento) & 0xFFFFFFFF)
        acumulador &= 0xFFFFFFFF
        if contador >= 2:
            for _ in range(8):
                acumulador = (acumulador << 1) & 0xFFFFFFFF
                if acumulador & 0x01000000:
                    acumulador ^= 0x800500
                    acumulador &= 0xFFFFFFFF
        else:
            contador += 1
    resultado = (((acumulador >> 16) & 0xFF) << 8) | ((acumulador >> 8) & 0xFF)
    return resultado & 0xFFFF


def montar_comando_autenticar(senha_leitura: str) -> bytes:
    """Comando de autenticação (sub-comando ``[5, 17]`` dentro do ``0xE7``).

    A senha de 6 dígitos tem cada dígito ``'0'`` trocado pelo caractere
    ``'A'`` **antes** de ser dividida em 3 pares e cada par interpretado
    como um byte em hexadecimal — achado real que faltava numa tentativa
    anterior (sem essa troca, a central responde "senha incorreta" mesmo
    com a senha certa). Confirmado contra hardware real.
    """
    if len(senha_leitura) != 6 or not senha_leitura.isdigit():
        raise ValueError("A senha de leitura deve ter exatamente 6 dígitos numéricos")

    senha_convertida = senha_leitura.replace("0", "A")
    pares = [int(senha_convertida[i : i + 2], 16) for i in range(0, 6, 2)]

    corpo = [5, 17] + pares + [52]
    crc = calcular_crc(corpo)
    corpo += [(crc >> 8) & 0xFF, crc & 0xFF]

    frame = [0xE7] + corpo
    frame_sem_checksum = [len(frame)] + frame
    cs = checksum(bytes(frame_sem_checksum))
    return bytes(frame_sem_checksum + [cs])


def montar_comando_leitura(endereco: int, quantidade: int) -> bytes:
    """Comando de leitura de EEPROM (sub-comando ``[4, 18]`` dentro do ``0xE7``)."""
    corpo = [4, 18, (endereco >> 8) & 0xFF, endereco & 0xFF, quantidade & 0xFF]
    crc = calcular_crc(corpo)
    corpo += [(crc >> 8) & 0xFF, crc & 0xFF]
    frame = [0xE7] + corpo
    frame_sem_checksum = [len(frame)] + frame
    cs = checksum(bytes(frame_sem_checksum))
    return bytes(frame_sem_checksum + [cs])


def autenticacao_bem_sucedida(resposta: bytes) -> bool:
    """``True`` se o byte de status da resposta de autenticação for
    ``0x50`` (sucesso, confirmado contra hardware real e contra o app
    oficial). Qualquer outro valor (ex.: ``0x53`` = senha incorreta) é
    tratado como falha.
    """
    return len(resposta) > 3 and resposta[3] == 0x50


def paginas(inicio: int, tamanho_pagina: int, fim: int, ultimo_tamanho: int):
    """Gera os pares (endereço, tamanho) de cada página de leitura,
    reproduzindo a paginação exata usada pelo app oficial."""
    endereco = inicio
    while endereco <= fim:
        tamanho = ultimo_tamanho if endereco == fim else tamanho_pagina
        yield endereco, tamanho
        endereco += tamanho


@dataclass
class NomesLidos:
    zonas: dict[int, str]
    usuarios: dict[int, str]
    bruto_resto: bytes  # receptores/teclados -- ainda sem parsing dedicado


def parse_nomes(dados: bytes) -> NomesLidos:
    """Interpreta o bloco de nomes já concatenado (zonas + usuários +
    receptores/teclados), reproduzindo ``parse_names()`` do script de
    referência que validou este protocolo contra hardware real."""

    def limpar(pedaco: bytes) -> str:
        return pedaco.split(b"\x00")[0].decode("latin1", errors="replace").strip()

    zonas = {}
    for i in range(NAME_TABLE_CAPACITY):
        nome = limpar(dados[i * NAME_RECORD_SIZE : (i + 1) * NAME_RECORD_SIZE])
        if nome:
            zonas[i + 1] = nome

    base_usuarios = NAME_TABLE_CAPACITY * NAME_RECORD_SIZE
    usuarios = {}
    for i in range(NAME_TABLE_CAPACITY):
        inicio = base_usuarios + i * NAME_RECORD_SIZE
        nome = limpar(dados[inicio : inicio + NAME_RECORD_SIZE])
        if nome:
            usuarios[i + 1] = nome

    resto = dados[base_usuarios + NAME_TABLE_CAPACITY * NAME_RECORD_SIZE :]
    return NomesLidos(zonas=zonas, usuarios=usuarios, bruto_resto=resto)


def parse_eventos(dados: bytes) -> list[dict]:
    """Divide o bloco de eventos já concatenado em registros de 8 bytes e
    traduz cada um usando ``protocol.parse_event_record`` (mesmo formato
    de registro já usado pela leitura de eventos via ``0x5C``)."""
    eventos = []
    for i in range(0, len(dados) - len(dados) % EVENT_RECORD_SIZE, EVENT_RECORD_SIZE):
        registro = dados[i : i + EVENT_RECORD_SIZE]
        evento = parse_event_record(registro)
        if evento is not None:
            eventos.append(evento)
    return eventos
