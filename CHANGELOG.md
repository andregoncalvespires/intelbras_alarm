# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado na entrada v2.0.0; a partir daqui, toda mudança relevante é
registrada aqui antes de cada release.

## [2.1.0-beta]

### Melhoria — evita reescritas de estado desnecessárias (`always_update=False`)

Achado numa revisão pontual, cruzando com o blog oficial da Home
Assistant ("Avoid unnecessary callbacks with DataUpdateCoordinator",
2023-07-27): o comportamento **padrão** do `DataUpdateCoordinator` é
notificar/reescrever o estado de todas as entidades a cada ciclo,
**mesmo quando o dado não mudou** — a otimização (`always_update=False`)
existe, mas precisa ser configurada explicitamente, o que esta
integração não fazia.

Especialmente relevante para esta integração: polling a cada 0,25s
(4x/segundo) — bem mais frequente que o caso típico do artigo — então
a central provavelmente reporta o mesmo status na grande maioria dos
ciclos (casa parada). Requer que a classe de dados suporte comparação
de igualdade por valor — `protocol.PanelStatus` já tem isso "de graça"
por ser uma `@dataclass` simples (testado isoladamente antes de
aplicar: duas instâncias com os mesmos valores comparam como iguais,
com um campo diferente comparam como diferentes). Confirmado também
lendo o código-fonte do próprio `DataUpdateCoordinator` instalado: com
`always_update=False`, a notificação só acontece quando o sucesso da
consulta muda de estado *ou* os dados realmente mudam.

Ressalva conhecida e documentada no código: `coordinator.last_status_raw`
(bytes brutos da última resposta, exposto como atributo de diagnóstico
em "Último comando") vive fora do `PanelStatus` e é atualizado a cada
ciclo — num cenário bem incomum (algum byte não capturado por nenhum
campo interpretado mudando sozinho), esse atributo específico poderia
ficar parado até a próxima mudança real. Atributo puramente de
diagnóstico, sem efeito em nenhuma lógica de automação.

### Adicionado — entidades de partições armadas ausente/presente

Duas entidades novas (`sensor`): **"Partições armadas ausente"** e
**"Partições armadas presente"** — contagem no estado, lista de quais
partições nos atributos. Resumo rápido sem precisar checar cada
`alarm_control_panel` de partição individualmente. Usa
`status.partitions_armed` (o que a central reporta de verdade) como
fonte da existência/estado "ativada" — não só o que esta integração
rastreou internamente (`coordinator.armed_home_mode`), garantindo que
partições ativadas por fora dela (teclado físico, outro app) também
apareçam corretamente. Partições com disparo em andamento não entram
em nenhuma das duas contagens, mesmo critério já usado no estado de
cada `alarm_control_panel`. Testado isoladamente com 4 cenários
(ausente, presente, não rastreada, disparada).

### Adicionado — recomendação sobre o evento 1410 do app AMT Remoto

Documentação (tela de configuração + README) atualizada: quem preenche
a senha de leitura de 6 dígitos agora é avisado para considerar
desativar o envio do evento `1410` ("Acesso remoto para leitura de
eventos ou configurações") no app AMT Remoto — esta integração
autentica com essa senha periodicamente (a cada 5 minutos, para a
tensão), e cada autenticação gera esse evento na central, podendo
encher o histórico de eventos ao longo do tempo. Aproveitado também
para corrigir uma descrição desatualizada no README sobre quando essa
senha é necessária (não mencionava mais a tensão como um dos motivos).

### Corrigido — timeouts de status coincidindo com o ciclo de tensão (causa raiz real)

Investigação aprofundada (log real + análise cruzada de arquitetura,
com apoio de outra IA consultada pelo usuário) sobre os timeouts
esporádicos na consulta de status já relatados numa versão anterior
desta release — a mitigação anterior (pausa de acomodação de 1s
depois da consulta de tensão) não resolveu de fato, como confirmado
por um novo log em produção: os timeouts continuavam acontecendo,
sempre no **mesmo instante exato** dentro de cada ciclo de 5 minutos
da consulta de tensão (não distribuídos aleatoriamente).

Causa raiz confirmada no código: a sequência de autenticação + consulta
(protocolo `0xE7`, usado tanto na tensão quanto na leitura legada de
nomes/eventos) enviava cada comando via `send_command()` normal — que
adquire e libera o lock de comunicação **a cada chamada individual**.
Isso deixava uma janela real, durante o `asyncio.sleep()` entre a
autenticação e o comando seguinte, em que o polling rápido de status
(a cada 0,25s) podia se intercalar **no meio** da troca autenticada —
provavelmente confundindo o estado de sessão da central e causando
lentidão na resposta ao comando seguinte, seja da própria transação ou
do polling.

- `panel_client.PanelClient`: novo mecanismo de transação atômica —
  `transaction()` (context manager que mantém o lock adquirido por
  toda a duração de um bloco `async with`) e
  `send_command_in_transaction()` (mesma lógica de `send_command()`,
  mas sem adquirir o lock sozinho — só utilizável dentro de
  `transaction()`). `send_command()` continua funcionando exatamente
  como antes para uso avulso.
- `coordinator.async_refresh_voltage()` e
  `coordinator._async_legacy_eeprom_session()` (usada tanto na
  sincronização de nomes quanto na leitura de eventos) — reescritas
  para rodar a sequência inteira (autenticação + comando(s) seguintes)
  dentro de uma única transação, sem soltar o lock no meio.
- Testado isoladamente: confirmado que nenhum status consegue adquirir
  o lock durante uma transação em andamento (mesmo com múltiplas
  tentativas concorrentes simuladas), e que uma exceção levantada no
  meio de uma transação ainda libera o lock corretamente (sem travar a
  conexão).
- Instrumentação de log adicionada (nível debug) nos três caminhos —
  consulta de status normal, consulta de tensão, sessão legada — com
  timestamps de alta resolução em cada etapa, para permitir confirmar
  em produção (com o log em nível debug ativado) se a correção resolveu
  de fato, e facilitar diagnósticos parecidos no futuro.

### Corrigido — nomes de zona/usuário voltavam ao genérico após reinício

Relatado pelo usuário: desligar a conexão com a central, reiniciar o
Home Assistant e religar a conexão fazia as entidades caírem de volta
nos nomes genéricos ("Zona 01" etc.), mesmo com os nomes reais ainda
intactos na EEPROM da central. Causa raiz: `zone_names`/`user_names`
só existiam na memória do processo — qualquer reinício os zerava — e
nada disparava uma nova sincronização automática ao religar a conexão
manualmente.

Corrigido com persistência própria (`names_state.py`, mesmo padrão já
usado em `connection_state.py` — `homeassistant.helpers.storage.Store`,
independente de `ConfigEntry.options`):
- Os nomes lidos com sucesso (automaticamente ou pelo botão
  "Sincronizar nomes de zona") agora são salvos em disco, sobrevivendo
  a reinícios/reloads/reconfigurações.
- No (re)carregamento, os nomes salvos são carregados **antes** de
  qualquer tentativa de conexão — as entidades já nascem com o nome
  certo, mesmo sem rede.
- A sincronização automática só é tentada quando **nunca** houve uma
  sincronização bem-sucedida antes (primeira configuração de verdade,
  detectada pela ausência de qualquer dado salvo) — evita o risco de
  uma tentativa que falha ou é pulada (conexão desligada) sobrescrever
  nomes bons por nomes genéricos. Combinada com a lógica de
  retentativas (até 5x) já existente.
- O botão manual continua funcionando sempre, e cada sincronização
  bem-sucedida por ele atualiza o que fica salvo.

### Corrigido — Receptor IP parava de vez após recarregar/reconfigurar

Relatado pelo usuário: recarregar ou reconfigurar a integração enquanto
a central tinha uma conexão ativa no Receptor IP fazia a comunicação
parar sem erro visível — nem recarregar de novo nem reconfigurar
resolviam, só um reinício completo do Home Assistant. Causa:
`asyncio.Server.close()` só impede **novas** conexões, deixando conexões
já aceitas abertas (comportamento documentado do próprio asyncio) — a
task da conexão ativa continuava rodando com callbacks apontando pro
coordinator antigo, e a central seguia mandando eventos pra essa conexão
órfã sem saber que precisava reconectar. Corrigido rastreando conexões
ativas e fechando cada uma explicitamente em `async_stop()`.

### Adicionado — retentativas (até 5x) na busca de nomes de zona/usuário

A busca inicial de nomes de zona/usuário, feita uma única vez na
configuração/recarregamento, agora tenta até 5 vezes (com pausa entre
cada uma) antes de desistir — cobre instabilidades momentâneas de
conexão logo após o Home Assistant subir, sem entrar em loop eterno se a
central genuinamente não estiver respondendo. Novo helper reutilizável
`_async_retry()` em `__init__.py`.

### Corrigido — bugs reais achados testando a tensão em campo

- **Timer de tensão nunca era criado se a conexão estivesse desligada no
  (re)carregamento**: religar o switch "Conexão com a central" depois
  não resolvia (não havia timer nenhum para retomar) — só um reinício
  completo do Home Assistant "consertava". Corrigido: o timer de 5
  minutos agora é sempre registrado, independente do estado da conexão
  no momento do (re)carregamento; `async_refresh_voltage()` verifica
  sozinho se a conexão está habilitada e sai em silêncio quando não
  está (sem gerar aviso repetido a cada 5 minutos à toa). O switch
  também passou a buscar a tensão imediatamente ao religar, em vez de
  esperar até 5 minutos pelo próximo ciclo.
- **Timeouts esporádicos na consulta de status normal**, coincidindo
  sistematicamente com múltiplos de 5 minutos (relatado com logs reais)
  — indício de que a central precisa de um instante para se recompor
  depois da troca autenticada via `0xE7` antes de responder prontamente
  ao próximo `0x5A`/`0x5B` do polling rápido. Mitigado com uma pausa de
  acomodação de 1 segundo após a consulta de tensão, antes de liberar a
  conexão de volta pro polling normal — heurística baseada na
  correlação observada, não uma medição exata; acompanhar os logs após
  esta versão para confirmar se o problema foi resolvido ou só reduzido.

### Adicionado — nome (zona/usuário) também no serviço `read_events`

O serviço `intelbras_alarm.read_events` e a entidade "Últimos eventos"
agora resolvem o nome da zona/usuário no campo `nome` de cada evento,
mesma lógica já usada nas mensagens do Receptor IP (`codigo` → tipo →
`zone_names`/`user_names`) — extraída para um método único e
compartilhado (`coordinator._resolver_nome_por_codigo()`) para evitar
duplicar a regra entre os dois lugares. Funciona nos 3 caminhos de
leitura de eventos (`0x5C`, protocolo legado `0xE7`, AMT 8000).

### Alterado — tela de configuração e serviço `read_events`

- Campo "Senha de leitura de mensagens" renomeado para "Senha acesso
  App AMT Remoto", com o texto de orientação atualizado mencionando
  também a leitura de tensão como um dos usos dessa senha.
- Descrição do serviço `read_events` simplificada — focada em
  requisitos e comportamento, sem detalhes de implementação (comando,
  endereço de memória) que não ajudam quem só quer usar o serviço.

### Adicionado — tensão da fonte e da bateria (sub-comando `[1, 0x17]`, `0xE7`)

Duas entidades novas (`sensor`): **"Tensão da fonte"** e **"Tensão da
bateria"**, atualizadas a cada 5 minutos. Achado e confirmado pelo
usuário contra hardware real, em dois modelos diferentes:
- AMT 1016 NET, firmware 3.1 (família 2018): fonte 14,49V, bateria 13,66V
- AMT 4010 SMART, firmware 5.2 (família 4010 — funciona mesmo essa
  família normalmente usando `0x5C` para nomes/eventos): fonte 13,58V,
  bateria 0,00V (central testada sem bateria conectada)

- Novo sub-comando dentro do mesmo `0xE7` já usado para nomes/eventos
  legados (`[1, 0x17]`, não é leitura de EEPROM — consulta de status
  direta), mesma autenticação/CRC/checksum já validados.
- Disponível **só com a senha de leitura de 6 dígitos configurada**
  (`coordinator.supports_voltage_reading`) — independente de
  `supports_extended_eeprom`/`supports_legacy_eeprom`, confirmado
  funcionando mesmo em modelos com `0x5C` disponível. Inclui a ANM 24
  Net por extrapolação de família (decisão do usuário — nunca testado
  especificamente nesse modelo; falha de forma silenciosa se não
  funcionar). Não se aplica à AMT 8000 (protocolo totalmente diferente).
- Consulta roda **fora** do polling rápido de status, em agendamento
  próprio de 5 minutos (`async_track_time_interval`) — evita
  autenticações repetidas desnecessárias no mesmo ritmo do status.
  Reaproveita a mesma conexão persistente; a fila (lock) já existente
  evita qualquer risco de concorrência com o polling normal.
- **Bug real corrigido antes de publicar**: o offset da família 4010
  havia sido transcrito errado por 1 byte numa etapa manual anterior
  (`(23, 25)` em vez do correto `(22, 24)`) — só percebido ao testar o
  parser de ponta a ponta contra os dois exemplos reais fornecidos
  pelo usuário, que só então bateram exatamente com os valores
  reportados.

Primeira versão de `main` a incluir suporte experimental à **AMT 8000**
(consolidado a partir do branch `dev`, onde foi desenvolvido e testado
isoladamente ao longo de várias versões `2.1.0-dev.N`), além de uma
melhoria nova no Receptor IP.

### Adicionado — AMT 8000 (experimental, protocolo próprio)

⚠️ **Nada desta seção foi validado contra hardware real** — toda a
implementação vem de engenharia reversa (decompilação do app oficial
AMT Remoto v3.4.2.2) cruzada com um fluxo Node-RED de terceiros usado
como referência. Ver README_DETALHADO.md, seção "AMT 8000
(experimental)", para o detalhe técnico completo, o que já foi
confirmado por projetos de terceiros (`fdaneluzzi/homeassistant-amt8000`)
e o que ainda depende de teste em campo.

- **Protocolo de transporte totalmente separado do ISECMobile** —
  framing próprio (`[0x00 0x00][srcId][0x00][LEN][opcode][conteúdo]
  [checksum]`), autenticação de sessão (`0xF0F0`, uma vez por conexão,
  não por comando), opcodes próprios para status, arme/desarme, bypass
  (individual por zona, diferente do comando absoluto do ISECMobile),
  PGM, pânico, leitura de eventos (buffer circular de até 512 posições)
  e sincronização de nomes (central/zona/usuário/partição/PGM/teclado/
  sirene). Módulos novos: `protocol_amt8000.py`, `panel_client_amt8000.py`.
- **Configuração manual, não detecção automática**: opção "AMT 8000
  (protocolo experimental)" na tela inicial — precisa ser marcada
  explicitamente; os demais modelos continuam com a sondagem automática
  de sempre, sem nenhuma mudança de comportamento.
- **16 partições numeradas** (não A-D como o ISECMobile) — nova classe
  `IntelbrasAmt8000PartitionAlarmPanel`.
- **"Pedir senha para ativar/desativar" tratado com segurança**: como o
  comando de arme/desarme desta central não carrega senha nenhuma (a
  autenticação é só da conexão), a integração agora compara o valor
  digitado **localmente** contra a senha configurada antes de agir —
  sem essa correção, qualquer sequência de dígitos "funcionaria" para
  armar/desarmar com essa opção marcada (achado real durante a
  consolidação, não só uma inconsistência de UX).
- **Entidade `camera` nova** ("Foto de evento") — sensores com câmera
  desta central. ⚠️ Incompleta: existe e funciona com segurança (mostra
  "sem imagem disponível"), mas ainda não consegue baixar uma foto de
  verdade — falta identificar com confiança um campo do protocolo.
- Zonas com falha de comunicação RF (`zones_comm_failure`) expostas como
  atributo extra nas entidades de zona já existentes — vazio `{}` nas
  demais famílias.
- Valores confirmados em hardware real por um projeto de terceiros
  (`fdaneluzzi/homeassistant-amt8000`) durante a consolidação:
  `AMT8000_ALL_PARTITIONS = 0xFF` (não `0`) e `AMT8000_STATUS_MAX_LEN =
  143` bytes de conteúdo (não 152, que era o tamanho do frame completo).

### Adicionado — nomes de usuário nas mensagens do Receptor IP

- Nomes de usuário agora são lidos junto com os de zona (mesma
  sincronização, mesmo botão/gatilho automático) — antes, o caminho
  legado (`0xE7`) já extraía esses nomes e descartava; o caminho
  moderno (`0x5C`) ganhou uma leitura nova, no endereço logo após o
  último slot de zona do modelo.
- Mensagens de evento do Receptor IP agora mostram o **nome** (zona ou
  usuário, conforme o tipo de evento) em vez do número cru, quando
  disponível — novo dict `const.RECEPTOR_IP_EVENT_SUBJECT` decide qual
  tabela consultar. Sem nome carregado, continua mostrando o número,
  como antes.

### Atualizado — tabela de códigos de evento do Receptor IP: 68 → 132 códigos

Substituída por uma tabela de referência mais completa (132 códigos,
fornecida pelo usuário, com um campo "tipo" próprio por código —
`ZONE`/`USER`/`USER_PARTITION`/`PGM`/`SYSTEM`/`BUS_DEVICE`). Os 68
códigos anteriores continuam todos presentes, com a descrição
atualizada quando a fonte nova trouxe uma redação diferente.

- `const.RECEPTOR_IP_EVENT_SUBJECT` recalculada a partir do campo
  "tipo" da fonte nova (antes: 38 códigos classificados manualmente
  numa planilha; agora: 64, incluindo uma categoria nova, **PGM**, que
  não existia antes — ainda sem efeito prático, já que esta integração
  não tem uma tabela de nomes de PGM para consultar).
- **Corrigidas 3 classificações que a planilha anterior tinha errado**:
  `3110` (restauração de disparo/pânico de incêndio) era "zona", na
  verdade é "usuário" — mesma classificação do disparo original
  (`1110`). `1570`/`1573` (anulação temporária / anulação por disparo)
  eram "usuário", na verdade são "zona" — faz mais sentido semântico,
  já que se anula zonas, não usuários.
- **Corrigido um significado real, não só uma redação**: `1333`/`3333`
  eram documentados como "Problema/Restauração em teclado ou receptor"
  — a fonte nova (com um campo de categoria próprio, `BUS_DEVICE`)
  mostra que são na verdade "Falha/Recuperação de dispositivo de
  barramento", um conceito diferente. Adotada a fonte nova por decisão
  do usuário.

### Corrigido — nomes de usuário deslocados por um (bug real, achado em testes)

O primeiro slot de usuário na EEPROM (logo após os nomes de zona) não é
o usuário 1 — é o registro **"Usuário Master"** da central, um slot à
parte. As duas leituras de nomes de usuário (`0x5C` e o protocolo
legado `0xE7`, que compartilham a mesma memória física) tratavam esse
slot como se fosse o usuário 1, deslocando toda a numeração por um —
pedir o nome do usuário 10 da central devolvia o que estava no slot 9
("Usuário 09"). Achado pelo usuário testando a v2.1.0-beta numa AMT
1016 NET real (protocolo legado).

- `protocol_legacy_eeprom.parse_nomes()`: slot 0 agora reservado para o
  Master (chave `0`, nunca usada por um evento real), usuários
  numerados começam corretamente do slot 1.
- `coordinator.async_refresh_zone_names()` (caminho `0x5C`): endereço
  de leitura deslocado em 16 bytes (pula o slot do Master), capacidade
  reduzida em 1 pelo mesmo motivo.
- Testado com dados simulados reproduzindo o layout real (Master +
  usuários numerados) nos dois caminhos — resultado correto nos dois.
- Também adicionado: log de depuração para eventos recebidos pelo
  Receptor IP (`receptor_ip.py`, evento bruto recebido;
  `coordinator.py`, resultado do enriquecimento com nome) — ausente
  até então, dificultava diagnosticar esse tipo de problema.

## [2.0.3]

### Corrigido
- **Integração travava (entidades indisponíveis) ao recarregar ou ao
  reconfigurar** (ex.: adicionar a senha de leitura de mensagens) — só
  recuperava com um reinício completo do Home Assistant. Causa: o
  fechamento da conexão TCP com a central (`writer.wait_closed()`, e o
  equivalente no servidor Receptor IP) não tinha nenhum timeout de
  proteção — se a central (dispositivo embarcado, pilha TCP simples)
  não confirmasse o fechamento de forma limpa, a chamada podia travar
  **indefinidamente**, impedindo o descarregamento da integração de
  terminar. Corrigido com um timeout de 3s: se o fechamento não for
  confirmado a tempo, a integração desiste de esperar e segue em
  frente mesmo assim. **Confirmado pelo usuário**, reproduzindo os
  dois cenários relatados antes da correção e validando que não
  travam mais depois dela.

### Documentação
- README.md/README_DETALHADO.md: tabela de modelos/firmwares testados
  reorganizada — a observação sobre o firmware 6.2 (AMT 4010 SMART)
  virou nota de rodapé numerada, em vez de texto longo dentro da
  célula da tabela.

## [2.0.2]

Passou por 6 rodadas de pré-lançamento (v2.0.2-beta.1 a beta.6) antes de
se tornar oficial — resumo consolidado abaixo. Detalhe completo de cada
mudança, incluindo commits e testes isolados, disponível no histórico
do git.

### Corrigido — bugs reais de estabilidade
- **CPU alta com o switch "Conexão com a central" desligado**: o
  agendador do próprio Home Assistant continuava se reagendando
  sozinho, mesmo com cada tentativa falhando instantaneamente — chegou
  a milhares de chamadas por segundo em log real. Corrigido
  interrompendo o agendamento por completo enquanto o switch estiver
  desligado, tanto ao desligar manualmente quanto se a integração já
  subir desligada.
- **Resposta de status truncada tratada como sucesso**: um bug de
  firmware conhecido (AMT 4010 SMART, firmware 6.2) fazia a central
  enviar uma resposta menor que o esperado de vez em quando — agora
  tratado como falha isolada e tolerada (mantém o último dado bom
  conhecido), não como um status válido incompleto.
- **Leitura legada de EEPROM (nomes de zona/eventos) tinha 3 bugs
  reais**, todos corrigidos: conexão isolada que sempre falhava (a
  central só aceita um cliente por vez — corrigido reaproveitando a
  conexão persistente já existente), botão de sincronizar não
  aparecia pro caminho novo, e a mesma lacuna em mais dois pontos
  (sincronização automática na configuração inicial e a entidade
  "Últimos eventos").

### Adicionado — compatibilidade de modelos, bem mais ampla
- **8 novos modelos reconhecidos automaticamente**: AMT 2008 RF, AMT
  2010, AMT 2018 (base), AMT 2110, AMT 2118 EG, AMT 3010, AMT 2018 E3G,
  GPRS 1000 UN — confirmado por engenharia reversa do app oficial que
  todos eles são tratados de forma idêntica à AMT 2018 E/EG já
  suportada (mesma classe do app, mesmo comando, mesmos offsets).
- **ANM 24 Net**: nome corrigido ("ANM 24 Net", não "AMN 24 NET" como
  antes) e adicionada a variante G2.
- **AMT 2018 E Smart**: comando de status próprio (`0x5D`, não `0x5A`)
  identificado e implementado corretamente, com validação posição por
  posição contra o app oficial. Ganhou também dados adicionais
  exclusivos desse modelo: diagnóstico de rede/celular (2 sensores
  novos), atributos extras nas zonas 25-48 (sem fio, tamper, curto,
  bateria, supervisão RF), e o status de Stay por partição reportado
  diretamente pela própria central.
- Nenhum dos modelos novos (os 8 + AMT 2018 E Smart) foi testado
  contra hardware real ainda — toda essa expansão vem de engenharia
  reversa do app oficial, documentada com o nível de confiança de
  cada item no README_DETALHADO.md.

### Adicionado — nomes de zona e eventos, cobertura bem maior
- **Novo caminho para modelos/firmwares fora do limiar do `0x5C`**
  (ex.: AMT 1016 NET com firmware antigo, que antes ficava sem essa
  função por completo): protocolo legado (`0xE7` + senha de leitura de
  mensagens opcional), confirmado funcionando de ponta a ponta em
  hardware real — nomes de zona, usuário e log de eventos completo.
- **12 novos códigos de evento confirmados** na tabela de tradução
  (de 22 para 26), a partir de leituras reais de log de eventos.

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
