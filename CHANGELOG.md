# Changelog

Este projeto passa a seguir [Versionamento Semântico](https://semver.org/lang/pt-BR/)
a partir da v2.0.0 — a primeira versão pública, liberada para a comunidade
via HACS.

O histórico de desenvolvimento anterior a esta versão (v1.6.0–v1.8.3) foi
consolidado na entrada v2.0.0; a partir daqui, toda mudança relevante é
registrada aqui antes de cada release.

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
