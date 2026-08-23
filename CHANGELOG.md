# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado nesta primeira entrada; a partir daqui, toda mudança relevante
é registrada aqui antes de cada release.

## [2.0.2-beta.3] — pré-lançamento, não visível por padrão no HACS

Correções de bugs reais relatados em testes da v2.0.2-beta.2, todos na
funcionalidade nova de leitura legada de EEPROM.

### Corrigido
- **"Não foi possível conectar" ao tentar sincronizar zonas ou ler
  eventos** (leitura legada): a implementação original abria uma
  conexão TCP isolada e separada da persistente — mas a central só
  aceita um cliente conectado por vez, então a segunda conexão sempre
  falhava enquanto o polling normal já estava rodando. Corrigido
  reaproveitando a conexão persistente já existente (`self.client`),
  igual às demais famílias — bate, inclusive, com o que a própria
  captura real do app oficial mostrou (status normal e comandos `0xE7`
  na mesma conexão).
- **Botão "Sincronizar nomes de zona" não aparecia** para centrais
  usando o caminho legado (senha de leitura configurada): a condição
  que decide se o botão é criado só checava `supports_extended_eeprom`,
  nunca foi atualizada para incluir `supports_legacy_eeprom`. Mesmo
  problema também corrigido em mais dois pontos que tinham a mesma
  lacuna: a sincronização automática na configuração inicial
  (`__init__.py`) e a disponibilidade da entidade "Últimos eventos"
  (`sensor.py`), que ficaria sempre indisponível mesmo depois de uma
  leitura de eventos bem-sucedida.

## [2.0.2-beta.2] — pré-lançamento, não visível por padrão no HACS

### Adicionado
- **Nomes de zona/usuário e log de eventos para modelos/firmwares fora
  do limiar do `0x5C`** (ex.: AMT 1016 NET com firmware antigo, que
  antes ficava totalmente sem essa função). Novo caminho alternativo,
  via protocolo legado (`0xE7` + identificação por senha de 6 dígitos),
  confirmado funcionando de ponta a ponta em hardware real — leitura
  completa de zonas, usuários e eventos, com texto batendo exatamente
  com os nomes configurados na central.
  - Novo módulo `protocol_legacy_eeprom.py`: framing, CRC próprio deste
    protocolo (peculiaridade real: os 2 primeiros bytes carregam sem
    passar pelo laço de deslocamento de CRC), autenticação (senha com
    dígito `'0'` trocado por `'A'` antes de codificar — achado que
    faltava numa tentativa anterior), leitura paginada, parsing de
    nomes e eventos. Tudo validado byte a byte contra uma leitura real
    completa fornecida pelo usuário antes de ser integrado.
  - Novo campo de configuração **opcional**, em branco por padrão:
    "Senha de leitura de mensagens (6 dígitos)" — só ativa essa função
    se preenchido explicitamente; não afeta nenhuma central que já
    tenha acesso normal via `0x5C`.
  - Usa uma conexão TCP **isolada e descartável**, própria para essa
    operação — nunca a conexão persistente usada no polling normal, e
    só roda sob demanda (botão de sincronizar zonas / serviço
    `read_events`), nunca durante o ciclo de consulta regular.

## [2.0.2-beta.1] — pré-lançamento, não visível por padrão no HACS

### Adicionado (nesta rodada)
- 5 novos códigos de evento confirmados em `protocol.EVENT_CODE_TABLE`
  (leitura de eventos via EEPROM), a partir de um trabalho paralelo de
  captura própria — mesma metodologia dos 17 originais: `9`→`3333`
  ("Restauração problema em teclado ou receptor"), `47`→`3361` ("Keep
  alive ethernet recuperado"), `158`→`1354` ("Falha ao comunicar
  evento"), `165`→`1621` ("Reset do buffer de eventos"), `175`→`1361`
  ("Falha keep alive ethernet"). Tabela agora com 22 códigos
  confirmados (era 17).

### Corrigido (nesta rodada)
- **Atribuição errada no byte `45`**: mapeava para o código `3333`
  ("Restauração problema em teclado ou receptor") — na verdade
  corresponde ao código `3531` ("Dispositivo Encontrado"). O código
  `3333` correto é o byte `9` (novo, ver acima).

### Corrigido
- **Resposta de status com tamanho inesperado** (ex.: bug conhecido do
  firmware 6.2 da AMT 4010 SMART) deixa de ser tratada como "sucesso com
  campos zerados" e passa a ser tratada como falha de leitura, igual a
  uma queda de conexão — cai no mesmo mecanismo de tolerância já
  existente (`_handle_poll_failure`). Antes desta correção, uma resposta
  truncada podia fazer uma entidade mostrar um valor **errado** por um
  ciclo de polling (ex.: zona aberta aparecendo como fechada), com risco
  real de disparar automações por engano. Agora: uma ocorrência isolada
  não altera nenhum valor de entidade (mantém o último dado bom
  conhecido); só escala para "indisponível" se o problema persistir além
  da janela de tolerância (10s por padrão — ajustado de 8s durante o
  período de teste desta pré-lançamento, mesma versão) — mesma proteção
  contra travamento silencioso já usada para quedas de conexão reais.
- **CPU alta com o switch "Conexão com a central" desligado** (bug real
  relatado em produção): desligar o switch fazia cada tentativa de
  consulta falhar rapidamente (sem tentar se comunicar de verdade), mas o
  **agendador** do próprio Home Assistant (`DataUpdateCoordinator`)
  continuava se reagendando sozinho — como cada tentativa desabilitada
  termina em ~0,000s, isso criava um laço apertado (milhares de chamadas
  por segundo, confirmado em log real), consumindo CPU à toa mesmo sem
  nenhuma tentativa de rede. Corrigido interrompendo o agendamento por
  completo (`coordinator.pause_polling()`/`resume_polling()`) ao
  desligar/religar o switch — e também na inicialização, se a integração
  já subir com o switch desligado, evitando o mesmo laço desde o início.

### Adicionado
- Novo código de evento na tabela do Receptor IP: `3531` ("Dispositivo
  Encontrado").

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
