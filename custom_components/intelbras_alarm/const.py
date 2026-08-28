"""Constantes da integração Intelbras Alarm (protocolo ISECNet / ISECMobile)."""
from __future__ import annotations

DOMAIN = "intelbras_alarm"
MANUFACTURER = "Intelbras"

# ---------------------------------------------------------------------------
# AMT 8000 — protocolo próprio (autenticado), completamente diferente do
# ISECMobile/ISECNet usado pelos demais modelos (ver protocol_amt8000.py).
#
# EXPERIMENTAL / EM DESENVOLVIMENTO: toda esta seção foi obtida por
# engenharia reversa do app oficial AMT Remoto (androguard, v3.4.2.2),
# validada com uma implementação de terceiros conhecida (fluxo Node-RED
# testado em campo pelo usuário em firmware 2.1.5), mas AINDA NÃO
# confirmada por captura de tráfego própria contra uma central AMT 8000
# real. Ver README_DETALHADO.md, seção "AMT 8000 (experimental)", para o
# que já foi validado e o que ainda depende de teste em campo.
# ---------------------------------------------------------------------------
FAMILY_8000 = "8000"
MODEL_AMT_8000 = "amt_8000"
AMT_8000_MODEL_NAME = "AMT 8000"

# Par fixo observado em toda transação (autenticação e comandos) — provável
# identificador de versão do protocolo. Nunca visto com outro valor.
AMT8000_SRC_ID = (0x00, 0x01)

# Opcodes (2 bytes cada), extraídos de ProtocoloServidorAmt8000 e
# Amt8000.class do app oficial — ver README_DETALHADO.md para o
# significado de cada um e a fonte exata.
AMT8000_CMD_AUTH = (0xF0, 0xF0)
AMT8000_CMD_STATUS = (0x0B, 0x4A)
AMT8000_CMD_ARM_DISARM = (0x40, 0x1E)
AMT8000_CMD_BYPASS = (0x40, 0x1F)
AMT8000_CMD_PANIC = (0x40, 0x1A)
AMT8000_CMD_PGM = (0x45, 0xAF)
AMT8000_CMD_EVENT_BUFFER_INDEX = (0x30, 0x03)
AMT8000_CMD_READ_EVENTS = (0x39, 0x00)
AMT8000_CMD_PHOTO_REQUEST = (0x0B, 0xB0)
AMT8000_CMD_DISCONNECT = (0xF0, 0xF1)
AMT8000_CMD_SYNC_NOME_CENTRAL = (0x31, 0xE0)
AMT8000_CMD_SYNC_USUARIO = (0x32, 0xE0)
AMT8000_CMD_SYNC_ZONA = (0x33, 0xE0)
AMT8000_CMD_SYNC_PARTICAO = (0x34, 0xE0)
AMT8000_CMD_SYNC_PGM = (0x35, 0xE0)
AMT8000_CMD_SYNC_TECLADO = (0x36, 0xE0)
AMT8000_CMD_SYNC_SIRENE = (0x38, 0xE0)
AMT8000_CMD_WRITE_MESSAGE = (0x21, 0xF1)  # escrita individual de nome (não usado ainda)

# Valores do "modo" no conteúdo de AMT8000_CMD_ARM_DISARM — deduzidos da
# convenção do fluxo de referência (0=desarmar, 1=armar, 2=stay), AINDA
# NÃO confirmados byte a byte contra uma captura real desta central.
AMT8000_MODE_DISARM = 0x00
AMT8000_MODE_ARM = 0x01
AMT8000_MODE_STAY = 0x02

AMT8000_ZONE_COUNT = 64
AMT8000_PARTITION_COUNT = 16
AMT8000_ALL_PARTITIONS = 0xFF  # valor pra "central inteira" no comando de
# arme/desarme (0x401E) -- corrigido de 0 (herdado sem confirmação do fluxo
# Node-RED de referência) para 0xFF, confirmado em hardware real pelo
# projeto de terceiros fdaneluzzi/homeassistant-amt8000 (ALL_PARTITIONS).
# Ver CHANGELOG.md e a comparação com esse repositório.
AMT8000_PGM_COUNT = 16
AMT8000_EVENT_BUFFER_SIZE = 512  # posições do buffer circular (mapa de EEPROM)
AMT8000_EVENT_READ_BATCH = 16  # nº de eventos lidos por chamada de AMT8000_CMD_READ_EVENTS
AMT8000_STATUS_MAX_LEN = 143  # bytes do CONTEÚDO do status (só payload, já
# sem cabeçalho/opcode/checksum -- parse_frame() já retira isso em
# ParsedFrameAmt8000.content). Corrigido de 152 (que na verdade era o
# tamanho do FRAME TOTAL, incluindo os 9 bytes de framing) para 143,
# confirmado em hardware real pelo projeto de terceiros
# fdaneluzzi/homeassistant-amt8000 -- é isso que response.content mede,
# então é contra isso que a checagem de tamanho deve comparar.

# Diretório dentro de /media onde as fotos de eventos são salvas (entidade
# camera) — ver decisão de arquitetura registrada no histórico do projeto.
AMT8000_MEDIA_SUBDIR = "amt8000"

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
CONF_LEGACY_EEPROM_PASSWORD = "legacy_eeprom_password"  # opcional, 6
# dígitos -- "Senha de leitura de mensagens"/"Senha Acesso Remoto" do
# app oficial. Habilita nomes de zona/usuário e leitura de eventos via
# protocolo legado (0xE7) nos modelos/firmwares que não alcançam o
# limiar do comando moderno 0x5C (ver supports_extended_eeprom). Em
# branco por padrão -- só é usado se o usuário preencher explicitamente.

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
CMD_STATUS_ESMART = 0x5D  # Solicitação de status da AMT 2018 E SMART/AMT 1000
# Smart -- comando diferente do resto da família 2018, mas mesmos offsets
# de byte para tudo que esta integração usa (ver MODEL_TABLE e
# MODEL_STATUS_CMD_OVERRIDE abaixo, e README_DETALHADO.md).
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
# na documentação oficial ISECNet R15; 0x61 e 0x24 foram confirmados em
# campo (fluxo Node-RED original). Os demais bytes (0x04, 0x08, 0x10, 0x18,
# 0x20, 0x25, 0x2E, 0x30, 0x32) vêm de engenharia reversa direta do app
# oficial (`PanelModelId`, classe `Amt2018`) — nunca testados contra
# hardware real, mas com alta confiança: são literalmente a mesma classe
# Java já usada (e validada) para 0x1E/0x61/0x24, sem nenhuma ramificação
# de comportamento por modelo específico dentro dela.
# ---------------------------------------------------------------------------
FAMILY_2018 = "2018"  # usa comando 0x5A, status de 43 bytes, até 48 zonas
FAMILY_4010 = "4010"  # usa comando 0x5B, status de até 54 bytes, até 64 zonas

# ---------------------------------------------------------------------------
# Tensão da fonte/bateria — comando 0xE7, sub-comando [1, 0x17] (achado e
# confirmado pelo usuário contra hardware real, nos dois modelos abaixo —
# mesmo protocolo/CRC/checksum já validados do restante do 0xE7, só um
# sub-comando novo). Formato da resposta varia por família (igual o
# status normal 0x5A/0x5B varia) — daí os offsets diferentes.
#
# fórmula: tensão = (byte[N]*256 + byte[N+1]) / 67.0, resultado em Volts.
#
# AMT 1016 NET (família 2018): fonte=content[18:20], bateria=content[20:22]
#   — confirmado com central real, firmware 3.1 (14.49V / 13.66V batendo
#   exatamente com o valor mostrado pela central).
# AMT 4010 SMART (família 4010): fonte=content[23:25], bateria=content[25:27]
#   — fonte confirmada com central real, firmware 5.2 (13.58V). Bateria
#   confirmada por eliminação: a central testada estava genuinamente sem
#   bateria conectada (0.00V bate com a realidade, não é um zero de
#   preenchimento não utilizado).
#
# Não se aplica à ANM 24 Net (protocolo próprio via 0xF1, nunca testado
# com este comando) nem à AMT 8000 (protocolo totalmente diferente).
VOLTAGE_DIVISOR = 67.0
VOLTAGE_OFFSETS: dict[str, tuple[int, int]] = {
    FAMILY_2018: (18, 20),
    FAMILY_4010: (22, 24),
}

MODEL_2018_EG = "amt_2018_eg"
MODEL_1016_NET = "amt_1016_net"
MODEL_ANM24_NET = "anm_24_net"
MODEL_2018_SMART = "amt_2018_smart"
MODEL_4010_SMART = "amt_4010_smart"
MODEL_2008_RF = "amt_2008_rf"
MODEL_2010 = "amt_2010"
MODEL_2018_BASE = "amt_2018"
MODEL_2110 = "amt_2110"
MODEL_2118_EG = "amt_2118_eg"
MODEL_3010 = "amt_3010"
MODEL_2018_E3G = "amt_2018_e3g"
MODEL_GPRS_1000_UN = "gprs_1000_un"
MODEL_UNKNOWN = "unknown"

# model_byte -> (chave do modelo, nome amigável, família, nº de zonas
# criadas como entidade, nº de partições). Confirmado com o usuário: o nº
# de zonas segue o limite do protocolo por família (48 na 2018/1016, 64 na
# 4010 — igual ao fluxo Node-RED original e à documentação), não uma
# estimativa por modelo específico. Só as primeiras 16 nascem habilitadas
# por padrão no Home Assistant (ver ZONE_ENABLED_BY_DEFAULT_COUNT); as
# demais são criadas desabilitadas, para o usuário ativar as que usar.
#
# "AMT 2018 E SMART" (byte 0x34) — uma análise inicial concluiu que esse
# modelo era incompatível (comando de status próprio 0x5D, resposta de
# mais de 135 bytes — parecia um layout completamente diferente) e chegou
# a remover o suporte. Uma segunda análise, mais cuidadosa, comparou
# posição por posição os campos que `Amt2018ESmart.
# updateStatusAttributes()` (app oficial, decompilado) realmente lê
# contra os offsets que esta integração usa — e todos batem exatamente
# (firmware, particionamento, partições A/B, sirene, falta de rede
# elétrica). O conteúdo extra (Stay por partição, status de rede geral)
# é estritamente adicional, não um layout diferente. Por isso: mesmo
# `parse_status_2018()`, mesmas 48 zonas — só o comando muda (ver
# MODEL_STATUS_CMD_OVERRIDE) e a validação de tamanho passa a aceitar
# qualquer tamanho >= 43 para este modelo (ver
# MODEL_STATUS_MIN_LEN_OVERRIDE). Ainda não testado contra hardware
# real. Ver README_DETALHADO.md e CHANGELOG.md para os detalhes.
#
# Os 8 bytes abaixo (2008 RF, 2010, 2018 base, 2110, 2118 EG, 3010, E3G,
# GPRS 1000 UN) foram adicionados a partir da mesma engenharia reversa:
# confirmado que a classe `Amt2018` do app oficial trata todos eles de
# forma IDÊNTICA, sem nenhuma ramificação por modelo específico (mesmo
# comando 0x5A, mesmas 48 zonas, mesmos offsets de byte, hardcoded) — o
# mesmo código-fonte já usado para AMT 2018 E/EG e AMT 1016 NET. Nenhum
# desses 8 foi testado contra hardware real; a confiança vem de serem
# literalmente a mesma classe Java, não de inferência por semelhança.
MODEL_TABLE: dict[int, tuple[str, str, str, int, int]] = {
    0x1E: (MODEL_2018_EG, "AMT 2018 E/EG", FAMILY_2018, 48, 2),
    0x61: (MODEL_1016_NET, "AMT 1016 NET", FAMILY_2018, 48, 2),
    0x24: (MODEL_ANM24_NET, "ANM 24 Net", FAMILY_2018, 48, 2),
    0x25: (MODEL_ANM24_NET, "ANM 24 Net", FAMILY_2018, 48, 2),  # variante G2, mesma classe/nome no app oficial
    0x34: (MODEL_2018_SMART, "AMT 2018 E SMART", FAMILY_2018, 48, 2),
    0x41: (MODEL_4010_SMART, "AMT 4010 SMART", FAMILY_4010, 64, 4),
    0x04: (MODEL_GPRS_1000_UN, "GPRS 1000 UN", FAMILY_2018, 48, 2),
    0x08: (MODEL_2008_RF, "AMT 2008 RF", FAMILY_2018, 48, 2),
    0x10: (MODEL_2010, "AMT 2010", FAMILY_2018, 48, 2),
    0x18: (MODEL_2018_BASE, "AMT 2018", FAMILY_2018, 48, 2),
    0x20: (MODEL_2110, "AMT 2110", FAMILY_2018, 48, 2),
    0x2E: (MODEL_2118_EG, "AMT 2118 EG", FAMILY_2018, 48, 2),
    0x30: (MODEL_3010, "AMT 3010", FAMILY_2018, 48, 2),
    0x32: (MODEL_2018_E3G, "AMT 2018 E3G", FAMILY_2018, 48, 2),
}

# Modelos cujo comando de status difere do padrão da família (ver
# CMD_STATUS_ESMART acima) — checado ANTES de FAMILY_STATUS_CMD.
MODEL_STATUS_CMD_OVERRIDE: dict[str, int] = {
    MODEL_2018_SMART: CMD_STATUS_ESMART,
}

# Modelos cuja resposta de status tem tamanho VARIÁVEL/maior que o padrão
# da família — checado ANTES de FAMILY_STATUS_LEN. Valor = tamanho MÍNIMO
# aceito (não exato): resposta com pelo menos esse tanto de bytes é
# considerada válida, mesmo que venha maior. Só a AMT 2018 E SMART tem
# essa particularidade hoje (43 = mesmo limite da família 2018 padrão,
# suficiente para cobrir tudo que este comando lê).
MODEL_STATUS_MIN_LEN_OVERRIDE: dict[str, int] = {
    MODEL_2018_SMART: 43,
}

# chave do modelo -> nº de zonas a criar como entidade (deriva de
# MODEL_TABLE para manter uma única fonte de verdade)
MODEL_ZONE_COUNT: dict[str, int] = {row[0]: row[3] for row in MODEL_TABLE.values()}
MODEL_ZONE_COUNT[MODEL_AMT_8000] = AMT8000_ZONE_COUNT

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
# verdade pela central — confirmado pelo usuário: a família 4010 e a
# AMT 2018 E SMART respondem corretamente a esse comando; nas demais
# (2018 E/EG, 1016 NET, ANM 24 Net e os demais bytes da tabela) o comando
# existe no protocolo mas a central não implementa esse modo de fato.
# A AMT 8000 (protocolo próprio) também suporta Stay, ver protocol_amt8000.py.
MODELS_SUPPORTING_STAY = {MODEL_4010_SMART, MODEL_2018_SMART, MODEL_AMT_8000}

# Nº máximo de zonas cobertas pelos bytes de status de cada família (limite
# do protocolo — ver MODEL_ZONE_COUNT para o nº de entidades por modelo,
# que hoje coincide com este valor para todos os modelos suportados)
# Não se aplica à AMT 8000 (FAMILY_8000, protocolo totalmente diferente).
FAMILY_MAX_ZONES = {FAMILY_2018: 48, FAMILY_4010: 64, FAMILY_8000: AMT8000_ZONE_COUNT}
FAMILY_STATUS_CMD = {FAMILY_2018: CMD_STATUS_PARTIAL, FAMILY_4010: CMD_STATUS_FULL}
FAMILY_STATUS_LEN = {FAMILY_2018: 43, FAMILY_4010: 54}

# Nº de PGMs suportadas com leitura de status real (ver protocol.py):
# família 2018/1016 só reporta PGM1/PGM2 no status; a família 4010 reporta
# PGM1-PGM3 no status principal e PGM4-PGM19 via expansores (Status53/54).
# A AMT 8000 reporta só PGM1-PGM3 no blob de status (ver protocol_amt8000.py)
FAMILY_PGM_COUNT = {FAMILY_2018: 2, FAMILY_4010: 19, FAMILY_8000: AMT8000_PGM_COUNT}

# Endereços do comando 0x50 para PGM 1..19 (31..43 em hexadecimal, doc 7.3)
PGM_ADDRESSES = {i: 0x30 + i for i in range(1, 20)}  # PGM1=0x31 ... PGM19=0x43

# ---------------------------------------------------------------------------
# EEPROM — nomes de zona (somente família 4010, confirmado por captura real)
# ---------------------------------------------------------------------------
ZONE_NAME_BASE_ADDRESS = 0x0800
ZONE_NAME_RECORD_LEN = 16
ZONE_NAME_MAX_READ = 0xC0  # 192 bytes = 12 zonas por leitura (limite do comando 0x5C)

# Nomes de usuário (comando 0x5C) — endereço vem logo depois da última
# zona possível do modelo (ZONE_NAME_BASE_ADDRESS + max_zones do modelo *
# ZONE_NAME_RECORD_LEN — calculado em tempo de execução pelo coordinator,
# já que depende da família). Capacidade fixa de 64 usuários, igual ao
# protocolo legado (`protocol_legacy_eeprom.NAME_TABLE_CAPACITY`) —
# confirmado batendo com o que apareceu numa leitura real de EEPROM de
# uma AMT 4010 SMART (usuários nomeados até o índice 61, dentro do
# limite de 64).
USER_NAME_RECORD_LEN = 16
USER_NAME_TABLE_CAPACITY = 64

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
# de ajuda "Senha Acesso Remoto" do app oficial AMT Mobile, confirmado
# byte a byte decompilando `Painel.isPanelUsing5c()` — centrais fora
# desta lista (ex.: AMT 1016 NET com firmware abaixo do limiar) usam um
# protocolo legado diferente (0xE7 + senha de leitura de mensagens,
# opcional — ver `protocol_legacy_eeprom.py` e
# `coordinator.supports_legacy_eeprom`) para ter acesso a essas mesmas
# duas funções.
EEPROM_EXTENDED_MIN_FIRMWARE: dict[str, tuple[int, int] | None] = {
    MODEL_2018_EG: (7, 7),
    MODEL_4010_SMART: (3, 2),
    MODEL_1016_NET: (4, 1),
    MODEL_2018_SMART: None,
    MODEL_ANM24_NET: None,
}

# ---------------------------------------------------------------------------
# Receptor IP — tabela completa de códigos de evento (código de 4 dígitos:
# qualificador + código Contact-ID de 3 dígitos -> descrição).
#
# Diferente da tabela usada na leitura de eventos via EEPROM
# (protocol.EVENT_CODE_TABLE, limitada aos bytes brutos já observados em
# captura real), o protocolo Receptor IP transmite o código de 4 dígitos
# por extenso, dígito a dígito — então os 132 códigos abaixo já são todos
# diretamente utilizáveis, sem depender de observar cada um numa captura
# real primeiro.
#
# Fonte: arquivo de referência de 132 códigos fornecido pelo usuário
# (contém também o campo "type" por código — ZONE/USER/USER_PARTITION/
# PGM/SYSTEM/BUS_DEVICE — usado para montar RECEPTOR_IP_EVENT_SUBJECT
# logo abaixo). Substituiu uma tabela anterior de 68 códigos (tela de
# configuração de eventos do software oficial "Receptor IP" da
# Intelbras) — os 68 códigos antigos continuam todos presentes aqui,
# com a descrição atualizada quando o arquivo novo trouxe uma redação
# diferente (ou, em 1333/3333, um significado diferente — ver
# CHANGELOG.md).
# ---------------------------------------------------------------------------
RECEPTOR_IP_EVENT_TABLE: dict[str, str] = {
    "1100": "Emergência médica",
    "1110": "Disparo ou pânico de incêndio",
    "1120": "Pânico audível",
    "1121": "Senha de coação",
    "1122": "Pânico silencioso",
    "1130": "Disparo",
    "1131": "Disparo de cerca elétrica",
    "1133": "Disparo 24h",
    "1134": "Alarme porta aberta",
    "1145": "Tamper",
    "1146": "Disparo silencioso",
    "1147": "Falha da supervisão RF",
    "1164": "Disparo por inatividade",
    "1256": "Desconexão do cliente",
    "1300": "Sobrecarga na saída auxiliar",
    "1301": "Falha na rede elétrica",
    "1302": "Bateria principal baixa ou em curto-circuito",
    "1305": "Reset pelo modo de programação",
    "1306": "Alteração da programação do painel",
    "1311": "Bateria principal ausente ou invertida",
    "1321": "Corte ou curto-circuito na sirene",
    "1322": "Toque de porteiro",
    "1333": "Falha dispositivo de barramento",
    "1342": "Falha rede elétrica",
    "1351": "Falha na linha telefônica",
    "1354": "Falha ao comunicar eventos",
    "1360": "Falha keep alive GPRS",
    "1361": "Falha keep alive ethernet",
    "1371": "Corte na fiação do sensor",
    "1372": "Curto-circuito na fiação do sensor",
    "1383": "Tamper",
    "1384": "Bateria baixa",
    "1401": "Desativado por",
    "1403": "Auto desativação",
    "1407": "Desativado via APP",
    "1408": "1 408",
    "1409": "Desativado via controle remoto",
    "1410": "Acesso remoto para leitura de eventos ou configurações",
    "1412": "1 412",
    "1413": "Falha no download",
    "1414": "1 414",
    "1415": "Desativado via entrada liga",
    "1416": "Sucesso atualização firmware",
    "1417": "Falha atualização firmware",
    "1418": "1 418",
    "1419": "Desativado via Alexa",
    "1420": "1420",
    "1422": "Acionamento",
    "1435": "Acionamento via Alexa",
    "1456": "1 456",
    "1461": "Senha incorreta",
    "1531": "1 531",
    "1533": "Dispositivo RF cadastrado",
    "1534": "Senha cadastrada/alterada",
    "1535": "Zona habilitada",
    "1570": "Anulação temporária",
    "1573": "Anulação por disparo",
    "1578": "Anulação temporária via Alexa",
    "1601": "Teste manual",
    "1602": "Teste periódico",
    "1616": "Solicitação de manutenção",
    "1621": "Reset de buffer de eventos",
    "1624": "Log de eventos cheio",
    "1625": "Data e hora foram reiniciadas",
    "1998": "Desconexão cliente cloud",
    "1999": "Desconexão cliente OFF LINE falha de KEEP ALIVE",
    "3100": "Restauração emergência médica",
    "3110": "Restauração do disparo ou pânico de incêndio",
    "3120": "Restauração pânico audível",
    "3121": "Restauração senha coação",
    "3122": "Restauração pânico silencioso",
    "3130": "Restauração disparo",
    "3131": "Restauração disparo de cerca elétrica",
    "3133": "Restauração disparo 24h",
    "3134": "Restauração alarme porta aberta",
    "3145": "Restauração do tamper",
    "3146": "Restauração de disparo Silencioso",
    "3147": "Restauração da supervisão RF",
    "3164": "3164",
    "3256": "Restauração da conexão do cliente",
    "3300": "Saída auxiliar restaurada",
    "3301": "Rede elétrica presente",
    "3302": "Bateria principal restaurada",
    "3305": "3 305",
    "3306": "3 306",
    "3311": "Bateria principal presente",
    "3321": "Sirene recuperada",
    "3322": "3 322",
    "3333": "Dispositivo do barramento recuperado",
    "3342": "Rede elétrica presente",
    "3351": "Linha telefônica presente",
    "3354": "3 354",
    "3360": "Keep alive GPRS recuperado",
    "3361": "Keep alive ethernet recuperado",
    "3371": "Fiação do sensor recuperada",
    "3372": "Fiação do sensor recuperada",
    "3383": "Tamper restaurado",
    "3384": "Bateria recuperada",
    "3401": "Ativado por",
    "3403": "Auto ativação",
    "3407": "Ativado via APP",
    "3408": "Ativado por uma tecla",
    "3409": "Ativado via controle remoto",
    "3410": "3 410",
    "3412": "Ativado stay via APP",
    "3413": "3 413",
    "3414": "Ativado stay via controle remoto",
    "3415": "Ativado via entrada liga",
    "3416": "3 416",
    "3417": "3 417",
    "3418": "Auto ativaçao stay",
    "3419": "Ativado via Alexa",
    "3420": "Ativado stay via Alexa",
    "3422": "Desacionamento",
    "3435": "Desacionamento via Alexa",
    "3456": "Ativado stay",
    "3461": "3 461",
    "3531": "Dispositivo encontrado",
    "3533": "Dispositivo RF apagado",
    "3534": "Senha apagada",
    "3535": "Zona desabilitada",
    "3570": "Restauração anulação temporária",
    "3573": "3 573",
    "3578": "Restauração anulação temporária via Alexa",
    "3601": "3 601",
    "3602": "3 602",
    "3616": "3 616",
    "3621": "3 621",
    "3624": "3 624",
    "3625": "3 625",
    "3998": "Restauração cliente cloud",
    "3999": "Restauração cliente OFF LINE falha de KEEP ALIVE",
}

# ---------------------------------------------------------------------------
# Receptor IP — classificação de cada código de evento: o campo bruto
# "zona_usuario" do frame (ver receptor_ip.parse_event) significa coisas
# diferentes dependendo do evento — às vezes é o número da zona, às vezes
# o número do usuário, às vezes o número da PGM, às vezes nenhum dos três
# (falhas de sistema/rede/barramento, por exemplo). Fonte: arquivo de
# referência fornecido pelo usuário (132 códigos, com campo "type" próprio
# — ZONE/USER/USER_PARTITION/PGM/SYSTEM/BUS_DEVICE), cruzado e usado para
# substituir a classificação anterior (68 códigos, planilha manual) —
# achado mais completo e, em 3 casos (3110, 1570, 1573), corrigindo uma
# classificação anterior equivocada. Usado por coordinator.on_receptor_event()
# para decidir se busca o nome em coordinator.zone_names ou
# coordinator.user_names ao montar o evento — "pgm" ainda não tem uma
# tabela de nomes própria nesta integração, então por enquanto não tem
# efeito (mesmo comportamento de "sem classificação").
# Códigos fora deste dict (SYSTEM/BUS_DEVICE, 68 dos 132) não têm nome
# associado — "zona_usuario" é ignorado nesses casos.
RECEPTOR_IP_EVENT_SUBJECT: dict[str, str] = {
    "1100": "usuario",
    "1110": "usuario",
    "1120": "usuario",
    "1122": "usuario",
    "1130": "zona",
    "1131": "zona",
    "1133": "zona",
    "1134": "zona",
    "1146": "zona",
    "1147": "zona",
    "1164": "zona",
    "1306": "usuario",
    "1371": "zona",
    "1372": "zona",
    "1383": "zona",
    "1384": "zona",
    "1401": "usuario",
    "1407": "usuario",
    "1409": "usuario",
    "1412": "usuario",
    "1414": "usuario",
    "1419": "usuario",
    "1420": "usuario",
    "1422": "pgm",
    "1435": "pgm",
    "1456": "usuario",
    "1533": "zona",
    "1534": "usuario",
    "1535": "zona",
    "1570": "zona",
    "1573": "zona",
    "1578": "zona",
    "3100": "usuario",
    "3110": "usuario",
    "3120": "usuario",
    "3122": "usuario",
    "3130": "zona",
    "3131": "zona",
    "3133": "zona",
    "3134": "zona",
    "3146": "zona",
    "3147": "zona",
    "3164": "zona",
    "3306": "usuario",
    "3371": "zona",
    "3372": "zona",
    "3383": "zona",
    "3384": "zona",
    "3401": "usuario",
    "3407": "usuario",
    "3409": "usuario",
    "3412": "usuario",
    "3414": "usuario",
    "3419": "usuario",
    "3420": "usuario",
    "3422": "pgm",
    "3435": "pgm",
    "3456": "usuario",
    "3533": "zona",
    "3534": "usuario",
    "3535": "zona",
    "3570": "zona",
    "3573": "zona",
    "3578": "zona",
}

# ---------------------------------------------------------------------------
# Entidades / plataformas
# ---------------------------------------------------------------------------
SIGNAL_STATUS_UPDATE = f"{DOMAIN}_status_update"
