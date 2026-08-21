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
CONF_RECEPTOR_IP_ENABLED = "receptor_ip_enabled"
CONF_RECEPTOR_IP_PORT = "receptor_ip_port"

OPT_POLLING_INTERVAL = "polling_interval"

DEFAULT_PORT = 9009
DEFAULT_POLLING_INTERVAL = 0.25  # segundos, sugerido pela Intelbras/AMT Mobile
MIN_POLLING_INTERVAL = 0.15
MAX_POLLING_INTERVAL = 10.0
DEFAULT_RECEPTOR_IP_ENABLED = False
# Porta diferente da 9009 (usada pela nossa conexão de CLIENTE) de propósito
# — aqui é o oposto, NÓS ficamos escutando e a central se conecta em nós.
# Mesmo valor usado nos scripts de referência testados pelo usuário antes
# desta funcionalidade ser incorporada à integração.
DEFAULT_RECEPTOR_IP_PORT = 9010
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
DEFAULT_CONNECTION_HEALTH_TIMEOUT = 10  # segundos
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
# EEPROM — log de eventos (mesmo comando 0x5C, endereço/tamanho confirmados
# por captura real: 256 registros de 8 bytes, de 0x1800 a 0x2000). Ver
# README_DETALHADO.md para a estrutura de bits de cada registro.
# ---------------------------------------------------------------------------
EVENT_LOG_BASE_ADDRESS = 0x1800
EVENT_LOG_TOTAL_BYTES = 0x800  # 2048 bytes = 256 registros
EVENT_RECORD_LEN = 8
EVENT_LOG_MAX_RECORDS = EVENT_LOG_TOTAL_BYTES // EVENT_RECORD_LEN  # 256
EVENT_LOG_CHUNK_BYTES = 0xC0  # 192 bytes = 24 registros por leitura (mesmo limite do 0x5C)
# Quantos dos eventos mais recentes (já ordenados por data/hora real) ficam
# disponíveis nos atributos da entidade "Últimos eventos" — o serviço de
# leitura sempre devolve TODOS os eventos na resposta, independente deste
# número; só a entidade fica limitada, para não gerar um atributo enorme.
EVENT_ENTITY_RECENT_COUNT = 24

# Modelo -> (limiar mínimo de firmware (major, minor), ou None = qualquer
# firmware) para ter acesso ao comando 0x5C nesse contexto (nomes de
# zona/painel/usuário e leitura de eventos). Extraído literalmente da tela
# de ajuda "Senha Acesso Remoto" do app oficial AMT Mobile — centrais fora
# desta lista (ex.: AMT 1016 NET com qualquer firmware, mesmo que suportada
# pelo resto desta integração) usam um protocolo legado diferente (0xE7,
# não implementado aqui por ser mais arriscado — ver README, seção de
# limitações conhecidas) e por isso não têm nomes de zona nem eventos
# disponíveis nesta integração.
EEPROM_EXTENDED_MIN_FIRMWARE: dict[str, tuple[int, int] | None] = {
    MODEL_2018_EG: (7, 7),
    MODEL_4010_SMART: (3, 2),
    MODEL_1016_NET: (4, 1),
    MODEL_2018_SMART: None,
    MODEL_AMN24_NET: None,
}

# ---------------------------------------------------------------------------
# Receptor IP — tabela completa de códigos de evento (código de 4 dígitos:
# qualificador + código Contact-ID de 3 dígitos -> descrição).
#
# Diferente da tabela usada na leitura de eventos via EEPROM
# (protocol.EVENT_CODE_TABLE, limitada aos 17 bytes brutos já observados
# em captura real), o protocolo Receptor IP transmite o código de 4
# dígitos por extenso, dígito a dígito — então os 67 códigos abaixo já
# são todos diretamente utilizáveis, sem depender de observar cada um
# numa captura real primeiro.
#
# Fonte: tela de configuração de eventos do software oficial "Receptor
# IP" da Intelbras (65-73 registros, ver capturas de tela cruzadas em
# versões anteriores desta documentação), validada de forma independente
# contra o projeto open-source amt2018 (Felipe Magno de Almeida, Boost
# Software License) e dois scripts de referência do usuário desta
# integração, testados em hardware real.
# ---------------------------------------------------------------------------
RECEPTOR_IP_EVENT_TABLE: dict[str, str] = {
    "1100": "Emergência Médica",
    "1110": "Disparo ou pânico de incêndio",
    "1120": "Pânico audível ou silencioso",
    "1121": "Senha de coação",
    "1122": "Pânico silencioso",
    "1130": "Disparo de zona",
    "1131": "Disparo de cerca elétrica",
    "1133": "Disparo de zona 24h",
    "1145": "Tamper do teclado",
    "1146": "Disparo silencioso",
    "1147": "Falha da supervisão Smart/RF",
    "1300": "Sobrecarga na saída auxiliar",
    "1301": "Falha na rede elétrica",
    "1302": "Bateria principal baixa ou em curto-circuito",
    "1305": "Reset pelo modo de programação",
    "1306": "Alteração da programação do painel",
    "1311": "Bateria principal ausente ou invertida",
    "1321": "Corte ou curto-circuito na sirene",
    "1322": "Toque de porteiro",
    "1333": "Problema em teclado ou receptor",
    "1351": "Falha na linha telefônica",
    "1354": "Falha ao comunicar evento",
    "1361": "Falha keep alive ethernet",
    "1371": "Corte da fiação dos sensores",
    "1372": "Curto-circuito na fiação dos sensores",
    "1383": "Tamper do sensor",
    "1384": "Bateria baixa de sensor sem fio",
    "1401": "Desativação pelo usuário",
    "1403": "Auto-desativação",
    "1407": "Desativação via computador ou telefone",
    "1410": "Acesso remoto pelo software de download/upload",
    "1413": "Falha no download",
    "1422": "Acionamento de PGM",
    "1461": "Senha incorreta",
    "1570": "Anulação temporária de zona",
    "1573": "Anulação por disparo",
    "1601": "Teste manual",
    "1602": "Teste periódico",
    "1616": "Solicitação de manutenção",
    "1621": "Reset do buffer de eventos",
    "1624": "Log de eventos cheio",
    "1625": "Data e hora foram reiniciadas",
    "3110": "Restauração de incêndio",
    "3130": "Restauração disparo de zona",
    "3131": "Restauração de disparo de cerca elétrica",
    "3133": "Restauração disparo de zona 24h",
    "3145": "Restauração tamper do teclado",
    "3146": "Restauração disparo silencioso",
    "3147": "Restauração da supervisão Smart/RF",
    "3300": "Restauração sobrecarga na saída auxiliar",
    "3301": "Restauração falha na rede elétrica",
    "3302": "Restauração bat. princ. baixa ou em curto-circuito",
    "3311": "Restauração bat. princ. ausente ou invertida",
    "3321": "Restauração corte ou curto-circuito na sirene",
    "3333": "Restauração problema em teclado ou receptor",
    "3351": "Restauração linha telefônica",
    "3361": "Keep alive ethernet recuperado",
    "3371": "Restauração corte da fiação dos sensores",
    "3372": "Restauração curto-circuito na fiação dos sensores",
    "3383": "Restauração tamper do sensor",
    "3384": "Restauração bateria baixa de sensor sem fio",
    "3401": "Ativação pelo usuário",
    "3403": "Auto-ativação",
    "3407": "Ativação via computador ou telefone",
    "3408": "Ativação por uma tecla",
    "3422": "Desacionamento de PGM",
    "3456": "Ativação parcial",
}

# ---------------------------------------------------------------------------
# Entidades / plataformas
# ---------------------------------------------------------------------------
SIGNAL_STATUS_UPDATE = f"{DOMAIN}_status_update"
