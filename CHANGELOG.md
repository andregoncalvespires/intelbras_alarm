# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado nesta primeira entrada; a partir daqui, toda mudança relevante
é registrada aqui antes de cada release.

## [2.1.0-dev.6] — EXPERIMENTAL, branch `dev`

Ajustes a partir da comparação com o projeto de terceiros
`fdaneluzzi/homeassistant-amt8000` (testado em hardware real), com
decisões explícitas do usuário sobre quais pontos aplicar.

### Corrigido
- **Arme/desarme de "central inteira"**: usava `0` (herdado sem
  confirmação do fluxo Node-RED de referência) — corrigido para `0xFF`
  (`const.AMT8000_ALL_PARTITIONS`), valor confirmado em hardware real
  pelo `fdaneluzzi`. Partições individuais (1-16) não mudam.
- **`AMT8000_STATUS_MAX_LEN`**: era `152` (na verdade o tamanho do
  frame *total*, incluindo framing) — corrigido para `143`, o tamanho
  real do *conteúdo* (`response.content` já vem sem cabeçalho/opcode/
  checksum, então é contra isso que a checagem deveria comparar).
  Agora um valor confirmado em hardware real (mesmo projeto de
  terceiros), não mais uma estimativa — mas os offsets dos campos
  dentro do conteúdo continuam sem validação própria, então a checagem
  de truncamento manteve a mesma margem cautelosa (50%), sem perda de
  robustez.
- Documentação (`README_DETALHADO.md`): corrigida a descrição das
  partições no status (1 byte por partição, não 1 bit — a doc estava
  desatualizada em relação ao código).

### Mantido, sem alteração (decisão explícita do usuário)
- Modelo de conexão (persistente, não por-operação) — traz benefícios
  reais para automações e resposta em tempo quase real; mantido mesmo
  sabendo que o `fdaneluzzi` usa conexão por operação.
- Codificação da senha na autenticação — sem certeza suficiente para
  mudar, mantida como está.
- Os achados novos do `fdaneluzzi` sem equivalente aqui (detecção de
  zonas abertas bloqueando o arme, códigos de erro de autenticação) —
  não implementados nesta rodada.

## [2.1.0-dev.5] — EXPERIMENTAL, branch `dev`

### Adicionado
- 5 novos códigos de evento confirmados em `protocol.EVENT_CODE_TABLE`
  (mesma correção aplicada em `main`/v2.0.2-beta.1): `9`→`3333`, `47`→`3361`,
  `158`→`1354`, `165`→`1621`, `175`→`1361`. Tabela agora com 22 códigos
  confirmados (era 17).

### Corrigido
- Byte `45` mapeava para `3333`, mas na verdade corresponde a `3531`
  ("Dispositivo Encontrado") — o `3333` correto é o byte `9` (novo).

## [2.1.0-dev.4] — EXPERIMENTAL, branch `dev`

### Corrigido
- **CPU alta com o switch "Conexão com a central" desligado** (mesma
  correção aplicada em `main`/v2.0.2-beta.1): o agendador do próprio Home
  Assistant continuava se reagendando sozinho mesmo com o switch
  desligado, criando um laço de milhares de chamadas por segundo (log
  real confirmou). Corrigido com `coordinator.pause_polling()`/
  `resume_polling()`, chamado ao desligar/religar o switch e também na
  inicialização (equiparado ao caminho da AMT 8000 também, já que o
  agendamento é compartilhado por todas as famílias).

### Adicionado
- Novo código de evento na tabela do Receptor IP: `3531` ("Dispositivo
  Encontrado").

## [2.1.0-dev.3] — EXPERIMENTAL, branch `dev`

### Corrigido
- **Falha de segurança real**: "Pedir a senha para ATIVAR/DESATIVAR pelo
  Home Assistant", na AMT 8000, checava só o **formato** do que era
  digitado (4 a 6 dígitos) — nunca o conteúdo — porque o comando de fio
  dessa central (`0x401E`) não carrega senha nenhuma (autenticação é só
  na conexão, uma vez). Na prática, **qualquer sequência de dígitos
  "funcionava"** para armar/desarmar com essa opção marcada. Corrigido:
  para esta família, o valor digitado agora é comparado **localmente**
  pela integração contra a senha configurada, antes de qualquer comando
  ser enviado — bloqueia com "Senha incorreta" se não bater. Sem efeito
  nas demais famílias (continuam com a central validando via NACK, como
  sempre). Ver README_DETALHADO.md, seção AMT 8000, "Pedir senha para
  ativar/desativar".

## [2.1.0-dev.1] — EXPERIMENTAL, branch `dev`

⚠️ Esta versão **não é destinada à `main`/HACS** — publicada apenas na
branch `dev` para desenvolvimento e teste em campo. Nenhum dos pontos
abaixo foi validado contra hardware real ainda; ver
`README_DETALHADO.md`, seção "AMT 8000 (experimental)", para o que já
foi confirmado (por engenharia reversa do app oficial AMT Remoto) e o
que ainda depende de captura de tráfego própria.

### Adicionado
- Suporte inicial (experimental) à central **AMT 8000**, que usa um
  protocolo próprio, autenticado, diferente do ISECMobile/ISECNet das
  demais famílias:
  - Novos módulos `protocol_amt8000.py` (framing, checksum, opcodes,
    parsing de status e de evento) e `panel_client_amt8000.py`
    (conexão persistente com sessão autenticada).
  - Opção "AMT 8000 (protocolo experimental)" no formulário de
    configuração inicial, para pular a detecção automática 2018/4010
    (protocolos incompatíveis) e autenticar direto pelo novo protocolo.
  - Arme/desarme/stay, bypass individual por zona (não em lote — mais
    simples que o comando absoluto do ISECMobile), controle de PGM 1-16
    e pânico.
  - Leitura de status completo reaproveitando a mesma dataclass
    `PanelStatus` das demais famílias (zonas, partições — 16 numeradas,
    bateria, sirene, PGMs, data/hora), incluindo campo novo
    `zones_comm_failure` (falha de comunicação RF por zona, exclusivo
    desta família).
  - Sincronização de nomes de zona (1 zona por requisição, decisão de
    arquitetura registrada no histórico do projeto) e leitura do log de
    eventos (buffer circular de 512 posições, 1 evento por requisição).
  - Nova entidade `camera` ("Última foto de evento"), salvando fotos em
    `/media/amt8000/<id>/` — ⚠️ **incompleta**: o índice de foto exigido
    pelo comando `0x0BB0` ainda não foi confirmado no formato do evento
    novo, então a busca real de imagem ainda não funciona (a entidade
    mostra "sem imagem disponível" com segurança, sem quebrar).
  - Intervalo de polling continua configurável (padrão sugerido: 0,25s).

### Conhecido como incompleto/pendente (ver README_DETALHADO.md)
- Nenhum opcode, offset de status ou de evento foi confirmado por
  captura de tráfego própria contra uma central AMT 8000 real — toda a
  implementação vem de engenharia reversa do app oficial (androguard)
  cruzada com um fluxo Node-RED de terceiros testado em campo.
- Esquema de ACK/NACK dos comandos de ação (armar, bypass, PGM, pânico)
  ainda não confirmado — comandos são considerados aceitos se não
  houver erro de conexão, sem validar o conteúdo da resposta.
- Download de foto de evento (fragmentação, autenticação de sessão de
  fotos) implementado apenas como esqueleto de uma tentativa única.
- Comportamento de reconexão/timeout da sessão autenticada sob polling
  sustentado ainda não testado.

## [2.0.1]

### Corrigido
- `hacs.json`: removida a chave `domains`, não reconhecida pelo schema de
  validação do HACS (`extra keys not allowed @ data['domains']`) — o
  domínio já é detectado automaticamente a partir do `manifest.json`
  dentro de `custom_components/`, não precisa (nem pode) ser declarado
  aqui. Corrige a falha na validação `hacsjson` do workflow
  `hacs/action`.

## [2.0.0] — Primeira versão pública

Primeira versão liberada para a comunidade. Consolida meses de
desenvolvimento e testes em hardware real (AMT 1016 NET, AMT 2018 E/EG,
AMT 4010 SMART) em uma base considerada estável para uso público.

### Adicionado
- Suporte a AMT 1016 NET, AMT 2018 E/EG, AMT 2018 E SMART, AMN 24 NET e
  AMT 4010 SMART via protocolo ISECNet/ISECMobile
- Entidades de alarme (central + partições), zonas, PGMs, sirene,
  sensores de bateria/diagnóstico
- Serviços `bypass_zone`, `send_raw_command` (diagnóstico avançado) e
  `read_events` (leitura do log de eventos via EEPROM)
- Sincronização de nomes de zona e leitura de eventos via EEPROM
  (`0x5C`), restrita aos modelos/firmwares com esse comando liberado
- **Receptor IP**: recepção de eventos em tempo real empurrados pela
  própria central (opcional, desligado por padrão)
- Templates de issue no GitHub para relatar problemas e sugerir
  funcionalidades

### Documentado
- README com passo a passo de instalação/configuração
- README_DETALHADO com toda a engenharia reversa do protocolo,
  decisões técnicas e limitações conhecidas
- Disclaimer de responsabilidade (projeto sem vínculo com a Intelbras)

### Corrigido nesta versão
- Lista de modelos testados: firmware da AMT 2018 E/EG corrigido de 6.2
  para 4.7 (valor realmente validado)
- Tabela de eventos do Receptor IP: adicionados os códigos `1361`
  ("Falha keep alive ethernet") e `3361` ("Keep alive ethernet
  recuperado")
- Documentação do Receptor IP: adicionado aviso sobre o sentido da
  conexão (central → Home Assistant) para redes com VLAN/segmentação
