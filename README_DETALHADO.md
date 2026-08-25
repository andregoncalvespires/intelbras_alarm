# Intelbras Alarm (ISECNet) — Home Assistant

<p align="center">
  <img src="docs/images/banner.png" alt="Intelbras Alarm Integration — central Intelbras AMT 4010 SMART conectada ao Home Assistant Core" width="400">
</p>

> ## ⚠️ Responsabilidade sobre o uso da integração e garantia
>
> **Este projeto NÃO tem participação alguma da Intelbras.**
>
> - A decisão de uso é totalmente de responsabilidade do usuário.
> - O responsável pelo repositório e eventuais colaboradores não são nem
>   serão responsáveis por eventuais sinistros após a instalação da
>   integração.
> - A integração possui conexão direta com a central de segurança, usando
>   a senha que o próprio usuário informa. O uso inadequado de suas
>   funcionalidades pode comprometer sua segurança.
> - Garanta que as práticas de segurança e uso da central permaneçam
>   adequadas com a utilização da integração.
> - **Ao instalar e configurar esta integração, você está ciente e
>   aceitando estes termos.**

Integração nativa (custom component / HACS) para centrais de alarme Intelbras
**AMT 1016 NET, AMT 2018 E/EG, ANM 24 Net, AMT 4010 SMART** e outros
modelos da mesma família (ver lista completa mais abaixo),
via protocolo **ISECNet/ISECMobile** (o mesmo usado pelo app AMT Mobile) —
conexão TCP persistente direta com a central, dentro do próprio ciclo de
vida do Home Assistant.

A integração usa as entidades **padrão do próprio Home Assistant** para
representar uma central de alarme como ela deveria ser representada:
`alarm_control_panel` para a central e cada partição, com os estados de
uma central de segurança de verdade (`disarmed`, `armed_away`,
`armed_home`, `triggered`), suporte a senha/código para armar e desarmar
(opcional, configurável por ação), zonas como `binary_sensor`, saídas
programáveis (PGM) e sirene como `switch`, e diagnósticos completos da
central (rede elétrica, bateria, tamper, sabotagem, expansoras, etc.) como
entidades próprias — nada de sensores genéricos tentando imitar um painel
de alarme por fora.

> Baseado no documento oficial *"Descrição de Comandos de Protocolo ISECnet
> Centrais de Alarmes – Intelbras Receptor IP"* (AMT2018 E/EG e AMT4010
> Smart, Revisão 15) e em capturas reais de tráfego (nomes de zona via
> EEPROM, validação de bits de status). Ver seção "Créditos" no final.

**Modelos/firmwares realmente testados até agora:**

| Modelo | Firmware | Observação |
|---|---|---|
| AMT 1016 NET | 3.1 | — |
| AMT 2018 E/EG | 4.7 | — |
| AMT 4010 SMART | 5.2 | — |
| AMT 4010 SMART | 6.2 | Esse firmware apresentou comportamento incorreto: enviava uma resposta de status menor que o esperado aleatoriamente. Uma resposta assim **não é mais aceita como status válido** — é tratada como falha de leitura isolada (mesmo mecanismo de tolerância usado para quedas de conexão, ver seção "Tolerância a falhas passageiras"), então nenhuma entidade chega a mostrar um valor incorreto por causa disso; o próximo ciclo de polling (a cada 0,25s por padrão) normalmente já traz a leitura completa de novo. |

Os demais modelos suportados pelo protocolo (ANM 24 Net, AMT 2018 E
Smart, AMT 2008 RF, AMT 2010, AMT 2018 base, AMT 2110, AMT 2118 EG, AMT
3010, AMT 2018 E3G, GPRS 1000 UN) seguem a mesma estrutura, mas ainda não
foram validados em hardware real — o suporte a eles não é bloqueado por
isso, é só para ter uma referência caso algum problema seja relatado.
Esta tabela vai sendo atualizada conforme outros usuários testarem e
relatarem outros modelos/firmwares.

> ⚠️ **AMT 2018 E Smart** tem uma ressalva técnica própria — ver seção
> "Modelos suportados e engenharia reversa por modelo" mais abaixo.

![Tela de configuração da integração](docs/images/tela-configuracao-1.png)
![Tela de configuração, rolada para baixo: zonas habilitadas e opções do Receptor IP](docs/images/tela-configuracao-2.png)

---

## Modelos suportados e engenharia reversa por modelo

Além das capturas reais e da documentação oficial, esta lista foi
fechada com engenharia reversa direta do app oficial (`AMT Mobile`
v3.4.2.2) — especificamente `Constantes$PanelModelId` (a lista completa
de modelos que o app reconhece), `Painel`/subclasses (`Amt2018`,
`Amt2018ESmart`, `Amt4010`, `Anm24Net`, `Amt8000`), e
`CentralMenuActivity` (`isPanelUsing5c`, `fixModelIdIfIncorrect`,
`goToSyncNames`).

### O app reconhece 19 modelos — reconstruído aqui como a família 2018

O app oficial internamente instancia **uma classe Java por modelo/grupo
de modelos**, e cada classe implementa seu próprio comando de status,
parsing de zonas, etc. — **não é uma correspondência 1:1 entre "modelo"
e "comportamento"**. O achado mais importante: a classe `Amt2018` (a
mesma já usada e validada para AMT 2018 E/EG e AMT 1016 NET) é
literalmente o **fallback padrão** do próprio app para todo modelo que
não é um caso especial — usa o comando `0x5A`, 48 zonas, nos mesmos
offsets de byte, **hardcoded, sem nenhuma ramificação por modelo
específico dentro da classe**. Foi isso que nos deu confiança pra
adicionar os 8 bytes abaixo sem precisar de hardware pra validar cada
um individualmente — são literalmente o mesmo código-fonte.

| Byte | Modelo | Confiança |
|---|---|---|
| `0x1E` | AMT 2018 E/EG | Testado em hardware real |
| `0x61` | AMT 1016 NET | Testado em hardware real |
| `0x41` | AMT 4010 SMART | Testado em hardware real |
| `0x24` / `0x25` | ANM 24 Net / ANM 24 Net G2 | Confirmado por captura real (status básico); sincronização de nomes usa protocolo próprio, não implementado — ver abaixo |
| `0x34` | AMT 2018 E Smart | Engenharia reversa, comando de status diferente (ver seção própria abaixo) — não testado |
| `0x04` | GPRS 1000 UN | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x08` | AMT 2008 RF | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x10` | AMT 2010 | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x18` | AMT 2018 (base) | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x20` | AMT 2110 | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x2E` | AMT 2118 EG | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x30` | AMT 3010 | Engenharia reversa (mesma classe `Amt2018`), não testado |
| `0x32` | AMT 2018 E3G | Engenharia reversa (mesma classe `Amt2018`), não testado |

### AMT 2018 E Smart (byte `0x34`) — comando de status diferente, mesmos offsets

Essa central usa um comando de status **diferente** do resto da família
2018: `0x5D` (93 decimal — `const.CMD_STATUS_ESMART`), não `0x5A`. A
resposta também é bem mais longa: `Amt2018ESmart.updateStatusAttributes()`
(decompilado do app oficial) referencia posições como `p13.get(94)`, com
uma checagem `if (p13.size() > 135)` — ou seja, mais de 135 bytes, contra
os 43 da família 2018 padrão.

A primeira análise deste projeto concluiu que isso tornava o modelo
incompatível e chegou a **removê-lo** da integração. Uma segunda análise,
mais cuidadosa, comparou posição por posição os campos que
`Amt2018ESmart.updateStatusAttributes()`/`updateBatteryStatus()`/
`updateProblems()` realmente leem contra os offsets que esta integração
usa (`protocol.parse_status_2018()`) — e todos batem exatamente:

| Campo | Posição no app (`p13.get(N)`) | Posição nesta integração (`content[N-2]`) | Bate? |
|---|---|---|---|
| Firmware | `21` | `19` | ✅ |
| Central particionada | `22`, bit 0 | `20` (status21), bit 0 | ✅ |
| Partição A ativada | `23`, bit 0 | `21` (status22), bit 0 | ✅ |
| Partição B ativada | `23`, bit 1 | `21` (status22), bit 1 | ✅ |
| Sirene disparada | `39`, bit 2 | `37` (status38), bit 2 | ✅ |
| Falta de rede elétrica | `30`, bit 0 | `28` (status29), bit 0 | ✅ |

(O deslocamento de `-2` entre as duas colunas é porque a lista do app
inclui `[Nº Bytes][echo]` no início, que nesta integração já são
removidos por `protocol.parse_frame()` antes de chegar em `content`.)

Os únicos campos **exclusivos** desse modelo (Stay por partição —
`p13.get(94)`/`(95)` — e um bloco de "status de rede geral", só presente
quando a resposta passa de 135 bytes) ficam em posições bem depois de
tudo que já lemos. Ou seja: **o conteúdo extra é estritamente adicional,
não um layout diferente** — o mesmo `protocol.parse_status_2018()` já
usado para toda a família 2018 funciona sem nenhuma alteração de offset,
bastando aceitar uma resposta mais longa como válida (em vez de exigir
exatamente 43 bytes) e mandar `0x5D` em vez de `0x5A` para esse modelo
específico.

**Implementação**: `const.MODEL_STATUS_CMD_OVERRIDE` (comando por
modelo, checado antes do padrão da família) e
`const.MODEL_STATUS_MIN_LEN_OVERRIDE` (tamanho mínimo aceito, em vez de
exato, só para este modelo). Na detecção automática
(`coordinator.async_detect_model()`), `0x5D` é tentado como terceira
opção, depois de `0x5A` e `0x5B` já terem dado uma resposta parseável
mas com modelo não reconhecido.

**Ainda em aberto**: não sabemos com certeza como uma central real reage
ao receber `0x5A` "por engano" antes da detecção descobrir que precisa
tentar `0x5D` (NACK explícito, silêncio, ou uma resposta ainda assim
válida) — a estratégia de detecção atual só chega a tentar `0x5D` se
`0x5A` falhar de forma "limpa" (resposta parseável, modelo
desconhecido), não se falhar com um erro de conexão mais duro. `AMT 1000
Smart` (byte `0x36`) provavelmente compartilha esse mesmo comando (sua
classe `Amt1000Smart` estende `Amt2018ESmart`), mas ainda não está na
tabela — não confirmamos se o restante do parsing também é idêntico.
Não testado contra hardware real.

### AMT 2018 E Smart — dados adicionais (rede, celular, zonas sem fio)

A resposta `0x5D` carrega bem mais dados do que os 43 bytes padrão da
família 2018 — até ~204 bytes, cobrindo diagnóstico de rede/celular e
atributos extras de zona. Confirmado por engenharia reversa direta
(`Amt2018ESmart.updateZonesDevicesStatus()`/`updateGeneralNetworkStatus()`),
cruzado com uma captura real fornecida pelo usuário (checksum e byte de
modelo confirmados, mas curta demais — só 95 bytes — para validar os
valores dessas seções extras).

**A resposta real varia de tamanho** — já observamos uma captura válida
bem mais curta que o "tamanho completo" teórico. Por isso a validação
desta integração (`const.MODEL_STATUS_MIN_LEN_OVERRIDE`) exige só o
mínimo de 43 bytes (o mesmo da família 2018 padrão), não um valor mais
alto — cada seção abaixo simplesmente fica ausente/vazia se a resposta
não for longa o bastante pra alcançá-la, sem gerar erro algum
(`protocol.parse_status_2018_esmart_extra`).

**Rede e celular** — duas entidades novas de diagnóstico, só criadas pra
esse modelo: **"Rede (diagnóstico)"** (tipo de conexão, status online de
cada link Ethernet/celular/Cloud, IP, máscara, gateway, DNS1/2, MAC) e
**"Módulo celular (diagnóstico)"** (tipo do módulo, sinal, chip em uso,
operadora, Chip ID/ICCID, IMEI). Todos os offsets (bytes 136-203 na
numeração do app) foram confirmados byte a byte, decompilando
`updateGeneralNetworkStatus()` — inclusive a fórmula de IP/máscara/
gateway/DNS (4 bytes cada) e o esquema de Chip ID/IMEI (cada caractere é
o código ASCII bruto do dígito, não BCD).

**Atributos extras nas zonas 25-48** — a central trata as zonas 1-24
como sempre fiadas; só 25-48 têm essa telemetria adicional (`sem_fio`,
`tamper_esmart`, `curto_circuito_esmart`, `bateria_baixa_esmart`,
`supervisionada`, `falha_supervisao`, `modelo_dispositivo`) como
atributos extras na própria entidade de zona já existente (não são
entidades novas). Deliberadamente **não implementamos** o campo de nível
de sinal RF por zona (byte 108) — o app usa um contador condicional mais
complexo pra indexar esse campo específico (só incrementa para zonas que
já passaram por outras condições), com risco maior de erro sem hardware
real pra validar; os demais campos usam um padrão bem mais simples (1
bit por zona, a cada 8 zonas), que replicamos com confiança.

**Stay reportado pela central** — atributo novo `stay_reportado_pela_central`
nas entidades de partição (e `stay_reportado_particao_a`/`_b` na central).
Diferente do estado `armed_home` já existente (que usa o controle local
desta integração, lembrando qual foi o último comando enviado — o único
mecanismo que funciona pra todos os outros modelos, já que eles não
reportam isso na resposta), esse atributo novo reflete o que a **própria
central diz** sobre o modo Stay de cada partição (byte 94 da resposta).

**Achado que precisa de confirmação em campo**: na captura real fornecida
pelo usuário, o byte correspondente às "zonas sem fio 25-31" veio como
`0x7F` (não-zero) — um valor genuíno, não um erro de leitura, mas sem
como confirmar se aquela central específica realmente tinha zonas
sem fio configuradas nessa faixa no momento da captura. Vale checar
isso contra a realidade da instalação, se possível.

**Nenhuma dessas três frentes foi testada contra hardware real** — só
validadas via engenharia reversa do app oficial e testes isolados com
dados simulados/parciais (o exemplo real disponível é curto demais para
cobrir a maior parte dos campos). Ver `CHANGELOG.md`.

### ANM 24 Net — status básico compatível, sincronização de nomes não

A ANM 24 Net usa o **mesmo comando de status** (`0x5A`) e os **mesmos
offsets de byte** da família 2018 — confirmado decompilando
`Anm24Net.updateZones()`, que é estruturalmente idêntico ao de `Amt2018`,
só com **24 zonas em vez de 48** (bate com o nome: "24 Net"). Por isso
está na tabela como suportada para status/arme/desarme.

Só a sincronização de nomes de zona/usuário é diferente: o app usa
comandos próprios e exclusivos para essa central
(`montarSincronismoZonaAnm24Net`, `montarSincronismoUsuarioAnm24Net`,
`montarSincronismoNomeCentralAnm24Net`) — nem o comando moderno `0x5C`
nem o protocolo legado `0xE7` que já implementamos. Não decifrado ainda;
nomes de zona/eventos não funcionam nesta central via nenhum dos dois
caminhos existentes.

### Correção de nome: "ANM 24 Net", não "AMN 24 NET"

O nome real, tanto no enum interno do app quanto no texto exibido pra o
usuário, é **"ANM 24 Net"** — este projeto usava "AMN 24 NET" (letras
trocadas) desde o início. Corrigido a partir desta versão; puramente
cosmético, não muda nenhum comportamento.

---

## Instalação

### Via HACS (repositório customizado)
1. HACS → Integrações → menu (⋮) → **Repositórios customizados**.
2. Adicione a URL do seu repositório Git com esta pasta, categoria **Integração**.
3. Instale "Intelbras Alarm (ISECNet)" e reinicie o Home Assistant.

### Manual
1. Copie a pasta `custom_components/intelbras_alarm` para
   `<config>/custom_components/intelbras_alarm` na sua instalação.
2. Reinicie o Home Assistant.

### Configuração
1. **Ajustes → Dispositivos e Serviços → Adicionar Integração → Intelbras Alarm**.
2. Informe:
   - **Endereço IP** da central (módulo Ethernet/Wi-Fi já configurado com IP fixo é recomendado).
   - **Porta** (padrão `9009`, a mesma usada pelo AMT Mobile/Receptor IP — ajuste se a sua central usa outra).
   - **Senha** (a mesma do app AMT Mobile, 4 a 6 dígitos).
3. A integração **detecta automaticamente o modelo** (envia `0x5A`; se a
   central responder "comando descontinuado" [`0xE5`], ela é uma AMT 4010 e
   o comando `0x5B` é usado) e define o número de zonas e partições
   conforme o modelo — **não há campo manual para isso**.
4. Ainda na tela inicial, duas opções controlam se o Home Assistant deve
   **pedir a senha na interface** ao ativar e/ou ao desativar a central:
   - Nenhuma marcada (padrão) → a senha memorizada é usada automaticamente
     em todos os comandos, sem pedir nada na UI (equivalente ao
     comportamento de um app que já está logado).
   - **"Exigir senha ao desativar"** marcada → o teclado numérico aparece
     ao desarmar, e o valor digitado é enviado à central **como a própria
     senha do comando** — não precisa ser igual à senha memorizada na
     configuração. É a própria central quem aceita ou rejeita (útil se
     ela tiver mais de uma senha cadastrada, ex.: uma senha secundária de
     usuário). Se a central recusar, o Home Assistant mostra o motivo
     (ex.: "Senha incorreta").
   - **"Exigir senha ao ativar"** marcada → o teclado aparece ao armar, com
     o mesmo comportamento acima.
     ⚠️ Limitação da própria API `alarm_control_panel` do Home Assistant:
     se **só** esta opção for marcada (sem a de desarmar), o teclado
     também aparece ao desarmar — mas nesse caso o valor digitado é
     **ignorado**, e a senha memorizada é usada automaticamente para
     desarmar (ou seja, qualquer coisa digitada ali desarma, sem checagem).
     Isso porque o HA usa um único `code_format` por entidade, compartilhado
     entre ativar e desativar; só o *requisito de preenchimento* pode ser
     independente por ação, não o formulário em si. Para exigir senha só
     ao desarmar (o caso mais comum), marque **apenas** essa opção — esse
     caso funciona exatamente como esperado, sem pedir nada ao armar.
   - Essas duas opções só podem ser definidas **na inclusão da central**;
     para alterá-las depois, remova e adicione a integração novamente.
5. **Só para a família 4010**, um segundo passo pergunta **senhas por
   partição** (A/B/C/D), todas opcionais. Se a central tiver senhas
   diferentes cadastradas por partição, informe aqui — a integração passa
   a usar a senha específica ao ativar/desativar aquela partição
   automaticamente. Deixar em branco usa a senha principal para aquela
   partição. Isso não interfere com "Exigir senha ao ativar/desativar": se
   marcado, o valor digitado na UI continua tendo prioridade (ver item 4).
7. Em **Configurar** na própria integração (Ajustes → Dispositivos e
   Serviços → Intelbras Alarm → Configurar) é possível ajustar, **sem
   remover e reconfigurar a integração do zero**:
   - a **senha principal** — validada contra a própria central antes de
     salvar (reaproveitando a conexão TCP persistente já aberta, sem
     abrir uma segunda — ver ressalva abaixo), para não gravar uma senha
     errada e só descobrir depois;
   - as **senhas por partição** (só 4010);
   - as opções de **exigir senha ao ativar/desativar**;
   - o **intervalo de consulta de status (polling)** — sugerido e padrão
     **0,25 s**, o mesmo valor usado pelo app oficial AMT Mobile.

   O endereço IP, a porta e o modelo detectado não são editáveis por ali
   de propósito — trocar de central é melhor tratado removendo e
   reconfigurando a integração do zero.

   **"Zonas habilitadas por padrão" também não está editável ali**: esse
   campo só tem efeito no momento em que as entidades de zona são criadas
   pela primeira vez (`entity_registry_enabled_default`, um valor que o
   Home Assistant só lê na primeira vez que grava a entidade no
   registro — mudar isso depois, num reload, não reabilita/desabilita
   nada em entidades que já existem). Deixar esse campo na tela de
   "Configurar" pareceria funcionar (salva, recarrega, sem erro) mas não
   teria efeito nenhum visível — por isso foi retirado de lá.

   **Validação de senha reaproveita a conexão existente**: a primeira
   versão desta tela abria uma **segunda conexão TCP** só para testar a
   senha nova (a mesma função usada para detectar o modelo na
   configuração inicial). Isso falhava sistematicamente, porque a central
   só aceita **um cliente conectado por vez** — o mesmo motivo por trás do
   problema com o app AMT Remoto documentado na seção "Comportamento em
   reinícios". Corrigido: a validação agora monta um comando de consulta
   de status com a senha candidata e o envia pela conexão persistente já
   aberta do coordinator (`coordinator.async_validate_password()`) — o
   protocolo ISECMobile leva a senha em cada frame, não na conexão TCP em
   si, então isso funciona sem precisar de uma segunda conexão.

---

## Entidades criadas

> 📖 As entidades `alarm_control_panel` usadas aqui são o tipo **padrão**
> do Home Assistant, não algo customizado desta integração — a
> [documentação oficial](https://www.home-assistant.io/integrations/alarm_control_panel/)
> descreve o comportamento genérico (estados, o parâmetro `code`,
> gatilhos/condições/ações padrão do domínio `alarm_control_panel`,
> exemplos de automação). O que segue aqui é específico desta integração:
> quais desses estados/recursos genéricos a central realmente entrega, e
> como.

| Plataforma | Entidade | Observações |
|---|---|---|
| `alarm_control_panel` | Central (dispositivo principal) | estados: `disarmed`, `armed_away`, `armed_home`, `triggered` — `armed_home` só disponível em AMT 4010 SMART e AMT 2018 E SMART (ver seção "Modo Stay por partição") |
| `alarm_control_panel` | Partição A/B (e C/D na 4010) | uma entidade por partição, só criada se a central estiver **particionada** (`<Partição habilitada>` = 1); mesmos estados e mesma restrição de `armed_home` por modelo da central acima |
| `switch` | PGM 1..N | N = 2 (2018/1016/SMART) ou até 19 (4010, conforme expansoras); comando `0x50`. **PGM 4 a 19 vêm desabilitadas por padrão** (Configurações → Entidades → mostrar desabilitadas para ativar as que sua instalação usa) — a funcionalidade existe para as 19, mas a central não informa quantas expansoras existem de verdade, então evitamos poluir a lista com entidades provavelmente inúteis |
| `switch` | Sirene | comandos `0x43`/`0x63`; status lido do Status38 bit 2 (2018/1016) ou Status46 bit 2 (4010) |
| `switch` (categoria **Configuração**) | Conexão com a central | liga/desliga a comunicação TCP (manutenção/teste); ao desligar, as demais entidades ficam indisponíveis; **estado persistido** — se desligado antes de um reinício do Home Assistant, permanece desligado e não tenta reconectar automaticamente (ver seção "Comportamento em reinícios" abaixo) |
| `binary_sensor` | Zona 01..N (`device_class: opening`) | N = 48 (toda a família 2018/1016) ou 64 (4010) — limite do protocolo por família, conforme documentado e validado em campo. **Zonas habilitadas por padrão configuráveis na inclusão da integração** (formato `1-5;8;10-15`, padrão `1-8;17-24`); as demais são criadas desabilitadas (Configurações → Entidades → mostrar desabilitadas para ativar as que sua instalação usa). Atributos: violada, anulada/bypass, e (só quando aplicável à faixa da zona) bateria baixa, tamper, curto-circuito |
| `binary_sensor` | Central disparada | bit 6 do Status23/30 **E** sirene realmente tocando (Status38/46 bit 2) — ver seção "Leitura do Status22/23" |
| `binary_sensor` | Alguma zona aberta | bit 2 do Status23/30 — sinal rápido agregado; diferente do bitmap por zona (Zona 01..N acima) e do contador `sensor` Zonas abertas |
| `binary_sensor` | Particionamento habilitado | reflete `<Partição habilitada>` (Status21/27) |
| `binary_sensor` | Rede elétrica, Bateria fraca, Bateria ausente/invertida, Curto na bateria, Sobrecarga aux., Problema na central | diagnóstico, `entity_category: diagnostic` |
| `binary_sensor` | Corte no fio da sirene, Curto-circuito no fio da sirene, Corte na linha telefônica, Falha ao comunicar evento | diagnóstico (Status33 legado / Status43 na 4010) |
| `binary_sensor` | Problema no teclado 1-4 / Problema no receptor 1-4 | diagnóstico (Status30 legado / Status37 na 4010); teclado tem atributo `tamper` |
| `binary_sensor` | Problema no expansor de PGM 1-4 / Problema no expansor de zonas 1-6 | só família 4010 (Status38/39) |
| `sensor` | Bateria (%) | diagnóstico; zera automaticamente se a bateria estiver ausente/invertida OU em curto (ver seção específica abaixo) |
| `sensor` | Zonas abertas / Zonas violadas / Zonas anuladas / Zonas com bateria baixa (contadores) | diagnóstico; atributo `zonas` com a lista dos números das zonas naquele estado (e `zonas_nomes` também, se a central informar nomes — família 4010), "Zonas com bateria baixa" soma o bitmap de sensores sem fio (Status39-43 na 2018/1016, Status47-52 na 4010 — só zonas 17-64 na 4010, que é a única faixa com sensor sem fio nesse modelo) |
| `sensor` | Último comando | diagnóstico — grava a **ação enviada** assim que o comando sai (ex.: `"Ativar Partição A..."`) e depois **atualiza** com o resultado (ex.: `"Ativar Partição A: OK"` ou `"Ativar Partição A: Senha incorreta"`) |
| `sensor` | Últimos eventos | diagnóstico — só nos modelos/firmwares com acesso ao comando `0x5C` para eventos (ver seção "Nomes de zona e log de eventos" abaixo); fica indisponível nos demais. Estado = evento mais recente; atributo `eventos` = lista dos `EVENT_ENTITY_RECENT_COUNT` (24) mais recentes. Atualizada pelo serviço `intelbras_alarm.read_events`, não pelo polling normal |
| `sensor` | Rede (diagnóstico) / Módulo celular (diagnóstico) | **só na AMT 2018 E SMART** — diagnóstico; tipo de conexão/status dos links/IP/MAC no primeiro, tipo de módulo/sinal/operadora/Chip ID/IMEI no segundo (nos atributos). Ver seção "AMT 2018 E Smart — dados adicionais". Não testado contra hardware real |
| `button` | Pânico silencioso / audível / emergência médica / incêndio | comando `0x45` |
| `button` | Anular zonas abertas / Anular zonas violadas / Anular zonas abertas ou violadas | comando `0x42`; preserva anulações já existentes em outras zonas; o terceiro botão une os dois conjuntos numa única operação (evita que uma anulação desfaça a outra, já que o comando é absoluto) |
| `button` | Remover todas as anulações de zona | comando `0x42`; reativa **todas** as zonas de uma vez (não pede número de zona) |
| `button` | Sincronizar nomes de zona | só nos modelos/firmwares com acesso ao comando `0x5C` para isso — ver seção "Nomes de zona e log de eventos" abaixo (**não** é mais "só família 4010"; passou a valer para toda a lista, incluindo 2018 EG e ANM 24 Net, com as ressalvas de firmware) |

> Todos os `button` acima ficam **indisponíveis** quando a comunicação com
> a central não está ativa (switch desligado, ou falha de conexão) — não
> aparecem "prontos para uso" sem realmente conseguir entregar o comando.

> Duas partes da documentação genérica do `alarm_control_panel` que
> **não** se aplicam a esta integração: os modos `armed_night`,
> `armed_vacation` e `armed_custom_bypass` (a central só expõe
> away/home/disarmed/triggered — ver tabela acima) e o atributo
> `changed_by` (o protocolo ISECNet não informa quem alterou o estado da
> central, então não é preenchido).

### Serviço `intelbras_alarm.bypass_zone` — anular/reativar uma ou mais zonas

Para anular ou reativar **zonas específicas por número** (algo que não
cabe bem numa entidade fixa, já que são até 64 zonas possíveis), a
integração registra um **serviço**, chamável de automações, scripts, ou da
aba **Ferramentas de desenvolvedor → Ações** do próprio Home Assistant.
Aceita **uma ou várias zonas na mesma chamada** — intervalos e/ou números
individuais separados por `;` (ex.: `1-5;8;10-15`). Isso importa porque o
comando `0x42` é absoluto: anular a zona 5 e, em seguida, a zona 8 em duas
chamadas separadas faria a segunda desfazer a anulação da primeira; juntar
as duas no mesmo `zones: "5;8"` evita esse problema.

```yaml
service: intelbras_alarm.bypass_zone
target:
  entity_id: alarm_control_panel.central   # ou qualquer alarm_control_panel desta central/partição
data:
  zones: "1-5;8;10-15"   # intervalos e/ou números separados por ;
  bypass: true            # true = anular, false = reativar (padrão: true)
```

Exemplo de uso em automação (anular a zona 5 automaticamente ao armar em
modo Stay, por exemplo, para uma janela que fica aberta à noite):

```yaml
automation:
  - alias: "Anular zona 5 ao armar em modo Stay"
    trigger:
      - trigger: state
        entity_id: alarm_control_panel.central
        to: armed_home
    action:
      - action: intelbras_alarm.bypass_zone
        target:
          entity_id: alarm_control_panel.central
        data:
          zone: 5
          bypass: true
```

Este serviço **sempre usa a senha memorizada** na configuração — não é
afetado pelas opções "Exigir senha ao ativar/desativar" (essas só valem
para os comandos de ativação/desativação, ver seção de Instalação).
Preserva anulações já existentes em outras zonas, e devolve um erro
amigável se a zona informada estiver fora do intervalo válido para o
modelo detectado.

> **Nota de versão**: as primeiras versões desta funcionalidade também
> incluíam uma entidade `select` ("Zona selecionada") e dois botões
> ("Anular zona selecionada"/"Reativar zona selecionada") para escolher a
> zona pelo dashboard, sem precisar chamar o serviço manualmente. Foram
> removidas: o botão de anular funcionava, mas o de reativar não
> respondia ao clique (sem erro nos logs), e a causa não foi identificada
> com segurança por revisão de código. Em vez de manter uma funcionalidade
> parcialmente confiável, o caminho recomendado agora é o serviço acima —
> que funciona de forma consistente e testada tanto via automação quanto
> via Ferramentas de desenvolvedor. O botão "Remover todas as anulações de
> zona" (que não depende de escolher uma zona) continua disponível e
> funciona normalmente.

### Serviço `intelbras_alarm.send_raw_command` — diagnóstico avançado

Ferramenta pensada para **testar comandos ISECNet ainda não
implementados/documentados** pela integração — reaproveita a mesma
conexão persistente já aberta (nunca abre uma segunda) e devolve a
**resposta bruta** da central via [resposta de serviço](https://www.home-assistant.io/docs/scripts/service-calls/#use-templates-to-handle-response-data)
(`response_variable` numa automação/script, ou direto na aba Ferramentas
de desenvolvedor → Ações).

⚠️ **Contorna todas as validações normais da integração de propósito** —
não injeta senha automaticamente (a menos que você peça), não monta
checksum (a menos que você peça), não valida se o comando é conhecido.
A central executa o que for enviado. Não é uma ferramenta para uso no
dia a dia — é para quem está investigando/testando algo específico do
protocolo.

Três modos de uso, mutuamente exclusivos:

**1. Frame completo, cru** — envia exatamente os bytes informados, sem
tocar em nada (nem senha, nem checksum):

```yaml
service: intelbras_alarm.send_raw_command
target:
  entity_id: alarm_control_panel.central
data:
  frame: "08 E9 21 31 32 33 34 42 21 5B"
```

**2. Frame quase completo, com checksum calculado automaticamente** —
digite o cabeçalho, comando e conteúdo à mão, termine com qualquer byte
de preenchimento (ex.: `FF`) no lugar do checksum, e marque
`calculate_checksum: true` — a integração recalcula e substitui só o
último byte:

```yaml
service: intelbras_alarm.send_raw_command
target:
  entity_id: alarm_control_panel.central
data:
  frame: "08 E9 21 31 32 33 34 42 21 FF"
  calculate_checksum: true
```

**3. Comando + conteúdo, resto montado pela integração** — só o byte de
comando e o conteúdo são "crus"; cabeçalho, senha (a memorizada, a menos
que `password` seja informado) e checksum são montados automaticamente,
do mesmo jeito que qualquer outro comando já implementado:

```yaml
service: intelbras_alarm.send_raw_command
target:
  entity_id: alarm_control_panel.central
data:
  command: "0x42"
  content: "01 02 03"
```

Os três modos aceitam hex com ou sem espaços, vírgulas, ponto-e-vírgula
ou prefixo `0x` por byte (`"08 E9 21"`, `"08,E9,21"` e `"08E921"` são
todos equivalentes).

Resposta devolvida (exemplo):

```yaml
frame_enviado: "08 E9 21 31 32 33 34 42 21 5B"
resposta_bruta: "0A FE 21 00"
checksum_valido: true
conteudo: "FE"
descricao: "OK"   # só presente quando a resposta é curta (tipo ACK/NACK)
```

Diferente dos demais comandos da integração, um **NACK aqui não vira
erro** — o objetivo é justamente ver a resposta (incluindo um NACK),
não interromper a chamada.

### Serviço `intelbras_alarm.read_events` — log de eventos

Só disponível nos modelos/firmwares com acesso ao comando `0x5C` para
isso — ver a tabela na seção "Nomes de zona e log de eventos" mais
abaixo. Lê o log de eventos **inteiro** (até 256 registros) a cada
chamada, sempre ordenado pela data/hora real decodificada de cada
evento (nunca pela ordem de endereço — ver aviso na mesma seção):

```yaml
service: intelbras_alarm.read_events
target:
  entity_id: alarm_control_panel.central
```

Resposta (exemplo, truncada):

```yaml
total_eventos: 87
eventos:
  - data_hora: "16/08/2026 00:00:01"
    zona_usuario: 0
    particao: "-"
    codigo: "1602"
    descricao: "Teste periódico"
  - data_hora: "15/08/2026 20:06:20"
    zona_usuario: 4
    particao: "D"
    codigo: "1401"
    descricao: "Desativação pelo usuário"
  # ...
```

Como efeito colateral, também atualiza a entidade **"Últimos eventos"**
com os `EVENT_ENTITY_RECENT_COUNT` (24) mais recentes — pensado para ser
chamado por uma automação no intervalo que você quiser (não há polling
automático de eventos, só quando o serviço é chamado explicitamente).

O campo `zona_usuario` é o número cru — pode ser uma **zona** ou um
**usuário**, dependendo do tipo de evento (ex.: em "Disparo de zona" é o
número da zona; em "Ativação pelo usuário" é o número do usuário). Esta
integração não resolve esse número para o nome correspondente (nem de
zona, nem de usuário) automaticamente — fica como número mesmo, para
manter o escopo desta primeira versão simples; o nome da zona pode ser
cruzado manualmente com as entidades de zona já existentes, se precisar.

O **modelo** e a **versão de firmware** detectados ficam no registro do
dispositivo (não como entidades separadas), visíveis em
*Dispositivos → Intelbras \<modelo\> (\<IP\>)*.

---

## Receptor IP — eventos empurrados pela central em tempo real

Diferente de todo o resto desta integração — onde **nós** somos o
cliente, conectando na central e perguntando o status — este recurso
inverte os papéis: a central é configurada (fora desta integração, no
teclado ou no app oficial, tela "Configurar central" → conta de
monitoramento IP) para conectar **nela mesma** num endereço/porta que
apontamos aqui. A partir daí, ela empurra eventos sozinha, sem
precisarmos ficar perguntando — o mesmo mecanismo usado por softwares de
monitoramento profissional (ex.: "Receptor IP" da própria Intelbras).

**Desligado por padrão** — ver `CONF_RECEPTOR_IP_ENABLED`/
`CONF_RECEPTOR_IP_PORT` em `const.py`, disponível tanto na configuração
inicial quanto na tela "Configurar" (reconfiguração). Diferente do campo
"zonas habilitadas por padrão" (que só funciona na configuração
inicial — ver seção acima), ligar/desligar isso na reconfiguração
**funciona de verdade**: não depende de nenhum `entity_registry_
enabled_default` travado na criação, é só iniciar ou parar um servidor
`asyncio` a cada recarregamento da integração, e qualquer mudança de
opção já dispara esse recarregamento automaticamente.

### Configuração na central (fora desta integração)

Habilitar a opção nesta integração só prepara o **lado que escuta** — a
central precisa ser configurada separadamente para saber que deve se
conectar aqui. Passo a passo pelo app **AMT Remoto** (o app de
configuração/instalador, diferente do AMT Mobile usado no dia a dia):

1. **Comunicação → Monitoramento IP → Servidor 2**:
   - `IP`: endereço IP do Home Assistant
   - `Porta`: a mesma configurada em `CONF_RECEPTOR_IP_PORT` (`9010` por
     padrão)
   - Desmarcar **"Utilizar endereço DNS"** (a integração espera conexão
     por IP direto, não resolve nome de domínio)
2. **Comunicação → Modo de Reportagem**: `"Duplo IP"`
3. **Ethernet → Configuração IP**:
   - `"Transmitir sinal de link Ethernet a cada"`: `1 minuto` — é este
     campo que controla a frequência do heartbeat (`0xF7`) que atualiza
     a entidade "Último sinal de vida (Receptor IP)"
   - `"Monitoramento do link (keep alive)"`: marcado, **se essa opção
     existir no seu modelo** — nem toda central tem esse campo
     disponível no AMT Remoto; se não aparecer, siga sem ele, sem
     problema

Passo a passo confirmado pelo usuário desta integração, configurando uma
central real. Se algum nome de campo ou caminho de menu tiver mudado em
versões mais recentes do AMT Remoto, os nomes dos comandos/telas
subjacentes (`0x94`, `0xB0`/`0xB4`, `0xF7`) continuam os mesmos — é só a
localização na interface do app que pode variar.

> 💡 **Rede com VLANs/segmentação**: diferente de toda a comunicação
> normal desta integração (Home Assistant → central), o Receptor IP
> inverte o sentido — é a **central** que abre a conexão em direção ao
> **Home Assistant**. Em redes com separação por VLAN, isso costuma
> exigir uma regra de firewall específica para esse sentido; uma regra
> que só libera Home Assistant → central (já necessária para o resto da
> integração) não cobre o Receptor IP.

### Protocolo — fonte e estrutura confirmada

Documentado na seção 8 ("Comandos do Receptor IP") do documento oficial
*"Descrição de Comandos de Protocolo ISECnet Centrais de Alarmes –
Intelbras Receptor IP"*, válido explicitamente para AMT2018E, AMT2018EG,
AMT 1016 NET e AMT 4010 SMART — **mesma estrutura de protocolo para
todos os modelos**, ao contrário da leitura de EEPROM (nomes de zona/
eventos via `0x5C`), que varia por modelo/firmware.

Cada exemplo do documento foi validado byte a byte nesta implementação
(incluindo o checksum, que usa a **mesma função `checksum()`** já usada
em todo o resto do protocolo — complemento do XOR de tudo, **incluindo**
o byte de "Nº Bytes", confirmado batendo 5 exemplos diferentes do
documento). O framing `[Nº Bytes][Comando][Conteúdo][Checksum]` também é
o mesmo — `receptor_ip.py` reaproveita `protocol.parse_frame()`
diretamente, sem duplicar lógica.

**Comando `0x94`** — a central manda isso **assim que conecta**, antes
de qualquer evento. Se não recebermos dentro de `HANDSHAKE_TIMEOUT`
(15s, valor nosso — o documento não especifica um tempo para o lado do
receptor), a conexão é encerrada. Conteúdo (6 bytes):
```
[Canal(1)] [ID1][ID2] [MAC1][MAC2][MAC3]
```
Canal: `0x45`='E'=Ethernet, `0x47`='G'=GPRS SIM1, `0x48`='H'=GPRS SIM2.
Conta: cada byte = 2 dígitos (nibble alto + nibble baixo). MAC: últimos
3 bytes do MAC da central.

**Comando `0xB0`** (evento sem data/hora, 16 bytes de conteúdo) e
**`0xB4`** (mesmo formato + 12 bytes de data/hora, 28 bytes no total):
```
[CH/IP(1)] [Conta(4)] [M(1)][T(1)] [Qualificador(1)] [Código(3)]
[Partição(2)] [Zona/Usuário(3)]                    -- (0xB0, 16 bytes)
... + [Data eventoD,M,A,H,Mi,S(6)] [Data central D,M,A,H,Mi,S(6)]  -- (0xB4, +12 bytes)
```
- `CH/IP`: nibble alto = canal (1=Ethernet, 2=GPRS), nibble baixo = 1/2 —
  não usado por esta integração além de log de depuração.
- `Conta`, `M`, `T`, `Qualificador`, `Código`, `Partição`, `Zona/Usuário`:
  **um dígito decimal por byte**, onde o dígito 0 é enviado como `0x0A`
  em vez de `0x00` — confirmado em três fontes independentes (o
  documento oficial, um projeto open-source de terceiros chamado
  "amt2018" de autoria de Felipe Magno de Almeida — Boost Software
  License —, e dois scripts de referência do usuário, testados em
  hardware real).
- `M`,`T` são sempre `01`,`08` — são os dois dígitos fixos do "tipo de
  mensagem 18" do Contact-ID, não um valor combinado.
- `Qualificador`: `1`=evento novo, `3`=restauração — **é exatamente o
  mesmo "prefixo 1/3" que já tínhamos decifrado empiricamente pra tabela
  de eventos da leitura via EEPROM**, só que aqui é um campo separado e
  documentado oficialmente, não uma dedução.
- `Código`: 3 dígitos Contact-ID — concatenado com o qualificador forma
  o código de 4 dígitos usado em `const.RECEPTOR_IP_EVENT_TABLE` (ex.:
  qualificador `3` + código `401` = `"3401"` = "Ativação pelo usuário").
- **As 6 datas/horas do `0xB4` são valor bruto binário** (ex.: dia 15 =
  byte `0x0F`), **não** o esquema de dígito-por-byte do resto do frame —
  confirmado batendo o exemplo do documento (`0F 06 11 0C 03 18` →
  15/06/17 12:03:24) byte a byte. Só a data/hora do **evento** é usada
  por esta integração; a data/hora **da central** (últimos 6 bytes do
  0xB4) não é usada aqui.

**Comando `0xF7`** (heartbeat): um byte sozinho, **sem** o framing
`[Nº Bytes][Comando][Conteúdo][Checksum]` normal — nem conteúdo, nem
checksum. Tratado como caso especial em `receptor_ip.py` antes de tentar
interpretar como um frame completo.

**Comandos `0xB5`, `0xB6`, `0xB7`** (foto, zona/usuário de 4 dígitos,
nomes por extenso): o próprio documento marca `0xB6` e `0xB7` como
*"Comando não utilizado por nenhuma central"* — não implementados
ativamente; qualquer coisa não reconhecida recebe um ACK genérico e é só
registrada em log de depuração, sem processamento específico.

Todos os comandos recebidos (reconhecidos ou não) recebem um ACK simples
(`0xFE`, 1 byte, sem framing) — é o que o protocolo espera de volta para
não reenviar/travar.

### Segurança — sem autenticação própria no protocolo

O comando `0x94` só **informa** a conta configurada na central, não é
uma senha nem um token — não há nenhum mecanismo de autenticação real
neste protocolo. A única proteção aplicada por esta integração é
**recusar imediatamente qualquer conexão que não venha do IP da central
configurado** (`entry.data["host"]`, o mesmo endereço já usado para a
conexão de cliente normal) — reduz bastante o risco numa rede doméstica
típica, mas não é uma autenticação criptográfica; a segurança real
continua dependendo da rede local estar protegida.

### Entidades

- **"Último evento (Receptor IP)"** (`sensor`): estado = descrição do
  evento + partição + zona/usuário concatenados (só quando fazem sentido
  para aquele evento específico — nem todo evento tem partição/zona,
  ex.: "Teste periódico"). Atributos: `codigo` (4 dígitos), `conta`,
  `particao`, `zona_usuario`, e `data_hora_evento` (só presente quando o
  evento veio via `0xB4`, com data/hora embutida).
- **"Último sinal de vida (Receptor IP)"** (`sensor`, `device_class:
  timestamp`): data/hora **deste servidor Home Assistant** (não da
  central — o heartbeat não carrega nenhuma data/hora própria) do último
  contato recebido, seja heartbeat puro ou qualquer evento. Usa
  `dt_util.utcnow()` (com fuso definido) em vez de `datetime.now()`,
  exigência do Home Assistant para esse `device_class`.

Ambas ficam **indisponíveis** (não deixam de existir, só ficam
indisponíveis) enquanto o Receptor IP estiver desligado na configuração.

### Limitações conhecidas deste recurso

- Precisa de configuração **na própria central**, fora do alcance desta
  integração — documentado acima, mas depende do usuário fazer certo.
- Em instalações Docker/HAOS, a porta escolhida precisa ser exposta/
  mapeada manualmente para a central conseguir alcançar — fora do
  controle desta integração.
- É um canal **adicional**: não substitui a conexão de cliente normal
  (armar/desarmar/status continuam exatamente como antes).
- `HANDSHAKE_TIMEOUT` (15s) e `IDLE_TIMEOUT` (180s) em `receptor_ip.py`
  são valores escolhidos por esta integração, não documentados
  oficialmente para o lado do receptor — podem precisar de ajuste se, na
  prática, alguma central levar mais tempo que isso para se identificar
  ou para mandar o próximo heartbeat.

---

## Fidelidade ao documento oficial (nomenclatura, `device_class`, estados)

Comparação entre o que a documentação ISECNet Rev. 15 descreve e o que a
integração expõe:

| Campo do protocolo (doc.) | Nome na doc. | Entidade HA | `device_class` / estado |
|---|---|---|---|
| Status23/30 bit3 ("Central ativada") | ativação | `alarm_control_panel` (central); cada partição usa seu próprio bit no Status22/28/29, não este | `armed_away` / `armed_home` (o protocolo não distingue stay via status; rastreado localmente pela integração a partir do último comando enviado) |
| Status23/30 bit6 ("disparo", latched) **E** Status38/46 bit2 (sirene realmente tocando) | disparo confirmado | `alarm_control_panel.triggered` e `binary_sensor` "Central disparada" | bit6 sozinho fica preso até a mesma partição ser reativada — exigir a sirene tocando evita `triggered` falso numa partição diferente (ver seção "Leitura do Status22/23") |
| Status38 bit2 (2018/1016) / Status46 bit2 (4010) ("Status sirene") | sirene | `switch` (não `binary_sensor`), pois é comandável pelos comandos `0x43`/`0x63` | — |
| `<Zonas abertas>` | zona fisicamente aberta | `binary_sensor` | `opening` (mais próximo do conceito "porta/janela aberta") |
| `<Zonas violadas>` | zona que gerou evento de alarme | atributo `violada` do `binary_sensor` da zona | — |
| `<Zonas anuladas>` | bypass | atributo `anulada_bypass` | — |
| "Bateria baixa em sensor sem fio na zona N" | bateria do sensor sem fio | atributo `bateria_baixa` | — |
| Status29/36 bit0 "Falta de rede elétrica" | energia CA | `binary_sensor` | `problem` (sem inversão — bit=1 na central significa falta de energia, e o sensor fica "ligado" nesse caso, coerente com `device_class: problem`, onde ligado = problema) |
| Status29/36 bit1 "Bateria baixa" | bateria interna fraca | `binary_sensor` | `battery` |
| Status29/36 bit2 "Bateria ausente ou invertida" | falha de bateria | `binary_sensor` | `problem` |
| Status29/36 bit3 "Bateria em curto-circuito" | falha de bateria | `binary_sensor` | `problem` |
| Status29/36 bit4 "Sobrecarga na saída auxiliar" | falha elétrica | `binary_sensor` | `problem` |
| Status23/30 = `0x11` ("Problema na central") | problema genérico | `binary_sensor` | `problem` |
| Status31/41 nibble baixo (bits 0-3) | nível da bateria (medidor "termômetro": `0x0F`=100%, `0x07`=75%, `0x03`=50%, `0x01`=25%, `0x00`=0%) | `sensor` (Bateria %) | zerado se bit2 OU bit3 do Status29/36 estiverem ligados (bateria ausente/invertida OU em curto — ver nota abaixo), validado com testes reais de campo (bateria ausente/em curto) |
| Status33/43 bit0 "Corte do fio da sirene" | falha na fiação da sirene | `binary_sensor` | `problem` |
| Status33/43 bit1 "Curto-circuito no fio da sirene" | falha na fiação da sirene | `binary_sensor` | `problem` |
| Status33/43 bit2 "Corte de linha telefônica" | falha na linha telefônica | `binary_sensor` | `problem` |
| Status33/43 bit3 "Falha ao comunicar evento" | falha na comunicação com o monitoramento | `binary_sensor` | `problem` |
| `<Partição habilitada>` (Status21/27) | particionamento ligado/desligado na programação da central | `binary_sensor` | sem `device_class` (é uma informação de configuração, não uma falha) |
| Controle de PGM (`0x50`) | saída programável | `switch` | (PGM é sempre bidirecional: liga/desliga + status de leitura — por isso é `switch`, e não `binary_sensor`) |
| `<Pânico>` (`0x45`) | evento momentâneo, sem "desfazer" | `button` | (não é `switch`: não existe estado permanente para ler de volta) |

> **Correção de campo — nível de bateria**: uma versão anterior só zerava
> o percentual quando o bit3 (curto-circuito) estava ligado, deixando
> passar o caso de bateria **ausente** (bit2) — a central relatava um
> percentual de carga mesmo sem bateria fisicamente instalada. Corrigido
> para checar os dois bits, confirmado com testes reais de campo.

### Sobre o estado `triggered`

Conforme solicitado, a lógica de disparo **não usa isoladamente o bit "zona
disparada"**. A ordem de avaliação em `alarm_control_panel.py` é:

```
se NÃO está ativada (armada):  -> disarmed   (mesmo que o bit de disparo esteja em 1)
senão se zona/central disparada: -> triggered
senão se modo Stay rastreado:   -> armed_home
senão:                          -> armed_away
```

Isso evita o problema comum de a central "ficar presa" em `triggered` após
o usuário desarmar, quando o bit de disparo da última ocorrência ainda não
foi zerado pela central.

> **Limitação conhecida do protocolo**: o bit de "zona disparada" é único
> por central (não por partição). Em uma central particionada, todas as
> partições armadas são avaliadas com o mesmo bit de disparo — o protocolo
> ISECNet não expõe qual partição especificamente disparou.

#### Leitura do Status22/23 (2018/1016) e Status28/29/30 (4010): regra final

Essa região do protocolo é a que mais precisou de captura de bytes reais
para acertar — a tabela de valores enumerados da documentação (seção
7.4/7.5) não reflete o comportamento observado em campo. A regra final,
validada com dados reais capturados pelo usuário, é uma **máscara de bits
de verdade** no Status23/30:

| Bit | Significado |
|---|---|
| bit 0 + bit 4 | "Problema na central" (os dois precisam estar em 1 — confirmado com bytes reais capturados pelo usuário; `0x11` = bit0+bit4, batendo com o exemplo da doc) |
| bit 2 | "Alguma zona aberta" (flag agregada) |
| bit 3 | "Central ativada" |
| bit 6 | Disparo — **mas é um bit *latched*, ver ressalva abaixo** |

"Ativada" (para `armed_away`/`armed_home`/`disarmed`/`triggered`) usa
fontes **diferentes** por entidade:
- **Central**: bit 3 do Status23/30.
- **Cada partição**: seu próprio bit no Status22 (2018/1016) ou
  Status28/29 (4010) — nunca o bit 3 do Status23/30, que é um sinal
  central, não por partição.

**A ressalva importante — bit 6 é uma memória, não um disparo "ao vivo"**:
capturas reais do usuário mostraram que o bit 6 fica em `1` até que a
**mesma partição** que disparou seja reativada — se uma partição
*diferente* for armada nesse meio-tempo, o bit 6 continua em `1` e geraria
um `triggered` falso nela, mesmo a zona já estando fechada e o disparo
"antigo" já ter acabado.

A correção: usar também a **sirene realmente tocando** (Status38 bit 2 na
2018/1016, Status46 bit 2 na 4010 — não confundir com o antigo bit 1 do
Status23/30, que era a leitura errada de origem) como condição extra.
Uma memória de disparo antiga não tem a sirene ativa, então isso filtra o
falso positivo:

```
zone_triggered = bit_6_do_status23/30  E  sirene_realmente_tocando
```

Essa é a definição final usada tanto pelo `alarm_control_panel` (via
`_compute_state`, combinado com a fonte de "ativada" de cada entidade
listada acima) quanto pelo `binary_sensor` **"Central disparada"** — os
dois ficam consistentes agora, sem gating adicional além dessa condição.

| Cenário real capturado | Partição | bit 6 (bruto) | Sirene | `zone_triggered` final |
|---|---|---|---|---|
| Partição A armada, sem disparo | A ativa | `0` | desligada | `false` |
| Disparo forçado na A | A ativa | `1` | **tocando** | `true` — `triggered` |
| Partição B armada logo depois (sirene já tinha parado) | B ativa | `1` (ainda preso) | **desligada** | `false` — corrigido |

#### Modo Stay (`armed_home`)

O protocolo não tem nenhum bit que informe se a central foi ativada em
modo Stay — só que está ativada. A integração rastreia isso **localmente**,
por partição e para a central (`coordinator.armed_home_mode`), a partir do
comando enviado por último (`stay=True`/`False` no `cmd_arm`). Como não há
como confirmar isso lendo a central (ela realmente não expõe essa
informação), esse estado pode ficar desatualizado se o alarme for armado
por outro meio que não esta integração (ex.: teclado físico, app oficial)
enquanto ela está sem se comunicar com a central.

> Esta região do status (Status22/23/28/29/30/38/46) é a que mais
> divergiu entre o texto da documentação e o comportamento observado em
> campo. A regra final acima foi construída em cima de bytes brutos reais
> capturados durante testes de disparo controlado — não apenas leitura da
> documentação — e por isso é a versão mais confiável até agora.

### Modo Stay por partição: doc vs. comportamento real de campo

O comando `0x41` (Ativação) tem um campo `<Conteúdo>` cuja seção 7.1
documenta explicitamente só o caso **sem partição**:
`NULL`/`0x41`/`0x42`/`0x43`/`0x44` (1 byte, qual partição ativar, sempre
away) OU `0x50` sozinho (1 byte, Stay para a central inteira). A doc não
detalha como armar uma partição específica em modo Stay.

O comportamento validado em campo resolve isso com um conteúdo de **2
bytes**: a partição seguida do marcador Stay — ex. partição A em Stay =
conteúdo `[0x41, 0x50]`. É o que `protocol.cmd_arm()` reproduz, e é por
isso que `armed_home` funciona tanto na central quanto em cada partição.

> Versões anteriores desta integração chegaram a remover esse suporte,
> seguindo a leitura literal da doc (só o caso sem partição). Foi
> reinstaurado depois que o modo Stay parou de funcionar nos testes —
> nesse ponto específico, o comportamento real de campo é mais confiável
> do que a tabela da doc, que simplesmente não cobre esse caso.

**Restrição por modelo, confirmada em testes**: o modo Stay só funciona de
verdade na **AMT 4010 SMART** e na **AMT 2018 E SMART** — nos demais
modelos da família 2018 (AMT 2018 E/EG, AMT 1016 NET, ANM 24 Net e os
demais bytes da tabela), o comando `0x50` existe no protocolo, mas a
central não implementa esse modo. Por isso, `armed_home` só aparece como
opção nas entidades `alarm_control_panel` (central e partições) para
esses dois modelos —
nos demais, a feature nem é oferecida na UI (`ARM_HOME` fica de fora de
`supported_features`), e o método correspondente também recusa a chamada
com um erro claro, caso seja invocado diretamente por um serviço
(`coordinator.supports_stay`, verificado em `alarm_control_panel.py`).

---

## Arquitetura

```
custom_components/intelbras_alarm/
├── protocol.py         # frames ISECNet/ISECMobile: build_command, checksum,

│                        # parse_status_2018/4010, decode_zone_names
├── panel_client.py      # conexão TCP assíncrona persistente + fila serializada
├── coordinator.py       # DataUpdateCoordinator: polling, comandos de alto nível,
│                        # detecção automática de modelo, leitura de nomes de zona
├── config_flow.py       # UI de configuração (IP/porta/senha) + opção de polling
├── alarm_control_panel.py  # central + partições + serviço bypass_zone
├── switch.py             # PGMs, sirene, liga/desliga conexão
├── binary_sensor.py      # zonas + diagnósticos
├── sensor.py             # bateria (%) + contadores de zona + último comando
├── button.py             # pânico, anulação de zonas, sincronizar nomes
├── services.yaml          # descrição do serviço bypass_zone para a UI
├── const.py               # comandos, tabela de modelos, endereços EEPROM
└── translations/          # pt-BR, pt, en
```

### Conexão TCP persistente
`panel_client.PanelClient` abre a conexão uma única vez e a mantém aberta.
Toda requisição é serializada por um `asyncio.Lock` (o protocolo é
estritamente requisição/resposta — a central nunca fala primeiro). Se a
leitura ou escrita falhar (timeout, reset, etc.), o socket é fechado e a
**próxima** requisição reabre a conexão automaticamente — nunca há
desconexão proposital a cada ciclo de polling.

### Dois timeouts diferentes, para dois problemas diferentes

Até uma versão anterior, um único valor (8s, herdado do item 5 da
documentação ISECNet) fazia dois papéis ao mesmo tempo — e esses dois
papéis fazem mais sentido com números diferentes:

- **`DEFAULT_REQUEST_TIMEOUT` (3s por padrão)**: quanto tempo esperar por
  UMA tentativa — conectar, ou receber a resposta de UM comando/consulta
  já na conexão estabelecida. Os 8s originais foram pensados pra um
  cenário de conexão nova a cada requisição (como no fluxo original de
  referência); numa conexão já persistente e aberta, a central deveria
  responder bem mais rápido, então um timeout menor aqui significa
  feedback mais rápido pro usuário quando um comando falha, e reconexão
  mais ágil numa queda real (antes, cada tentativa de reconectar podia
  levar até 8s só pra desistir).
- **`DEFAULT_CONNECTION_HEALTH_TIMEOUT` (10s por padrão)**: quanto tempo
  de **silêncio acumulado** (sem nenhuma consulta de status bem-sucedida)
  a integração tolera antes de marcar as entidades como indisponíveis de
  verdade. Esse número mais generoso evita que um soluço isolado da
  central (ex.: o bug do firmware 6.2 documentado acima, ou qualquer
  outra instabilidade passageira) derrube a disponibilidade das entidades
  por causa de uma única consulta que falhou — só depois de repetidas
  tentativas malsucedidas dentro dessa janela é que a indisponibilidade é
  declarada de verdade.

**Importante — essa tolerância só vale pra consulta de status periódica,
nunca para comandos reais** (armar, desarmar, PGM, sirene, pânico,
bypass). Um comando é um pedido explícito do usuário; ele sempre falha de
forma imediata e visível (com log em nível `ERROR`) se não conseguir uma
resposta dentro do `DEFAULT_REQUEST_TIMEOUT` — não faria sentido "tolerar
silenciosamente" a falha de uma ação que o usuário está esperando ver
acontecer.

O ciclo de tolerância da consulta de status (`coordinator._handle_poll_failure`)
funciona assim:

| Situação | O que acontece | Nível de log |
|---|---|---|
| Switch "Conexão com a central" desligado | Nenhuma tentativa de comunicação é feita; entidades ficam indisponíveis | `INFO`, só na transição para esse estado (nunca se repete enquanto durar) |
| Nunca houve nenhuma consulta bem-sucedida ainda | Falha imediata, entidades ficam indisponíveis | `ERROR`, só na primeira vez (não se repete a cada ciclo) |
| Falha isolada, dentro da janela de tolerância (< 10s desde o último sucesso) | Tolerada — mantém o último dado bom conhecido, entidades continuam disponíveis, tenta de novo no próximo ciclo | `WARNING` |
| Silêncio acumulado ultrapassa a janela de tolerância (≥ 10s desde o último sucesso) | Falha definitiva — entidades ficam indisponíveis | `ERROR`, só na transição (não se repete a cada ciclo enquanto continuar falhando) |
| Comunicação volta a funcionar depois de uma falha definitiva | Entidades voltam a ficar disponíveis | `WARNING`, avisando quanto tempo ficou indisponível |

**Todas as linhas de `ERROR`/`INFO` de falha acima só aparecem uma vez por
"episódio" de indisponibilidade** — enquanto a causa persistir (switch
desligado, central offline, etc.), os ciclos de polling seguintes
continuam marcando as entidades como indisponíveis normalmente, mas sem
gerar log novo a cada 0,25s. Essa supressão foi adicionada depois de um
caso real em produção (ver aviso no topo da seção "Diagnóstico" mais
abaixo) em que a ausência dela gerou 12 milhões de linhas de log e 16GB
de banco de dados.

### Diagnóstico de resposta com tamanho inesperado

Cada família tem um tamanho de resposta de status fixo e conhecido
(`FAMILY_STATUS_LEN`: 43 bytes para 2018/1016, 54 para a 4010). Se a
central responder com um tamanho diferente do esperado para a família
detectada — como o bug do firmware 6.2 da AMT 4010 SMART documentado
acima —, a integração continua funcionando normalmente (a leitura de
campos já é defensiva, usa valor padrão pros bytes ausentes), mas agora
registra um `WARNING` no log com o tamanho recebido, o esperado, e o
conteúdo bruto em hex — útil pra correlacionar com o comportamento
observado na UI sem precisar ativar debug.

### Mensagens de erro com mais contexto

`PanelClient.send_command()` aceita um parâmetro opcional `context` (ex.:
`"Ativar Partição A"`, `"consulta de status"`) usado só para enriquecer
as mensagens de erro e os logs — toda chamada relevante do coordinator já
passa esse rótulo. Além disso, a leitura da resposta é feita em duas
etapas (primeiro o byte de cabeçalho "Nº de Bytes", depois o resto) — se o
timeout estourar na segunda etapa, a mensagem de erro já informa quantos
bytes a central chegou a **prometer** no cabeçalho, mesmo sem saber
quantos do "resto" chegaram de fato (isso exigiria um loop de leitura
manual próprio, que não implementamos por ora). Se a conexão for
encerrada pela central no meio da resposta (`IncompleteReadError`, um
cenário diferente de timeout), a mensagem já inclui os bytes parciais
recebidos em hex, não só a contagem.

### Detecção automática de modelo
1. Envia `0x5A` (status parcial, famílias 2018/1016/SMART/AMN24).
2. Se a resposta for `NACK 0xE5` ("comando descontinuado" — documentado na
   seção 7.4 como o comportamento da AMT 4010 para esse comando), envia
   `0x5B` (status completo) e identifica o modelo pelo Status25.
3. Caso contrário, identifica o modelo pelo Status19 da resposta ao `0x5A`.

### Nomes de zona e log de eventos (EEPROM, comando `0x5C`)

Ambos usam o mesmo comando (`0x5C`) e a mesma restrição de
modelo/firmware — a lista abaixo foi extraída literalmente da tela de
ajuda "Senha Acesso Remoto" do app oficial AMT Mobile, que documenta
exatamente quais centrais **não** precisam dessa senha adicional para
sincronizar nomes/eventos (e, por extensão, são as que têm esse comando
liberado nesse contexto):

| Modelo | Firmware mínimo |
|---|---|
| AMT 2018 EG | ≥ 7.70 (byte `0x77`) |
| AMT 4010 SMART | ≥ 3.20 (byte `0x32`) |
| AMT 1016 NET | ≥ 4.10 (byte `0x41`) |
| AMT 2018 E SMART | qualquer |
| ANM 24 Net | qualquer |

Ver `coordinator.supports_extended_eeprom` e `const.EEPROM_EXTENDED_MIN_FIRMWARE`.
Fora dessa lista — **inclusive a AMT 1016 NET com firmware abaixo de
4.10** (a central usada para testar esta integração está no firmware
3.1, portanto fora da lista) — a central usa um protocolo diferente e
mais antigo (comando `0xE7`), que **não é implementado aqui de
propósito**: uma tentativa real de reverso desse protocolo travou a
comunicação da central durante os testes (recuperou sozinha depois de
alguns minutos, mas ficou sem responder tanto pela integração quanto
pelo app oficial nesse meio tempo). Ver a seção "Limitações conhecidas"
mais abaixo para os detalhes dessa investigação.

**Nomes de zona**: endereço `0x0800 + (zona-1) × 16`, registros ASCII de
16 bytes terminados em `NUL`. Lidos em lotes de 12 zonas (192 bytes,
limite por leitura do comando `0x5C`). Um padrão de fábrica (`A,B,C,D...`
sequencial) é detectado e tratado como "sem nome configurado", caindo de
volta para `Zona NN`.

**Log de eventos**: endereço fixo `0x1800`, 256 registros de 8 bytes cada
(2048 bytes = `0x1800` a `0x2000`), lidos em blocos de até 192 bytes (24
registros) por leitura — o último bloco fica menor (128 bytes = 16
registros), já que 256 não é múltiplo de 24. Cada registro de 8 bytes é
um *bitfield* compacto (não são bytes alinhados a cada campo) — os 8
bytes são invertidos e tratados como uma sequência única de 64 bits:

| Campo | Bits (após inverter os bytes) | Observação |
|---|---|---|
| Ano | 1-8 | Somado a 2000 |
| Dia | 10-15 | |
| Hora | 15-20 | |
| Minuto | 20-26 | |
| Segundo | 26-32 | |
| Mês | 32-36 | |
| Zona/Usuário | 36-48 | Número da zona OU do usuário, dependendo do evento |
| Código do evento | 48-56 | Ver tabela abaixo |
| Partição | 58-64 | `0`=nenhuma, `1..4`=A..D (valores >9 subtraem 6 antes de mapear) |

Um registro com mês/dia inválidos (nunca escrito pela central) é
descartado silenciosamente — não é um evento real. Ver
`protocol.parse_event_record()`.

> ⚠️ **A ordem de endereço não é a ordem cronológica** — confirmado em
> testes reais (eventos "voltam no tempo" entre um bloco e o próximo, e
> até dentro do mesmo bloco). Por isso, `async_read_events()` sempre lê
> o log inteiro (as 11 leituras) e ordena pela data/hora **decodificada**
> de cada registro, nunca pela posição do endereço.

**Tabela de códigos de evento**: a estrutura de bits foi decifrada por
engenharia reversa do app oficial (decompilação do APK) e validada com
capturas reais de tráfego; a tabela de tradução dos códigos (`0` →
"Ativação pelo usuário", etc.) foi cruzada com a tela de configuração de
eventos do software oficial "Receptor IP" da Intelbras — só os códigos
brutos já **observados em captura real** têm tradução; um código nunca
visto aparece como `"Código desconhecido (N)"` em vez de arriscar um
palpite. Ver `protocol.EVENT_CODE_TABLE`.

| Byte bruto | Código exibido no app | Descrição |
|---|---|---|
| `0` | 3401 | Ativação pelo usuário |
| `128` | 1401 | Desativação pelo usuário |
| `1` | 3456 | Ativação parcial |
| `2` | 3130 | Restauração de disparo de zona |
| `130` | 1130 | Disparo de zona |
| `42` | 3147 | Restauração da supervisão Smart |
| `170` | 1147 | Falha da supervisão Smart |
| `43` | 3422 | Desacionamento de PGM |
| `171` | 1422 | Acionamento de PGM |
| `139` | 1570 | Anulação temporária de zona |
| `160` | 1410 | Acesso remoto pelo software de download/upload |
| `163` | 1602 | Teste periódico |
| `137` | 1333 | Problema em teclado ou receptor |
| `167` | 3301 | Restauração falha na rede elétrica |
| `13` | 1625 | Data e hora foram reiniciadas |
| `143` | 1311 | Bateria principal ausente ou invertida |
| `9` | 3333 | Restauração problema em teclado ou receptor |
| `45` | 3531 | Dispositivo Encontrado |
| `47` | 3361 | Keep alive ethernet recuperado |
| `158` | 1354 | Falha ao comunicar evento |
| `165` | 1621 | Reset do buffer de eventos |
| `175` | 1361 | Falha keep alive ethernet |
| `141` | 1301 | Falha na rede elétrica |
| `142` | 1302 | Bateria principal baixa ou em curto-circuito |
| `14` | 3302 | Restauração bat. princ. baixa ou em curto-circuito |
| `15` | 1303 (⚠️ não confirmado contra a tela oficial do app) | Bateria principal pendente |

> Os 5 marcados como "trabalho paralelo" foram confirmados posteriormente,
> num trabalho paralelo de captura própria — mesma metodologia dos 17
> originais. Nessa rodada, também corrigimos uma atribuição: o byte `45`
> na verdade corresponde ao código `3531` ("Dispositivo Encontrado"), não
> `3333` como estava antes — o `3333` correto é o byte `9`.
>
> Os 4 últimos (`141`, `142`, `14`, `15`) vieram de uma leitura real do
> log de eventos completo (256 registros) de uma AMT 1016 NET, firmware
> 3.1, confirmados pelo usuário comparando com o que o app mostra pra
> cada um. Três batem exatamente com descrições já catalogadas; o byte
> `15` não corresponde a nenhum código de 4 dígitos já confirmado — o
> número `1303` é uma extrapolação nossa (mesmo padrão dos outros "13xx"
> de bateria), possivelmente uma particularidade de firmwares antigos.

---

## Segurança

- A senha da central é armazenada como credencial do `config_entry` do Home
  Assistant (mesmo mecanismo de qualquer outra integração), nunca em texto
  plano em um arquivo de flow versionado.
- Nenhuma dependência de pacotes npm de terceiros; usa apenas `asyncio`
  (biblioteca padrão) para a conexão TCP.
- O switch **"Conexão com a central"** permite cortar a comunicação sem
  remover a integração — útil durante manutenção da central ou testes de
  campo, evitando comandos acidentais.
- O checksum de cada frame recebido é validado antes do conteúdo ser
  interpretado; frames com checksum inválido são descartados (o
  `DataUpdateCoordinator` marca a atualização como falha e tenta de novo no
  próximo ciclo). O checksum de saída também é recalculado a cada comando
  — não há valor fixo nem *cache*: qualquer senha (memorizada ou digitada
  na UI) gera um frame com checksum correto automaticamente.
- Por padrão (nenhuma das duas opções marcadas), a senha memorizada é usada
  em todos os comandos sem pedir nada na UI. Se "Exigir senha ao
  ativar/desativar" estiver marcada (ver seção de Instalação), o valor
  digitado é enviado à central **como a senha real do comando** — a
  integração não faz nenhuma validação de conteúdo, apenas de formato (4 a
  6 dígitos); quem aceita ou rejeita é a própria central, permitindo usar
  uma senha diferente da memorizada (ex.: uma senha secundária de usuário
  cadastrada na central). Uma rejeição (`NACK`, ex.: "Senha incorreta")
  aparece como erro na interface do Home Assistant.
- **Senhas por partição (4010)**: se configuradas na inclusão da
  integração (ver seção de Instalação), a senha específica de cada
  partição é usada automaticamente para armar/desarmar aquela partição —
  sem precisar digitar nada, a menos que "Exigir senha ao
  ativar/desativar" também esteja marcada, caso em que o valor digitado
  na UI continua tendo prioridade sobre a senha configurada (seja ela a
  principal ou a da partição).

## Desempenho

- Conexão TCP única e persistente (elimina o overhead de reconectar a
  cada ciclo de polling).
- Leitura da resposta é feita por tamanho exato (`readexactly`), usando o
  primeiro byte (`Nº Bytes`) do frame para saber exatamente quantos bytes
  ainda faltam — sem buffers arbitrários nem race condition entre
  respostas.
- Fila serializada por `asyncio.Lock`: no máximo uma requisição em trânsito
  por vez, exatamente como o protocolo exige (mestre único), sem overhead
  de retry desnecessário.

---

## Comportamento em reinícios do Home Assistant

O estado do switch **"Conexão com a central"** é persistido em um arquivo
próprio (`.storage/intelbras_alarm_<entry_id>_connection_enabled`), lido
**antes** de qualquer tentativa de comunicação com a central:

- Se estava **ligado**, o comportamento é o de sempre: a integração conecta
  normalmente e, se a central estiver de fato inacessível (IP errado, rede
  fora do ar), a entrada fica em `ConfigEntryNotReady` — o Home Assistant
  tenta de novo automaticamente em intervalos crescentes, sem travar a
  inicialização do restante do sistema.
- Se estava **desligado**, a integração é configurada normalmente (todas as
  entidades são criadas, incluindo o próprio switch, já mostrando
  "desligado"), mas **nenhuma tentativa de conexão TCP é feita** — nem na
  configuração inicial, nem nos ciclos de polling seguintes, que falham
  imediatamente dentro do próprio processo (sem tocar a rede) até o switch
  ser ligado de novo. As demais entidades ficam `unavailable`, exatamente
  como quando o switch é desligado manualmente em tempo de execução.

Ou seja: o Home Assistant **não fica instável** por causa disso — na pior
hipótese (central genuinamente inacessível com o switch ligado), o
comportamento é o padrão recomendado pelo próprio HA
(`ConfigEntryNotReady` + nova tentativa automática), sem nenhuma exceção
não tratada se propagando para fora da integração.

> Antes desta versão, o estado do switch **não era persistido**: a cada
> reinício, a conexão era recriada já "ligada" por padrão, ignorando
> silenciosamente uma escolha anterior de mantê-la desligada. Não chegava a
> gerar erro, mas também não respeitava a intenção do usuário — corrigido
> com o mecanismo de persistência acima.

### Entidades de partição "somem" depois de uma falha de conexão pontual

Cenário relatado: desligar o switch de conexão, uma ferramenta externa
(ex.: app AMT Remoto) ocupar a porta TCP da central enquanto isso, religar
o switch (falha, porta ainda ocupada), depois a ferramenta externa
desconectar — todas as entidades voltam ao normal, **exceto** as
`alarm_control_panel` de partição, que só retornam depois de recarregar a
integração manualmente.

Causa raiz identificada: as entidades de partição só são criadas se a
central estiver particionada, mas essa informação só é conhecida depois da
primeira leitura de status bem-sucedida — e essa checagem acontecia **uma
única vez**, no momento em que a plataforma `alarm_control_panel` é
configurada. Se esse instante coincidisse com uma falha de conexão (porta
ocupada por outro cliente, por exemplo), `coordinator.data` ainda estava
`None` naquele momento exato, e as entidades de partição nunca eram
criadas para o resto daquela sessão do Home Assistant — sem nenhum
mecanismo automático para tentar de novo depois que a conexão se
restabelecia. Um reload força uma nova checagem, então "resolvia" o
sintoma sem indicar a causa.

Corrigido: em vez de uma checagem única, a criação das entidades de
partição agora observa o coordinator continuamente através de um
listener, e cria as partições assim que dados válidos com
particionamento habilitado estiverem disponíveis pela primeira vez —
imediatamente se já estiverem no momento da configuração da plataforma, ou
mais tarde, automaticamente, se a primeira leitura só for bem-sucedida
depois. Não é mais necessário recarregar a integração manualmente para
este cenário.

---

## Diagnóstico (sem precisar de log)

Antes de mexer no logger, o caminho mais rápido é olhar os **atributos**
das próprias entidades — não exigem nada configurado, aparecem sempre:

- `alarm_control_panel` (central e cada partição): atributos
  `status22_bruto`/`status23_bruto` (2018/1016) ou
  `status28_bruto`/`status29_bruto`/`status30_bruto` (4010) — os nomes
  já vêm certos para o modelo detectado, sem ambiguidade sobre qual byte é
  qual. Nas **partições**, tem ainda `bit_desta_particao` (ex.: `"bit 1 do
  status22"`), dizendo exatamente qual bit dentro daquele byte decide o
  estado armado daquela partição especificamente.
- `binary_sensor` **"Central disparada"**: `statusNN_bruto` (nome
  dinâmico), `bit_6_latched` (bruto, pode ficar preso) e `sirene_ligada`
  (condição extra) — o estado do sensor é a junção dos dois, ver seção
  "Leitura do Status22/23".
- `sensor` **"Último comando"**:
  - `ultima_resposta_status_bruta`: sequência **completa** (todos os
    StatusNN de uma vez, em hex) da última resposta de status recebida —
    muda a cada ciclo de polling (0,25s por padrão).
  - `ultimo_comando_finalidade`, `ultimo_comando_enviado`,
    `ultimo_comando_resposta`: nome da ação, frame enviado e resposta
    específica do **último comando real** (armar, desarmar, PGM, sirene,
    pânico, bypass) — deliberadamente **não** atualizados pela consulta
    de status, para não sobrescrever rápido demais e dar tempo de
    analisar uma ação específica com calma.

Esses atributos aparecem em qualquer entidade: abra a entidade no painel,
clique no ícone de engrenagem/`{}` ("Detalhes"), e olhe a seção
"Atributos".

## Diagnóstico (logs de depuração)

> ### ⚠️ Bug crítico corrigido (v1.5.0) — crescimento descontrolado do banco do `recorder`
>
> Antes desta versão, deixar o switch **"Conexão com a central" desligado**
> (ou a central genuinamente offline) por um período longo gerava uma
> linha de log `ERROR` **a cada ciclo de polling** (0,25s por padrão),
> indefinidamente, sem nenhuma supressão. Caso real relatado em produção:
> switch desligado por ~35 dias → **12 milhões de linhas de log
> idênticas** → banco do `recorder` chegando a **16GB**, causado
> inteiramente por esta integração.
>
> Corrigido: quando o switch está desligado, a integração **não tenta
> nenhuma comunicação** com a central (nem abre socket) e loga a
> transição para esse estado **uma única vez** — silêncio completo
> enquanto permanecer desligado. O mesmo vale para qualquer falha de
> conexão genuína com o switch ligado (central offline, cabo rompido,
> etc.): a falha vira `ERROR` só na transição para "indisponível", nunca
> se repete enquanto durar, e quando a comunicação volta a funcionar
> aparece um `WARNING` avisando (com o tempo que ficou fora do ar). Se
> você tiver uma versão anterior instalada e notar o banco do Home
> Assistant crescendo rápido, atualize para esta versão o quanto antes.

Para uma investigação mais profunda (ex.: acompanhar a evolução do status
em tempo real durante um teste), ative o log em nível `debug` desta
integração:

```yaml
logger:
  logs:
    custom_components.intelbras_alarm: debug
```

> O nível por componente fica **dentro** de `logs:`, não direto embaixo de
> `logger:` — colocar `custom_components.intelbras_alarm: debug` direto
> sob `logger:` dá erro de validação de config. Para testar sem editar o
> YAML (e sem persistir após um reinício), use o serviço
> `logger.set_level` em Ferramentas de desenvolvedor → Ações:
> ```yaml
> service: logger.set_level
> data:
>   custom_components.intelbras_alarm: debug
> ```

Com o nível debug ativo, os logs (em **Configurações → Sistema → Logs**,
filtrando por `intelbras_alarm`) mostram, a cada ciclo de polling:

```
status recebido: conteúdo=<bytes em hex> | activated(central)=... partitions_armed={'A': ..., 'B': ...} zone_triggered=... siren_on=... problem=...
```

E, a cada comando enviado (armar, desarmar, PGM, sirene, pânico, bypass):

```
enviando comando: ação=Ativar Partição A frame=<bytes em hex>
resposta recebida: ação=Ativar Partição A resultado=OK resposta_bruta=<bytes em hex>
```

Isso permite comparar, byte a byte, o que a central realmente envia contra
a lógica documentada na seção "Leitura do Status22/23" — essencial para
investigar qualquer suspeita de que `triggered`/`armed_home`/`armed_away`
não estão batendo com o comportamento real da central.

---

## Limitações conhecidas

- O protocolo não informa **qual partição** disparou quando há mais de uma
  partição armada — o alarme mostra `triggered` em todas as partições
  armadas simultaneamente (ver seção sobre `triggered` acima).
- O número de zonas exibido é o **nativo do modelo detectado**
  (`const.MODEL_TABLE`). Instalações com expansoras de zona além do nativo
  do modelo devem ajustar esse valor diretamente em `const.py` — não há
  opção de UI para isso, por definição do escopo deste projeto.
- PGMs de 4 a 19 (família 4010) são expostas como `switch` mesmo sem uma
  expansora física instalada, pois o protocolo não informa quantas
  expansoras existem — apenas se há problema em uma expansora endereçada.
  Zonas sem expansora simplesmente não responderão (ou responderão sempre
  desligadas).
- O comando `0x42` (bypass) é **absoluto**: ele define de uma vez o estado
  de anulação das 64 zonas do protocolo. Os botões "Anular zonas
  abertas"/"Anular zonas violadas" contornam isso enviando sempre a união
  entre o que já estava anulado (última leitura de status) e as zonas
  novas — mas se duas anulações forem disparadas quase ao mesmo tempo
  (ex.: automação + botão manual), a mais recente pode não considerar uma
  anulação ainda não refletida no último status lido.
- Nomes de zona e log de eventos, pelo caminho **moderno** (`0x5C`),
  **não estão disponíveis em todos os modelos/firmwares suportados pelo
  resto da integração** — só nos listados na seção "Nomes de zona e log
  de eventos" acima. Fora dessa lista, ver a seção "Protocolo legado" a
  seguir — desde a v2.0.2, existe um caminho alternativo,
  opcional.

### Protocolo legado (`0xE7`) de nomes/eventos

Para modelos/firmwares fora da lista de "Nomes de zona e log de
eventos" (comando moderno `0x5C`) — por exemplo, a AMT 1016 NET com
firmware abaixo de 4.10 — a central usa um protocolo diferente e mais
antigo (frames começando em `0xE7`, com um CRC próprio, distinto do
checksum simples usado no resto do protocolo).

**Confirmado funcionando de ponta a ponta em hardware real** (AMT 1016
NET, firmware 3.1) — autenticação bem-sucedida seguida de leitura
completa de zonas, usuários, receptores/teclados e do log de eventos,
com texto batendo exatamente com os nomes configurados na central.
Implementado em `protocol_legacy_eeprom.py`, opcional e desligado por
padrão — precisa da "Senha de leitura de mensagens" (6 dígitos, a mesma
"Senha Acesso Remoto" do app oficial) configurada explicitamente.

**Histórico**: uma tentativa anterior, sem essa senha de identificação,
só recebia um ACK genérico da central, sem dados — e uma tentativa
ainda mais antiga, com um endereço/comando diferente, chegou a travar a
comunicação da central (recuperou sozinha, sem reset físico). A
diferença que resolveu: o comando precisa de uma **autenticação prévia**
(sub-comando `[5,17]` dentro do `0xE7`, com a senha de 6 dígitos), *e*
essa senha precisa de uma codificação específica — cada dígito `'0'` é
trocado pelo caractere `'A'` **antes** de dividir em pares e interpretar
cada par como um byte em hexadecimal (achado que faltava nas tentativas
anteriores).

**Como funciona nesta integração**:
- Comando de autenticação: `[5, 17, par1, par2, par3, 0x34, crc_hi, crc_lo]`
  — sucesso confirmado pelo byte de status `0x50` na resposta (`0x53` =
  senha incorreta).
- Comando de leitura: `[4, 18, endereço_hi, endereço_lo, tamanho,
  crc_hi, crc_lo]` — mesmo formato já usado no comando moderno, só que
  sem passar pelo `0x5C`.
- **CRC próprio deste protocolo** — não é nenhum CRC16 padrão
  conhecido. Peculiaridade real, confirmada byte a byte no bytecode
  decompilado: os 2 primeiros bytes de cada cálculo são carregados
  direto num registrador de 24 bits (posições alta/média), **sem**
  passar pelo laço de 8 deslocamentos — só a partir do 3º byte em
  diante que o deslocamento de CRC de verdade acontece.
- Endereços de leitura (nomes: `2048`–`4316`; eventos: `6144`–`8034`,
  ambos em páginas de 189 bytes) são constantes literais encontradas no
  código decompilado do app oficial (`SincronizarNomes`/
  `BaixarEventos`) — confirmadas na AMT 1016 NET testada; ainda não
  confirmadas independentemente para os demais modelos fora do limiar
  do `0x5C` (assume-se o mesmo layout, por virem do mesmo trecho de
  código do app, não específico de modelo).
- **Reaproveita a conexão persistente já existente** (`self.client`,
  mesma usada no polling normal) — só roda sob demanda (botão de
  sincronizar zonas / serviço `read_events`), nunca durante o ciclo de
  consulta regular. A primeira versão desta funcionalidade tentava
  abrir uma conexão TCP **isolada e separada**, pensando em evitar
  misturar protocolos numa mesma conexão — só que a central **só
  aceita um cliente conectado por vez**, então a segunda conexão
  sempre falhava enquanto o polling normal já estivesse rodando (bug
  real relatado em produção). Corrigido reaproveitando `self.client`
  — o framing de baixo nível (`[Nº Bytes]` como primeiro byte) já é
  genérico o suficiente pra funcionar com qualquer comando, `0xE7`
  incluso. Isso, aliás, bate com o que a própria captura real do app
  oficial mostrou: consulta de status normal e comandos `0xE7` na
  **mesma** conexão, sem reabrir nada entre um e outro.

**Ainda em aberto**: os endereços acima só foram confirmados numa
central real (1016 NET); os três códigos de evento vistos numa leitura
real de teste (`141`, `142`, `14`) ainda não estão catalogados — ver
`protocol.EVENT_CODE_TABLE`.

### Bug conhecido da central (não da integração): senha única em central particionada

Relatado em campo: usando **apenas uma senha geral** numa central
**particionada**, com duas ou mais partições ativadas ao mesmo tempo
(ex.: partição A e partição B), enviar o comando para desativar **só uma
delas** (ex.: só a B) pode fazer a central desativar a outra partição (A)
junto, sem nenhum comando ter sido enviado para ela. A integração envia
exatamente o comando de desativar aquela partição específica, conforme a
documentação do protocolo — o comportamento observado é da própria
central, não da lógica de comando aqui.

**Mitigação recomendada**: cadastrar senhas específicas por partição
diretamente **na central** (pelo teclado ou app oficial), e depois
informar essas mesmas senhas na tela "Senhas por partição" desta
integração (disponível para a AMT 4010 SMART — ver seção de
Configuração), para que cada comando de ativar/desativar use a senha
daquela partição especificamente, em vez da senha geral. Sugestão de 5
senhas a cadastrar na central:

- **Senha 1**: ativa/desativa **todas** as partições + bypass
- **Senha 2**: ativa/desativa **só a partição A** + bypass
- **Senha 3**: ativa/desativa **só a partição B** + bypass
- **Senha 4**: ativa/desativa **só a partição C** + bypass
- **Senha 5**: ativa/desativa **só a partição D** + bypass

## Nomenclatura das entidades

O nome de cada entidade é **prefixado pelo nome do dispositivo** (ex.:
"Intelbras AMT 4010 SMART (IP) Sirene") — o padrão do Home Assistant. Uma
versão anterior chegou a remover esse prefixo a pedido do usuário, depois
revertida — mantido o comportamento padrão.

> **Efeito colateral dessa reversão**: alternar `has_entity_name` entre
> `True`/`False` faz o Home Assistant tentar **migrar o `entity_id`**
> internamente para acompanhar o novo nome sugerido — mesmo o `unique_id`
> nunca tendo mudado. Se a instalação já tiver passado por várias dessas
> trocas ao longo do tempo (como aconteceu durante o desenvolvimento
> desta integração), o registro de entidades pode acumular IDs "órfãos"
> de tentativas anteriores, causando avisos como *"Cannot migrate history
> for entity_id ... because the new entity_id is already in use"* nos
> logs do `recorder`. Isso é só um aviso: a entidade em si continua
> funcionando normalmente com seu `entity_id` atual — o que se perde é a
> continuidade do **histórico/estatísticas antigas** ficando presas sob o
> ID abandonado. Não é causado pela tela de "Configurar" (opções) nem por
> nenhuma mudança nela — é resultado de trocas de `has_entity_name` em
> versões anteriores. Se incomodar, pode limpar manualmente em
> Configurações → Entidades → filtrar por "indisponível"/os IDs antigos
> mencionados no log → excluir.

## Data/Hora da central: não é BCD, é o valor cru do byte

Diferente do que a documentação oficial afirma (seção 7.4/7.5: "cada
nibble representa um dígito", com o exemplo "0x12 representa 12 horas",
sugerindo BCD), bytes reais capturados pelo usuário provam que os campos
de hora/minuto/dia/mês/ano da central são o **valor cru do byte em
decimal**, sem separação de nibbles. Duas evidências definitivas:

- Um byte de minuto `0x2E` só faz sentido como valor cru (`0x2E` = 46
  decimal, o minuto real na captura) — como BCD teria um nibble baixo
  `E`, que não é um dígito decimal válido (0-9), então nem deveria ser
  possível decodificar.
- Um byte de ano `0x1A` bate com `26` (2026, o ano real) como valor cru;
  via BCD daria `20` (2020), errado.

Isso também é consistente com o valor sendo usado diretamente, sem
nenhuma conversão BCD, em implementações de referência anteriores para
este protocolo. `_format_panel_datetime()` usa o valor cru do byte
diretamente.

## Créditos

Esta integração foi construída a partir de trabalhos de engenharia
reversa do protocolo ISECNet/ISECMobile muito bem feitos, originalmente
publicado como um fluxo do Node-RED, e documentação disponível na
internet.
