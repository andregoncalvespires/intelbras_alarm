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

Integração HACS para centrais de alarme Intelbras **AMT 1016 NET, AMT 2018
E/EG, ANM 24 Net, AMT 4010 SMART** e outros modelos da mesma família (ver
lista completa abaixo), via protocolo ISECNet/ISECMobile (o mesmo do app
AMT Mobile) — conexão TCP direta e persistente com a central.

A integração usa as entidades **padrão do próprio Home Assistant** para
representar a central como uma central de segurança de verdade deveria
ser representada: `alarm_control_panel` para a central e cada partição,
com os estados de um alarme real (desarmada, armada ausente, armada
presente, disparada), suporte a senha para armar/desarmar (opcional), e
todos os diagnósticos da central (bateria, rede elétrica, tamper,
sabotagem, sirene, etc.) como entidades próprias.

> 📘 Documentação técnica completa (mapeamento de bits do protocolo,
> decisões de design, histórico de correções): [README_DETALHADO.md](README_DETALHADO.md).
> Este README é o resumo prático para instalar e usar.

**ℹ️ Modelos/firmwares realmente testados até agora:**

| Modelo | Firmware | Observação |
|---|---|---|
| AMT 1016 NET | 3.1 | — |
| AMT 2018 E/EG | 4.7 | — |
| AMT 4010 SMART | 5.2 | — |
| AMT 4010 SMART | 6.2 | Comportamento incorreto da central: eventualmente a central envia uma resposta de status menor que o esperado aleatoriamente. Nesses casos, a integração descarta a leitura (tratada como falha isolada, igual a uma queda de conexão) e mantém o último dado bom conhecido — nenhuma entidade muda de valor por causa disso. Só fica indisponível se o problema persistir por mais de 10s seguidos (ver seção de diagnóstico no README_DETALHADO.md). |

Os demais modelos suportados pelo protocolo (ANM 24 Net, AMT 2018 E
Smart, AMT 2008 RF, AMT 2010, AMT 2018 base, AMT 2110, AMT 2118 EG, AMT
3010, AMT 2018 E3G, GPRS 1000 UN) seguem a mesma estrutura, mas ainda não
foram validados em hardware real — o suporte a eles não é bloqueado por
isso, é só para você ter uma referência caso relate algum problema. Esta
tabela vai sendo atualizada conforme outros usuários testarem e
relatarem outros modelos/firmwares.

> ⚠️ **AMT 2018 E Smart** também é suportada, mas com uma ressalva
> técnica: essa central usa um comando de status diferente (`0x5D`, não
> `0x5A`), com uma resposta bem mais longa — confirmamos, decompilando o
> app oficial, que os dados que a integração usa ficam nos mesmos
> endereços da família 2018 padrão, então reaproveitamos o mesmo parsing.
> Ainda **não testado contra hardware real**. Ver README_DETALHADO.md
> para os detalhes técnicos.

![Tela do dispositivo no Home Assistant, mostrando central, partições, PGMs e sirene](docs/images/tela-dispositivo.png)

---

## Instalação

**Via HACS**: HACS → Integrações → menu (⋮) → Repositórios customizados →
adicione a URL deste repositório (categoria Integração) → instale
"Intelbras Alarm (ISECNet)" → reinicie o Home Assistant.

**Manual**: copie `custom_components/intelbras_alarm` para
`<config>/custom_components/` → reinicie o Home Assistant.

## Configuração

**Ajustes → Dispositivos e Serviços → Adicionar Integração → Intelbras Alarm**

![Tela de configuração: IP, porta, senha e opções de exigir senha](docs/images/tela-configuracao-1.png)
![Tela de configuração, rolada para baixo: zonas habilitadas e opções do Receptor IP](docs/images/tela-configuracao-2.png)

1. **IP** e **porta** da central (padrão `9009`).
2. **Senha** (a mesma do app AMT Mobile, 4 a 6 dígitos).
3. Opcional: marque se quer que o Home Assistant **peça a senha** antes de
   ativar e/ou desativar pela interface (por padrão, nenhuma das duas —
   usa a senha configurada automaticamente, sem perguntar nada).
4. Opcional: **zonas habilitadas por padrão** — formato `1-5;8;10-15`
   (intervalos e/ou números separados por `;`). Padrão: `1-8;17-24`. As
   demais zonas continuam existindo, só ficam desabilitadas até você
   habilitá-las manualmente em Configurações → Entidades.
5. Opcional: **habilitar recepção de eventos (Receptor IP)** e a porta de
   escuta (padrão `9010`) — ver seção própria mais abaixo. Desligado por
   padrão; precisa de configuração adicional **na própria central**, fora
   desta integração.
6. Opcional: **senha de leitura de mensagens (6 dígitos)** — deixe em
   branco se seu modelo já aparece na lista de "Nomes de zona e log de
   eventos" abaixo. Preencha (a mesma "Senha Acesso Remoto" do app AMT
   Mobile) só se sua central ficar de fora dessa lista e você mesmo
   assim quiser nomes de zona/usuário e eventos — usa um protocolo
   alternativo, confirmado funcionando em hardware real.
7. O **modelo é detectado automaticamente** — sem campo manual.
8. Só para a **AMT 4010 SMART**: uma tela extra permite cadastrar senhas
   diferentes por partição (A/B/C/D), se sua central tiver — opcional,
   deixe em branco para usar a senha principal em todas.

   > ⚠️ **Central particionada com uma senha só**: há um bug conhecido da
   > própria central (não da integração) onde desativar uma partição pode
   > desativar outra junto, se as duas usarem a mesma senha geral.
   > Detalhes e mitigação recomendada (5 senhas por partição, cadastradas
   > na central) no [README_DETALHADO.md](README_DETALHADO.md#bug-conhecido-da-central-não-da-integração-senha-única-em-central-particionada).

   ![Tela complementar de senhas por partição, só para a AMT 4010 SMART](docs/images/tela-configuracao-4010-particoes.jpeg)

Depois de configurada, em **Configurar** na própria integração (Ajustes →
Dispositivos e Serviços → Intelbras Alarm → Configurar) dá pra ajustar,
**sem remover e reconfigurar do zero**: a senha principal (validada contra
a central antes de salvar), as senhas por partição (4010), as opções de
exigir senha, **habilitar/desabilitar o Receptor IP e sua porta**, e o
intervalo de polling. IP, porta, modelo e zonas habilitadas por padrão
não são editáveis ali (esse último só funciona na configuração inicial)
— para isso, remova e reconfigure.

---

## Entidades criadas

- **Alarme** (`alarm_control_panel`): uma para a central e uma para cada
  partição (se a central estiver particionada). Estados: desarmada,
  armada ausente, armada presente (Stay — só em AMT 4010 SMART e AMT 2018
  E SMART) e disparada — os mesmos estados que uma central de alarme de
  verdade tem, com suporte a código/senha na própria interface.

  ![Painel de controle da central AMT 4010 SMART armada em modo presente (Stay)](docs/images/controle-armado-em-casa-4010.jpeg)

  > 📖 Como a entidade é o `alarm_control_panel` **padrão** do Home
  > Assistant (não algo customizado desta integração), boa parte do que a
  > [documentação oficial do Home Assistant sobre Alarm control panel](https://www.home-assistant.io/integrations/alarm_control_panel/)
  > descreve já funciona sem nenhuma configuração extra: os gatilhos
  > (`alarm_control_panel.armed`, `.disarmed`, `.triggered`), condições
  > (`is_armed`, `is_triggered`) e ações (`alarm_arm_away`,
  > `alarm_arm_home`, `alarm_disarm`) padrão do Home Assistant, incluindo
  > o parâmetro `code` (a senha) nas ações. A página também traz exemplos
  > prontos de automação (armar quando todos saem de casa, notificar em
  > disparo, etc.) que funcionam direto com esta integração. Duas coisas
  > da documentação que **não** se aplicam aqui: os modos "night",
  > "vacation" e "custom bypass" (a central não expõe esses modos, só
  > away/home/disarmed/triggered) e o atributo `changed_by` (o protocolo
  > não informa quem alterou o estado, então não é preenchido).

- **Zonas** (`binary_sensor`, uma por zona): aberta/fechada, com violação,
  anulação, bateria baixa, tamper e curto-circuito como atributos (quando
  aplicável àquela zona).
- **Diagnóstico da central** (`binary_sensor`): rede elétrica, bateria
  (fraca/ausente/curto), sobrecarga, sirene (fio cortado/curto), linha
  telefônica, falha de comunicação, particionamento, disparo, zona aberta
  agregada, problema em teclados/receptores (desabilitados por padrão —
  habilite manualmente os que existem na sua instalação) e (só na 4010)
  expansores de PGM/zona.
- **Bateria e contadores** (`sensor`): nível de bateria (%), contagem de
  zonas abertas/violadas/anuladas/com bateria baixa (sensores sem fio, com
  a lista de quais zonas nos atributos), **"Último comando"** (rastreia
  a última ação enviada e a resposta da central, separado da consulta de
  status normal), **"Últimos eventos"** (só nos modelos/firmwares da
  tabela abaixo — ver seção própria mais adiante), e, se o Receptor IP
  estiver habilitado, **"Último evento (Receptor IP)"** e **"Último sinal
  de vida (Receptor IP)"** (ver seção própria).
- **PGMs e sirene** (`switch`): controla e mostra o estado real de cada
  PGM e da sirene.
- **Conexão com a central** (`switch`): liga/desliga a comunicação TCP —
  útil para manutenção, sem precisar remover a integração.
- **Botões** (`button`): pânico (silencioso/audível/médico/incêndio),
  anular zonas abertas/violadas/ambas, remover todas as anulações, e
  (só nos modelos/firmwares da tabela abaixo) sincronizar nomes de zona
  lidos da central.

## Nomes de zona e log de eventos — só em alguns modelos/firmwares

Ler nomes de zona (EEPROM) e o log de eventos da central usa o mesmo
comando (`0x5C`) e só está disponível nos modelos/firmwares abaixo —
exatamente a mesma lista que o app oficial AMT Mobile usa para decidir se
pede a "Senha de Acesso Remoto" para essas duas funções:

| Modelo | Firmware mínimo |
|---|---|
| AMT 2018 EG | ≥ 7.70 |
| AMT 4010 SMART | ≥ 3.20 |
| AMT 1016 NET | ≥ 4.10 |
| AMT 2018 E SMART | qualquer |
| ANM 24 Net | qualquer |

Fora dessa lista (por exemplo, uma AMT 1016 NET com firmware abaixo de
4.10), a central usa um protocolo diferente e mais antigo — que, a
partir da v2.0.2-beta.2, **também é suportado**, opcionalmente: informe
a "Senha de leitura de mensagens" (6 dígitos, a mesma "Senha Acesso
Remoto" pedida pelo app AMT Mobile) na configuração da integração
(deixe em branco se não quiser usar). Sem essa senha preenchida, o
botão de sincronizar nomes de zona e o serviço de eventos continuam
sem fazer nada, como antes.

## Serviço `intelbras_alarm.bypass_zone`

Anula ou reativa uma ou mais zonas por número, direto de automações,
scripts ou pela aba Ferramentas de desenvolvedor → Ações:

```yaml
service: intelbras_alarm.bypass_zone
target:
  entity_id: alarm_control_panel.central
data:
  zones: "1-5;8;10-15"   # intervalos e/ou números separados por ;
  bypass: true             # true = anular, false = reativar
```

Sempre usa a senha configurada da central (não depende das opções de
"pedir senha" da UI). Preserva anulações já existentes em outras zonas.

## Serviço `intelbras_alarm.read_events`

Lê o log de eventos completo da central (até 256 eventos) e devolve todos
já traduzidos (data/hora, zona ou usuário, partição, código e descrição)
na resposta do serviço — além de atualizar a entidade **"Últimos
eventos"** com os mais recentes, para consulta rápida sem precisar olhar
a resposta do serviço toda vez.

```yaml
service: intelbras_alarm.read_events
target:
  entity_id: alarm_control_panel.central
```

Só disponível nos modelos/firmwares da tabela acima. Pensado para ser
chamado por uma automação no intervalo que você quiser (ex.: a cada 5
minutos) — cada chamada sempre lê e ordena o log inteiro por data/hora
real de cada evento (a ordem de endereço na memória **não** corresponde
à ordem cronológica, confirmado em testes reais), então o resultado é
sempre consistente, não importa quantas vezes ou com que frequência você
chamar.

## Receptor IP — eventos em tempo real (opcional)

Além da leitura sob demanda acima, a central pode ser configurada para
**empurrar eventos sozinha, em tempo real**, sem a integração precisar
perguntar — o modo "Receptor IP" já usado por softwares de monitoramento
profissional. Aqui os papéis se invertem: a central vira **cliente**,
conectando nela mesma no Home Assistant.

**Desligado por padrão.** Para habilitar:

1. Na configuração da integração (inicial ou em "Configurar"), marque
   **"Habilitar recepção de eventos (Receptor IP)"** e confira a porta
   (padrão `9010`, diferente da `9009` usada pela conexão normal desta
   integração).
2. **Na própria central** — **fora desta integração** — configure-a para
   apontar para o Home Assistant. Passo a passo pelo app **AMT Remoto**
   (não confundir com o AMT Mobile, o app de uso do dia a dia):

   - **Comunicação → Monitoramento IP → Servidor 2**:
     - `IP` = endereço IP do seu Home Assistant
     - `Porta` = `9010` (ou a porta que você escolheu no passo 1)
     - **Desmarque** "Utilizar endereço DNS"
   - **Comunicação → Modo de Reportagem**: selecione **"Duplo IP"**
   - **Ethernet → Configuração IP**:
     - "Transmitir sinal de link Ethernet a cada" = **1 minuto**
     - "Monitoramento do link (keep alive)" = **marcado**, se essa opção
       existir no seu modelo (nem toda central tem esse campo)

3. Se o Home Assistant roda em Docker ou HAOS, essa porta precisa estar
   **exposta/mapeada** para a central conseguir alcançar — confira a
   documentação da sua instalação.

> 💡 **Rede com VLANs/segmentação**: a conexão acontece no sentido
> **central → Home Assistant** (é a central que liga para nós, ao
> contrário de toda a comunicação normal desta integração, que liga
> para a central). Se a central e o Home Assistant estiverem em VLANs
> diferentes, garanta que o firewall/roteador permita tráfego **nesse
> sentido específico** (da rede da central para a porta do Home
> Assistant) — uma regra que só libera o sentido contrário (Home
> Assistant → central) não é suficiente para o Receptor IP funcionar.

Duas entidades novas, presentes sempre (ficam **indisponíveis** enquanto
o recurso estiver desligado na configuração):

- **"Último evento (Receptor IP)"**: descrição do evento mais recente,
  já com partição e zona/usuário concatenados quando fazem sentido para
  aquele evento (ex.: *"Ativação pelo usuário — Partição A — Zona/Usuário
  4"*). Código, conta e data/hora ficam nos atributos.
- **"Último sinal de vida (Receptor IP)"**: data/hora (deste Home
  Assistant) do último contato da central — atualiza tanto num
  "heartbeat" simples quanto em qualquer evento recebido. Útil para
  confirmar que a conexão está viva.

> ⚠️ **Este protocolo não tem senha nem autenticação própria.** A única
> proteção que esta integração aplica é aceitar conexões **só do IP da
> central configurado nesta integração** — qualquer outra origem é
> recusada imediatamente. Isso reduz bastante o risco numa rede
> doméstica normal, mas não é uma autenticação de verdade; mantenha sua
> rede local segura.

## Dicas de uso

- Quer confirmar o que a integração está fazendo? O sensor **"Último
  comando"** mostra a ação enviada e a resposta da central em atributos
  separados da consulta de status normal (que atualiza rápido demais para
  acompanhar):

  ![Atributos da entidade "Último comando", mostrando o comando enviado e a resposta da central](docs/images/ultimo-comando-detalhe.png)

- Se algo parecer errado, olhe os atributos de `alarm_control_panel` e do
  binary_sensor "Central disparada" — mostram os bytes brutos recebidos
  da central, sem precisar mexer em log.
- Precisa de mais detalhe (log de depuração, explicação de cada bit do
  protocolo)? Veja o [README_DETALHADO.md](README_DETALHADO.md).

## Demonstração

<table>
<tr>
<td align="center" width="33%">

**Ativar/desativar sem exigir senha**
<br>(padrão — um toque, sem digitar nada)

![Ativando e desativando sem senha](docs/images/armar-desarmar-sem-senha.gif)

</td>
<td align="center" width="33%">

**Ativar/desativar exigindo senha**
<br>(opção marcada na configuração)

![Ativando e desativando com senha](docs/images/armar-desarmar-com-senha.gif)

</td>
<td align="center" width="33%">

**Disparo**
<br>(estado `triggered` refletido em tempo real)

![Central disparando](docs/images/disparo.gif)

</td>
</tr>
</table>

## Créditos

Esta integração foi construída a partir de trabalhos de engenharia
reversa do protocolo ISECNet/ISECMobile muito bem feitos, originalmente
publicado como um fluxo do Node-RED, e documentação disponível na
internet.
