# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado nesta primeira entrada; a partir daqui, toda mudança relevante
é registrada aqui antes de cada release.

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
