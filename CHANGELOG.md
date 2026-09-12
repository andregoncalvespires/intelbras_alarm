# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado na entrada v2.0.0; a partir daqui, toda mudança relevante é
registrada aqui antes de cada release.

## [2.1.2]

### Corrigido — divergência entre o que foi pedido e o que foi publicado na 2.1.1

Na 2.1.1, além da mudança combinada explicitamente com o usuário
(manter a pausa de acomodação de 1s dentro do lock — ver `2.1.1`
abaixo), também foi removida por conta própria a função
`send_without_response_in_transaction()` de `panel_client.py` (código
não usado em lugar nenhum, sugerido como remoção numa análise anterior)
— sem reconfirmar isso com o usuário depois que o pedido explícito
final foi "implemente na íntegra". Usuário percebeu a divergência e
pediu correção.

Corrigido restaurando a função exatamente como estava no arquivo
recebido do usuário. Confirmado com diff byte a byte contra o arquivo
original: 7 dos 8 arquivos adotados na 2.1.1 já eram idênticos; agora
o oitavo (`panel_client.py`) também é — a única diferença
remanescente, em `coordinator.py`, é exatamente a pausa de 1s mantida
dentro do lock, que foi um pedido explícito do usuário, não uma
liberdade tomada.

## [2.1.1]

Passou por duas rodadas de pré-lançamento (v2.1.0-beta e v2.1.1-beta,
com várias correções cada) antes de se tornar oficial — resumo
consolidado abaixo. Detalhe completo de cada mudança, incluindo
commits, análises comparativas com versões alternativas testadas por
usuários, e testes isolados, disponível no histórico do git.

### Corrigido — arquitetura de comunicação (causa raiz de instabilidades reais)

- **Causa raiz dos timeouts de status, identificada e corrigida em
  camadas**: investigação com log real em produção revelou que o
  `update_interval` sub-segundo do `DataUpdateCoordinator` do próprio
  Home Assistant não é preciso o suficiente (confirmado direto no
  código-fonte do HA — o scheduler não foi desenhado para isso, e
  produzia rajadas de 6-8 consultas em menos de 100ms seguidas de
  pausas, não a cadência estável pretendida). Substituído por um
  **scheduler próprio** (`update_interval=None`), que nunca tenta
  "recuperar" atraso e agenda o polling com precisão de verdade.
  Autenticação e consulta em protocolos com sessão (`0xE7`) passaram a
  rodar como **transação atômica**, evitando que o polling rápido se
  intercalasse no meio de uma troca autenticada. Depois disso, uma
  segunda causa foi encontrada e corrigida: bytes residuais de uma
  sessão `0xE7` anterior (a resposta de logout que nunca líamos)
  dessincronizavam o leitor genérico da consulta de status seguinte —
  corrigido enviando o logout de verdade, lendo e validando sua
  resposta completa, e fechando a conexão TCP incondicionalmente ao
  final de toda sessão `0xE7`, sucesso ou falha. Todas essas correções
  foram validadas com testes reais (sockets de verdade, locks
  concorrentes, reprodução exata dos padrões de bytes observados em
  produção), não apenas inspeção de código.
- **Prioridade de comando sobre o scheduler de status**: comandos do
  usuário (armar, desarmar, PGM, etc.) agora têm prioridade sobre a
  próxima consulta periódica — esperam apenas a consulta que já
  estiver em andamento no momento em que chegam, nunca ficam atrás de
  uma nova consulta que o scheduler dispararia por coincidência de
  tempo.
- **Inicialização do Home Assistant demorando exageradamente** após
  atualizar: o scheduler próprio criava sua tarefa de fundo com
  `hass.async_create_task()`, que fica registrada num conjunto que
  `hass.async_block_till_done()` espera terminar — e como o scheduler
  roda indefinidamente, isso travava a inicialização. Corrigido usando
  `entry.async_create_background_task()`, documentado pelo próprio HA
  como seguro para esse propósito.
- **Entidades não ficavam indisponíveis** quando o switch "Conexão com
  a central" era desligado (ou a integração subia com ele já
  desligado): o mecanismo que marca isso agora é explícito e
  imediato, sem depender de uma tentativa de comunicação falhar
  primeiro.
- **Botões de ação (pânico, anular zonas, sincronizar nomes) nunca
  refletiam mudança de disponibilidade**, em nenhuma direção — nem
  ficavam indisponíveis ao desligar a conexão, nem voltavam a ficar
  disponíveis ao religar. Bug pré-existente, só ficou visível quando a
  correção anterior passou a marcar a indisponibilidade corretamente.
- **Consulta de tensão continuava rodando após remover a senha do app
  remoto** na reconfiguração da integração — corrigido lendo a senha
  sempre em tempo real da configuração.
- **Sensor "Últimos eventos"** não ficava indisponível quando a
  comunicação com a central falhava (checava só se a funcionalidade
  estava habilitada, não se a conexão estava saudável).
- Tolerância a falhas isoladas de status refinada: a primeira falha
  consecutiva fica em nível de depuração (silenciosa); só a partir da
  segunda seguida é que gera aviso no log — evita ruído por um soluço
  isolado sem esconder uma interrupção real. Mensagens de falha agora
  incluem contexto de diagnóstico (idade da última sessão `0xE7`, se o
  logout foi confirmado, se há suspeita de reinicialização de rede em
  andamento).

### Adicionado

- **Suporte experimental à AMT 8000** (protocolo próprio, autenticação
  e status funcionando; câmera de eventos ainda sem decodificar a
  imagem em si) — nada testado contra hardware real ainda.
- **Nomes de usuário nas mensagens do Receptor IP** e tabela de
  eventos ampliada de 68 para 132 códigos.
- **Nomes de zona/usuário agora sobrevivem a reinícios** do Home
  Assistant (antes eram perdidos e precisavam ressincronizar).
- **Nova opção "Consultar tensão da fonte/bateria"**, independente da
  senha do app remoto: em modelos com firmware antigo, a senha é
  obrigatória só para nomes de zona/eventos — antes, removê-la para
  desligar a tensão quebrava essa outra funcionalidade também. Marcada
  por padrão (sem quebrar quem já usa a funcionalidade hoje).
- **Detecção experimental de reinicialização de rede da central**: um
  sensor de diagnóstico novo correlaciona o fechamento gracioso (FIN)
  da conexão de comandos/status com o do Receptor IP dentro de uma
  janela de 1 segundo — indício de que a própria central reiniciou seu
  subsistema de rede, não um problema da integração. Puramente
  diagnóstico, não muda disponibilidade de nenhuma entidade funcional.
- Receptor IP reconhece o comando de solicitação de data/hora da
  central (não responde com calendário ainda — a central já mantém
  sincronismo por outro canal).

### Desempenho

- `always_update=False` no `DataUpdateCoordinator` e um filtro na
  resposta bruta antes de interpretar — evita reescritas de estado e
  notificações desnecessárias quando os dados não mudam.
- Corrigida a granularidade de segundo na AMT 8000, causa real de até
  60 atualizações/minuto desnecessárias.
- Timeout de leitura da consulta de status reduzido de 3s para 300ms
  (família 1016/2018/4010 e derivadas — não afeta a AMT 8000): falha
  rápido numa troca travada, deixando o scheduler tentar de novo
  quase na hora, em vez de bloquear o ciclo por até 3 segundos.

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
