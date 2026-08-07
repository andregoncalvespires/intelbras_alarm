"""Constantes da integração Intelbras Alarm (protocolo ISECNet / ISECMobile)."""
from __future__ import annotations

DOMAIN = "intelbras_alarm"
MANUFACTURER = "Intelbras"

# ---------------------------------------------------------------------------
# Configuração / opções
# ---------------------------------------------------------------------------
CONF_PASSWORD = "password"
CONF_MODEL = "model"
CONF_PARTITIONS = "partitions"
CONF_PARTITION_PASSWORDS = "partition_passwords"
CONF_ZONE_COUNT = "zone_count"
CONF_PGM_COUNT = "pgm_count"
CONF_CODE_REQUIRED_ARM = "code_required_arm"
CONF_CODE_REQUIRED_DISARM = "code_required_disarm"

OPT_POLLING_INTERVAL = "polling_interval"

DEFAULT_PORT = 9009
DEFAULT_POLLING_INTERVAL = 0.25  # segundos, sugerido pela Intelbras/AMT Mobile
MIN_POLLING_INTERVAL = 0.15
MAX_POLLING_INTERVAL = 10.0
DEFAULT_TIMEOUT_ETHERNET = 8  # segundos, conforme item 5 da documentação ISECNet
DEFAULT_CODE_REQUIRED_ARM = False
DEFAULT_CODE_REQUIRED_DISARM = False

# ---------------------------------------------------------------------------
# Comandos do protocolo ISECMobile (campo <Comando> dentro do frame 0x21..0x21)
# ---------------------------------------------------------------------------
CMD_ARM = 0x41  # Ativação da central
CMD_BYPASS = 0x42  # Bypass / Anulação de zonas
CMD_SIREN_ON = 0x43  # Liga sirene
CMD_DISARM = 0x44  # Desativação da central
CMD_PANIC = 0x45  # Pânico
CMD_PGM = 0x50  # Controle de PGM
CMD_STATUS_PARTIAL = 0x5A  # Solicitação parcial de status (AMT 2018 / 1016 / SMART)
CMD_STATUS_FULL = 0x5B  # Solicitação completa de status (AMT 4010)
CMD_EEPROM_READ = 0x5C  # Leitura de n bytes da EEPROM
CMD_SIREN_OFF = 0x63  # Desliga sirene

# Sub-comandos de partição usados nos comandos 0x41/0x44
PARTITION_ALL = None
PARTITION_A = 0x41
PARTITION_B = 0x42
PARTITION_C = 0x43
PARTITION_D = 0x44
PARTITION_STAY = 0x50  # Ativação em modo Stay (somente disponível ao ativar)

PARTITION_CODES = {"A": PARTITION_A, "B": PARTITION_B, "C": PARTITION_C, "D": PARTITION_D}

# Sub-comandos do comando 0x50 (PGM)
PGM_ON = 0x4C
PGM_OFF = 0x44

# Valores do comando 0x45 (Pânico)
PANIC_SILENT = 0x00
PANIC_AUDIBLE = 0x01
PANIC_MEDICAL = 0x02
PANIC_FIRE = 0x03

# ---------------------------------------------------------------------------
# Respostas ACK / NACK (frame curto, campo <Conteúdo> = 1 byte)
# ---------------------------------------------------------------------------
ACK_OK = 0xFE
NACK_MESSAGES = {
    0xE0: "Formato de pacote inválido",
    0xE1: "Senha incorreta",
    0xE2: "Comando inválido",
    0xE3: "Central não particionada",
    0xE4: "Zonas abertas",
    0xE5: "Comando descontinuado",
    0xE6: "Usuário sem permissão para bypass",
    0xE7: "Usuário sem permissão para desativar",
    0xE8: "Bypass não permitido com a central ativada",
    0xEA: "Partição sem zonas habilitadas",
}

# ---------------------------------------------------------------------------
# Famílias / modelos de central.
#
# O byte de modelo é lido do status da central (Status19 no comando 0x5A,
# Status25 no comando 0x5B). Os valores 0x1E e 0x41 são os únicos descritos
# na documentação oficial ISECNet R15; os demais (0x61, 0x24, 0x34) foram
# confirmados em campo (fluxo Node-RED original) e são mantidos por
# compatibilidade, claramente identificados como extensão não documentada.
# ---------------------------------------------------------------------------
FAMILY_2018 = "2018"  # usa comando 0x5A, status de 43 bytes, até 48 zonas
FAMILY_4010 = "4010"  # usa comando 0x5B, status de até 54 bytes, até 64 zonas

MODEL_2018_EG = "amt_2018_eg"
MODEL_1016_NET = "amt_1016_net"
MODEL_AMN24_NET = "amn_24_net"
MODEL_2018_SMART = "amt_2018_smart"
MODEL_4010_SMART = "amt_4010_smart"
MODEL_UNKNOWN = "unknown"

# model_byte -> (chave do modelo, nome amigável, família, nº de zonas nativo
# do modelo — usado para limitar quantas entidades de zona são criadas —,
# nº de partições). Os números de zona seguem as especificações de produto
# publicadas pela Intelbras para cada central; o array de bits do protocolo
# suporta mais zonas do que algumas centrais fisicamente oferecem (ver
# FAMILY_MAX_ZONES), por isso os dois valores são mantidos separados.
MODEL_TABLE: dict[int, tuple[str, str, str, int, int]] = {
    0x1E: (MODEL_2018_EG, "AMT 2018 E/EG", FAMILY_2018, 18, 2),
    0x61: (MODEL_1016_NET, "AMT 1016 NET", FAMILY_2018, 16, 2),
    0x24: (MODEL_AMN24_NET, "AMN 24 NET", FAMILY_2018, 24, 2),
    0x34: (MODEL_2018_SMART, "AMT 2018 E SMART", FAMILY_2018, 18, 2),
    0x41: (MODEL_4010_SMART, "AMT 4010 SMART", FAMILY_4010, 64, 4),
}

# chave do modelo -> nº de zonas nativo (usado para criar as entidades de
# zona; deriva de MODEL_TABLE para manter uma única fonte de verdade)
MODEL_ZONE_COUNT: dict[str, int] = {row[0]: row[3] for row in MODEL_TABLE.values()}

# Nº máximo de zonas cobertas pelos bytes de status de cada família (limite
# do protocolo, não do modelo — ver MODEL_ZONE_COUNT para o nº de entidades)
FAMILY_MAX_ZONES = {FAMILY_2018: 48, FAMILY_4010: 64}
FAMILY_STATUS_CMD = {FAMILY_2018: CMD_STATUS_PARTIAL, FAMILY_4010: CMD_STATUS_FULL}
FAMILY_STATUS_LEN = {FAMILY_2018: 43, FAMILY_4010: 54}

# Nº de PGMs suportadas com leitura de status real (ver protocol.py):
# família 2018/1016 só reporta PGM1/PGM2 no status; a família 4010 reporta
# PGM1-PGM3 no status principal e PGM4-PGM19 via expansores (Status53/54).
FAMILY_PGM_COUNT = {FAMILY_2018: 2, FAMILY_4010: 19}

# Endereços do comando 0x50 para PGM 1..19 (31..43 em hexadecimal, doc 7.3)
PGM_ADDRESSES = {i: 0x30 + i for i in range(1, 20)}  # PGM1=0x31 ... PGM19=0x43

# ---------------------------------------------------------------------------
# EEPROM — nomes de zona (somente família 4010, confirmado por captura real)
# ---------------------------------------------------------------------------
ZONE_NAME_BASE_ADDRESS = 0x0800
ZONE_NAME_RECORD_LEN = 16
ZONE_NAME_MAX_READ = 0xC0  # 192 bytes = 12 zonas por leitura (limite do comando 0x5C)

# ---------------------------------------------------------------------------
# Entidades / plataformas
# ---------------------------------------------------------------------------
SIGNAL_STATUS_UPDATE = f"{DOMAIN}_status_update"
