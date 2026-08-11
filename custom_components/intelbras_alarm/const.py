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
CONF_ENABLED_ZONES = "enabled_zones"

OPT_POLLING_INTERVAL = "polling_interval"

DEFAULT_PORT = 9009
DEFAULT_POLLING_INTERVAL = 0.25  # segundos, sugerido pela Intelbras/AMT Mobile
MIN_POLLING_INTERVAL = 0.15
MAX_POLLING_INTERVAL = 10.0
# Timeout POR TENTATIVA (conectar OU esperar resposta a UM comando/consulta
# já na conexão estabelecida). Antes desta revisão, os 8s do item 5 da
# documentação ISECNet eram usados aqui — mas esse valor foi pensado para
# um cenário de conexão nova a cada requisição (como no fluxo Node-RED
# original), não para uma conexão persistente já aberta, onde a central
# deveria responder bem mais rápido. Um timeout de 8s por TENTATIVA fazia
# o usuário esperar até 8s por feedback de um único comando, e a
# reconexão em caso de queda real também demorava até 8s por tentativa.
DEFAULT_REQUEST_TIMEOUT = 3  # segundos
# Timeout de TOLERÂNCIA ACUMULADA: usado só pela consulta de status
# (nunca por comandos reais, que sempre falham rápido e visivelmente — ver
# coordinator.py). Se uma consulta de status isolada falhar mas o tempo
# desde a última consulta bem-sucedida ainda estiver dentro deste limite,
# a falha é tolerada silenciosamente (fica só um aviso no log; as
# entidades continuam "disponíveis", mostrando o último dado bom
# conhecido) — evita marcar tudo como indisponível por causa de um único
# soluço passageiro da central (ex.: o bug do firmware 6.2 documentado no
# README). Só depois que o silêncio ultrapassa este limite é que a falha
# vira uma indisponibilidade de verdade.
DEFAULT_CONNECTION_HEALTH_TIMEOUT = 8  # segundos
DEFAULT_CODE_REQUIRED_ARM = False
DEFAULT_CODE_REQUIRED_DISARM = False
# Formato: intervalos e/ou números individuais separados por ponto e
# vírgula, ex.: "1-8;17-24" ou "1-5;8;10-15". Ver ZONE_SPEC_FORMAT_HELP
# (usado no rótulo do campo, no config_flow e no serviço bypass_zone).
DEFAULT_ENABLED_ZONES_SPEC = "1-8;17-24"
ZONE_SPEC_FORMAT_HELP = "Formato: intervalos e/ou números separados por ; (ex.: 1-5;8;10-15)"

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

# model_byte -> (chave do modelo, nome amigável, família, nº de zonas
# criadas como entidade, nº de partições). Confirmado com o usuário: o nº
# de zonas segue o limite do protocolo por família (48 na 2018/1016, 64 na
# 4010 — igual ao fluxo Node-RED original e à documentação), não uma
# estimativa por modelo específico. Só as primeiras 16 nascem habilitadas
# por padrão no Home Assistant (ver ZONE_ENABLED_BY_DEFAULT_COUNT); as
# demais são criadas desabilitadas, para o usuário ativar as que usar.
MODEL_TABLE: dict[int, tuple[str, str, str, int, int]] = {
    0x1E: (MODEL_2018_EG, "AMT 2018 E/EG", FAMILY_2018, 48, 2),
    0x61: (MODEL_1016_NET, "AMT 1016 NET", FAMILY_2018, 48, 2),
    0x24: (MODEL_AMN24_NET, "AMN 24 NET", FAMILY_2018, 48, 2),
    0x34: (MODEL_2018_SMART, "AMT 2018 E SMART", FAMILY_2018, 48, 2),
    0x41: (MODEL_4010_SMART, "AMT 4010 SMART", FAMILY_4010, 64, 4),
}

# chave do modelo -> nº de zonas a criar como entidade (deriva de
# MODEL_TABLE para manter uma única fonte de verdade)
MODEL_ZONE_COUNT: dict[str, int] = {row[0]: row[3] for row in MODEL_TABLE.values()}

# Nº de zonas iniciais (1..N) que nascem habilitadas por padrão no registro
# de entidades do Home Assistant — as demais (até o total de
# MODEL_ZONE_COUNT) são criadas desabilitadas. Configurável pelo usuário na
# inclusão da integração (CONF_ENABLED_ZONES); DEFAULT_ENABLED_ZONES_SPEC é
# usado se o campo for deixado em branco.
class InvalidZoneSpec(ValueError):
    """Formato de intervalo/lista de zonas inválido (ver ZONE_SPEC_FORMAT_HELP)."""


def parse_zone_spec(spec: str, max_zone: int = 64) -> set[int]:
    """Converte ``"1-5;8;10-15"`` em ``{1,2,3,4,5,8,10,11,12,13,14,15}``.

    Aceita intervalos (``a-b``) e números individuais, separados por ``;``.
    Espaços em torno dos números/intervalos são ignorados. Levanta
    ``InvalidZoneSpec`` para qualquer formato ou valor fora de 1..max_zone.
    """
    zones: set[int] = set()
    spec = spec.strip()
    if not spec:
        return zones
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2:
                raise InvalidZoneSpec(f"Intervalo inválido: {part!r}")
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError as err:
                raise InvalidZoneSpec(f"Intervalo inválido: {part!r}") from err
            if start > end:
                start, end = end, start
            zones.update(range(start, end + 1))
        else:
            try:
                zones.add(int(part))
            except ValueError as err:
                raise InvalidZoneSpec(f"Número de zona inválido: {part!r}") from err
    if zones and (min(zones) < 1 or max(zones) > max_zone):
        raise InvalidZoneSpec(f"Zonas devem estar entre 1 e {max_zone}")
    return zones

# Modelos cujo comando de ativação em modo Stay (0x50) é suportado de
# verdade pela central — confirmado pelo usuário: só a família 4010 e a
# variante "SMART" da 2018 respondem corretamente a esse comando; nas
# demais (2018 E/EG, 1016 NET, AMN 24 NET) o comando existe no protocolo
# mas a central não implementa esse modo de fato.
MODELS_SUPPORTING_STAY = {MODEL_4010_SMART, MODEL_2018_SMART}

# Nº máximo de zonas cobertas pelos bytes de status de cada família (limite
# do protocolo — ver MODEL_ZONE_COUNT para o nº de entidades por modelo,
# que hoje coincide com este valor para todos os modelos suportados)
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
