# noticiasgg — estado detalhado

> Criado em 04/08/2026 durante a arrumação do painel global. Motivo: o `STATE.md`
> global cita este projeto e **não havia arquivo de detalhe nenhum** — então o painel
> estava sozinho segurando a memória, e sozinho ele não cabe.
>
> **Regra — onde mora o quê.** Detalhe, número, data e história moram AQUI. O painel
> global guarda uma linha e aponta para cá. **Nunca copie de volta** — a mesma verdade
> em dois lugares acaba discordando.
>
> **Regra — número que o sistema sabe responder não se escreve aqui; escreve-se o
> COMANDO que mede.** Número em documento apodrece calado.

---

## O que é

Agente de IA multi-domínio, backend em Python/FastAPI:
1. coleta dados financeiros (Yahoo Finance, CoinGecko, FRED, BCB) + notícias, e manda
   um resumo diário pelo WhatsApp;
2. identifica plantas, pragas e doenças por foto (plant_id).

Fonte viva do que existe hoje: `README.md` e `CLAUDE.md` na raiz do projeto.

## Feature em andamento (04/09/2026) — mensagem diária "Soja Disponível" às 12h

Pedido do Matheus: o bot manda todo dia às 12h, em MENSAGEM SEPARADA (não no relatório),
neste formato EXATO — montado por CÓDIGO, nunca pelo modelo (formato fixo + LLM = deriva):

```
Soja Disponível

Porto 🌱🛳️ = 159,44
Pontal/SP🌱1️⃣ = 150,44
Uberaba/MG🌱2️⃣ = 147,44
Canarana/MT🌱3️⃣ = 132,44

💵 = 5,153
🇺🇸🌱ZSU6 Setembro26 = 12,504/bushel
```

### Especificação FECHADA — respondida pelo primo (G.Mouro, 5516991016898) em 04/09 15:33

Fonte: mensagem dele no banco da Evolution (`Message`, remoteJid `255666618896603@lid`).
Eu conversei com ele direto pelo número do bot, com autorização do Matheus.

| # | Pergunta | Resposta dele | Consequência |
|---|---|---|---|
| 1 | porto base | **Santos = Paranaguá, considerar iguais; fonte CEPEA** (`cepea.org.br/br/indicador/soja.aspx`) | **UM bloco só** — morreu o problema dos 6 fretes |
| 2 | Canarana R$ 27/sc (58% acima do mercado→Santos) | é valor **conservador, perto da máxima de safra** (fev/mar passa de R$ 500/t); Canarana escoa por Santos, Paranaguá, Vitória, Arco Norte, Rio Verde, Uberaba, Rondonópolis | usar os números DELE como estão; nunca "corrigir" por média |
| 3 | frete inclui algo? | **só frete** | — |
| 4 | fretes p/ 2º porto? | **não tem** — rotas variam no ano | confirma bloco único |
| 5 | frete muda quando? | caro em **jan–mar** (colheita: menos caminhão na estrada) | painel: frete editável + data; lembrete sazonal é opcional |
| 6 | CBOT fixo em ZSU6? | **sempre o contrato MAIS CURTO** (hoje ZSU6) | rótulo roda sozinho: Set→Nov→Jan…; `ZS=F` do Yahoo NÃO serve (já está em Nov) |
| 7 | dólar | **comercial** | Yahoo `BRL=X`, 3 casas |

Fretes derivados da mensagem dele (Porto − praça): **Pontal 9,00 · Uberaba 12,00 · Canarana 27,00**
(R$/sc, todos redondos — por isso os ",44" repetidos vinham do Porto).

### Verificações feitas (o que já se sabe que funciona / não funciona)

- **Yahoo tem cada contrato:** `ZS{F,H,K,N,Q,U,X}{aa}.CBT` — testado ZSU26 (1294,25), ZSX26, ZSF27,
  ZSH27, ZSK27, ZSN27, ZSQ27, todos 200. Preço em **USX (centavos)** → dividir por 100 e
  mostrar 3 casas ("12,504/bushel"). "Mais curto" = menor vencimento AINDA negociado (Set
  negocia até ~14/09); calcular por código, não pelo `ZS=F`.
- **`BRL=X`** = comercial (5,1267 em 04/09); arredondar a 3 casas.
- **CEPEA é inalcançável, ponto** (medido 04/09 ~17h): direto → 403; via ScraperAPI → **500
  "protected domain" nas 4 variantes** (normal, `render`, `premium`, `ultra_premium`). Não é
  questão de parâmetro. A auditoria de julho já registrava `esalq` quebrado em prod por isso.
- **Fonte do Porto = Notícias Agrícolas republicando o CEPEA**, bloco **"Indicador da Soja
  ESALQ/B3 - Paranaguá"** com `Fonte: Cepea/Esalq`, 2 casas e data de referência (160,14 em
  03/09). Tem página própria: `/cotacoes/soja/soja-indicador-cepea-esalq-porto-paranagua`
  (preferida) e aparece também em `/cotacoes/soja` (fallback). **Armadilha:** a linha "Porto
  Paranaguá (disponível)" da página geral é da **Insoy Commodities** (162,00), NÃO o CEPEA —
  a versão anterior desta spec presumia o contrário. **Casar por NOME em três níveis — bloco
  (título + fonte), coluna (`<th>` "Valor R$") e linha (data mais recente), nunca por posição**;
  dois blocos empatados na data com preços diferentes → erro, nunca escolhe às cegas. Testes
  provam: o 162,00 da Insoy nunca sai; coluna `Valor US$` injetada não engana; bloco Paraná
  injetado na página dedicada vira erro; tabela em ordem crescente devolve o dia certo.
- **Respostas 8 e 9 do primo (04/09 ~22h40, via Matheus):** (8) o 159,44 era só exemplo; a
  série é **Paranaguá** e a regra é **sempre o valor mais recente**. (9) o CEPEA do dia só sai
  **depois das 19h** → às 12h a mensagem carrega o valor de ontem (D-1), **sem data**, igual
  ao formato dele. O `data_ref` fica só no coletor/boletim, não na mensagem.
- Fonte caiu → a linha diz "indisponível"; **nunca some em silêncio**.

### Próximos passos (nesta ordem)

1. ✅ EM PROD (PR #27 mergeada 04/09 18h) `collectors/soja_disponivel.py`: Porto
   via NA (geral → dedicada → ScraperAPI; geral primeiro porque só lá cada bloco tem título
   próprio — 2ª revisão do Apolo) casado por nome; `BRL=X`; contrato mais curto por
   calendário (último dia útil antes do dia 15) + 404 do Yahoo. Endpoint
   `/api/collectors/soja_disponivel`. Medir: `python -m pytest backend/tests/test_soja_disponivel.py -q`.
   Conferir em prod depois do deploy: `curl -s https://noticiasgg.vercel.app/api/collectors/soja_disponivel`
   → 04/09 21:14 UTC: 200 em 0,8 s, três blocos OK a partir da Vercel. Apolo revisou 2x em 04/09: 3 furos posicionais
   provados por cenário e consertados; `market.collect()` agora projeta só `preco`/`variacao_pct`
   para não inchar o corpus do relatório (teto 6.000). `fetch_cbot`: 3 diretos, depois 1 ScraperAPI.
2. ✅ EM PROD (PR #28 mergeada 04/09 ~21h; deploy dos 2 projetos OK; 4 rodadas do Apolo) — fretes
   em `agent_config` chave `soja_fretes` (JSON pontal/uberaba/canarana), `services/soja_fretes.py`
   é a fonte única de ordem/rótulo/default (`PRACAS`); data e autor vêm de `updated_at`/
   `updated_by` da própria tabela (o `upsert_config` do backend passou a gravá-los). Painel:
   tela `/soja`. Boletim de saúde: check `soja_fretes` (só no completo, não no `/api/health`
   público) → ⚠️ se >60 dias, nunca salvo ou valor corrompido.
   Matheus salvou 9/12/27 em `/soja` em 04/09 21:16 (data e autor gravados, selo sumiu).
   Conferir no boletim de 05/09: "Fretes Soja Disponível: OK (0 dias)".
   Medir: `python -m pytest backend/tests/test_soja_fretes.py backend/tests/test_admin_soja_fretes.py -q`.
   Fora do escopo, registrado: o aviso viaja pelo mesmo WhatsApp que ficou mudo 35 h — só o
   alarme externo (UptimeRobot) fecha esse buraco.
3. ✅ CÓDIGO PRONTO (04/09, branch `feat/soja-msg`, 3 rodadas do Apolo) `services/soja_msg.py`:
   `montar()` pura (byte a byte com o exemplo, `/bushel`), `gerar()` nunca levanta e devolve texto +
   `indisponiveis`/`avisos` derivados do próprio texto (fonte caiu → linha `indisponível`; Supabase
   fora ou frete corrompido → 3 praças `indisponível`, nunca o padrão calado; praça ≤ 0 → indisponível
   + aviso). Prévia no painel `/soja` (`GET /api/admin/soja-preview`, timeout 10 s, com data do CEPEA
   e horário do pregão em BRT). Medir: `python -m pytest backend/tests/test_soja_msg.py -q`.
4. Cron 12h BRT (= 15:00 UTC) em `vercel.json` + endpoint com `check_cron_secret`, enviando à
   lista de alertas (hoje 2 pessoas).
5. Apolo antes do merge. Prova de campo: comparar com a mensagem que o primo manda no dia.

## Estado em 04/09/2026 — bot MUDO por ~35 h: a VPS reiniciou e a versão VELHA ganhou a porta

Descoberto por acidente, ao tentar mandar uma mensagem pelo bot. `/api/health` marcava
`evolution: warn (404)` — mas o boletim que avisaria viaja por WhatsApp, que era o que
estava quebrado. **Todos os alarmes tocam no mesmo sino.**

### Causa-raiz (medida na VPS)

A VPS reiniciou (`uptime` batia com os 35 h dos containers). No boot, o Docker subiu os
DOIS containers, porque os dois tinham `restart: always`:

| container | o que é | o que aconteceu |
|---|---|---|
| `evolution-api` (v1.8.2) | a versão VELHA, "parada para rollback" desde 16/07 | subiu e pegou a 8080 |
| `evolution-v2` (v2.3.7) | a de produção | perdeu a porta → `Exited (255)` |

Por isso o 404: o backend falava com a v1.8.2, que só conhece o backup
`noticiasgg.bak-20260714`. A instância viva e a sessão estavam intactas no `evo2-postgres`.
A bomba-relógio estava armada desde 16/07: "parada" só valia até o primeiro reboot, que
levou 7 semanas para acontecer.

### O conserto, e por que precisou de dois passos

1. `docker update --restart=no evolution-api && docker stop evolution-api` — permanente:
   a v1.8.2 nunca mais ganha a porta num reboot.
2. `docker start evolution-v2` NÃO bastou: o container ficou **sem rede** (não resolvia
   `postgres:5432`, loop de 24 reinícios). `docker compose up -d evolution` também não —
   viu o container existente e só deu start. O que resolveu foi
   `docker compose up -d --force-recreate evolution`, que remonta o container dentro
   da `evolution-v2_evo2`. A sessão do WhatsApp **sobreviveu** (sem QR code).

Conferir se voltou a acontecer (uma linha, de fora):
```bash
curl -s -H "apikey: $EVOLUTION_API_KEY" http://46.202.179.33:8080/instance/connectionState/noticiasgg
```
Esperado: `{"instance":{"instanceName":"noticiasgg","state":"open"}}`. Qualquer outra
coisa (404, vazio, `close`) = o bot está mudo.

### 🔴 04/09, 17h — A CHAVE DA EVOLUTION ESTAVA PÚBLICA DESDE 13/05, e foi TROCADA

Achado na conferência do reset da VPS: o repositório é PÚBLICO e a chave real da
API (a mesma do `docker-compose.yml`) estava em 6 arquivos versionados desde o
scaffold de 13/05 — `CLAUDE.md`, este arquivo, `docs/PLAN.md` e 3 exports do n8n.
Porta 8080 aberta para a internet, `ufw` inativo: qualquer um com um `curl` mandava
mensagem em nome do bot.

**Feito em 04/09:** chave nova gerada, trocada no compose da VPS (backup em
`docker-compose.yml.bak-20260904`), container recriado, chave velha responde **401**,
`EVOLUTION_API_KEY` trocada na Vercel + redeploy, `/api/health` = `ok`/`open`, `.env`
local atualizado, e a chave saiu dos 6 arquivos (placeholders). **Privar o repo não
bastaria**: o que ficou 4 meses público trata-se como queimado — a troca é o conserto.

**17h36 — `ufw` LIGADO** (nega o que entra; libera 22/tcp, 8080/tcp, `tailscale0` e
41641/udp). Provado: `/api/health` `ok`/`open` depois. ⚠️ Porta publicada pelo Docker
passa por fora do ufw: a 8080 ficaria aberta de qualquer jeito — quem protege a
Evolution é a chave, não o firewall. Ainda em aberto: tornar o repositório privado.

### ⚠️ Pendência que este incidente abriu

**O sistema não tem como avisar quando o WhatsApp cai** — health digest e `notify_admin`
dependem dele. Precisa de um segundo canal (e-mail, Telegram, ou o próprio `/api/health`
vigiado por um serviço externo tipo UptimeRobot, que é grátis). Sem isso, a próxima queda
só é descoberta quando alguém estranhar o silêncio.

## Estado em 31/08/2026 — plano anti-alucinação COMPLETO, e um ponto cego achado no caminho

As quatro stories estão em produção. Também subiu, fora do plano, o conserto do
monitoramento que o próprio dia expôs.

| Story | O que faz | PR |
|---|---|---|
| 1 | o alerta grava a notícia que enviou | (18/08) |
| 2 | o agente consulta o que ele mesmo mandou | #13, provada em campo 5/5 |
| 3 | o corretor liga na conversa | #20 |
| 4 | evals que prendem o comportamento | #21 |
| — | `/api/health` enxerga a Anthropic | #22 |

### O incidente do dia: o saldo acabou e NADA avisou

O saldo da conta Anthropic zerou em produção. `/api/health` respondia `keys: ok`
— porque só conferia se a variável de ambiente EXISTE, não se ela FUNCIONA — e o
cron de alertas caía num `except Exception: logger.warning(); continue`, logando
um aviso por notícia a cada 15 minutos, para sempre. **O agente ficou mudo e o
painel ficou verde.** O Matheus descobriu à mão, porque um eval falhou.

Conserto em duas camadas, porque são duas falhas diferentes:

- **imediata:** o cron separa o que adianta repetir (timeout, 529) do que não
  adianta (saldo, chave revogada, chave sem permissão). O que não adianta para o
  laço e vai para o WhatsApp do dono.
- **diária:** o boletim sonda a API de verdade. `models.list()` NÃO serve — responde
  200 com saldo zerado, porque não é inferência. Só o endpoint de mensagens recusa
  por cobrança.

A sonda mora em `collect_status_completo` (com senha), **nunca** no
`collect_status`: `GET /api/health` é público, e chamada paga em endpoint aberto é
convite para esvaziarem o saldo. Há teste que reprova se ela vazar para lá.

### Custo dos evals — medido, não estimado

Uma passada completa: **US$ 0,62** (42 chamadas Sonnet + 11 Haiku, 190 s). Por isso
o cron foi para **mensal** (`0 9 1 * *`), não semanal: o número não muda de semana
para semana — o que muda é modelo e prompt, e esses mexem em release. Rodar à mão:
aba Actions → Run workflow.

Medir de novo (nunca confiar no número escrito aqui):
```bash
PYTHONPATH=. python -m backend.evals.news_recall_eval
```

### Prova de campo da Story 3 — feita em 01/09/2026

Pergunta que força busca + leitura de matéria ("o que saiu hoje sobre o preço do boi
gordo?"). **O corretor não apagou dado bom**: voltou com faixa do físico (R$ 338–344/@),
variação do dia, spot da B3, três vencimentos futuros e quatro estados. Latência 16 s —
sem regressão.

⚠️ **Ressalva:** "o corretor rodou" é INFERIDO (resposta rica + tempo compatível), não
observado — os 16 s de referência vinham de uma pergunta SIMPLES, então não isolam os
2,3 s dele. O que está provado é a **ausência do dano**, que era o risco: resposta vaga e
sem número. Para observar de verdade seria preciso ler o log da Vercel.

### O que as revisões acharam, e vale lembrar

Quatro rodadas do Apolo, e o padrão se repetiu em todas: **medida que fica verde
sem medir nada.**

- o `| tee` do CI engolia o código de saída — os três evals nunca podiam falhar;
- a coerência do eval conferia se o número estava numa lista branca, então
  61% → 62% → 51% para o milho passava como coerente (a forma exata do incidente);
- o `regex` das armadilhas nunca era comparado com a resposta;
- três respostas educadas e vazias davam cartão perfeito;
- o portão de 100 caracteres do validador descartava justamente a correção BEM feita.

E duas vezes o instrumento estava errado, não o código: a "recuperação do registro"
era adivinhada no texto da resposta quando dava para **espionar a chamada da
ferramenta**. Trocado o instrumento, o número saiu 5/5 onde a heurística dizia False.

## Estado em 20/08/2026 — Story 2 (`get_sent_news`) NO AR e provada em campo (5 de 5)

PR #13 mergeada (`ebe6268`), branch apagada, **deploy confirmado em produção**: o
`/api/health` respondeu com o campo `entregas_registradas`, que só existe no código novo.
Depois vieram as provas em WhatsApp real (seção mais abaixo) e o conserto que a prova 3
achou — PR #16, `5a550df`.
O agente de chat ganhou a ferramenta para consultar os alertas de notícia que ele mesmo
enviou — "essa notícia que você mandou" deixa de ser adivinhação a partir do título.

| Commit | O que é |
|---|---|
| `2938494` | a ferramenta, o despacho, a regra de prompt |
| `6a7942b` | consertos dos achados 1, 2, 4, 5, 6, 7, 8, 9, 10 do Apolo |
| `c356d8e` | achado 3 — escopo por destinatário |
| `6c532a0` | janela de tempo cortada duas vezes apagava o sinal `truncado` |
| `100035f` | achados 11–14 da segunda passada |

**O corte de 20 itens NÃO é caso raro.** O `/api/health` do deploy respondeu
`broadcasts_24h: 17` — na janela padrão de 72 h a lista estoura o teto quase sempre, e
`truncado`/`cobertura_desde` viram o caminho normal, não a exceção. Conferir o número de
novo (nunca acreditar no que está escrito aqui):

```bash
curl -s https://noticiasgg.vercel.app/api/health | python -c "import sys,json;print(json.load(sys.stdin)['checks']['news_log'])"
```

**O plano escrito estava desatualizado em dois pontos** e seguir ele ao pé da letra teria
embutido bug: `supabase.get_news_log` devolve `{"itens": [...]}` e não uma lista, e o plano
achatava "dia calmo" e "a consulta falhou" num aviso só — que é a negativa autoritária que o
achado A5 da revisão de 18/08 existe para impedir. Corrigido com o campo `consulta_ok`.

### As quatro bordas onde o agente afirmaria o que não conferiu

Todas fecham com um campo na saída da ferramenta + uma regra de prompt, não só com prompt:

| Borda | Campo que a fecha |
|---|---|
| a consulta ao Supabase falhou | `consulta_ok: false` — "não conferi", nunca "não mandei" |
| a lista bateu no teto de 20 itens | `truncado` + `cobertura_desde` |
| o alerta foi para outra pessoa | filtro por `news_log_messages.phone`; sem telefone, campo `escopo` |
| a notícia veio pelo relatório diário | regra 8 do prompt (`log_sent_news` só é chamada pelo `alert_checker`) |

### Dois defeitos que a revisão do Apolo achou com medição em produção

1. **`url_publisher` do RSS é o domínio pelado**, não a matéria — `web_search._url_canonica`
   já dizia isso e a primeira versão da ferramenta o entregava mesmo assim. O `read_article`
   nele **não dá erro**: devolve o MENU da capa como se fosse o artigo. Agora existe
   `_link_da_materia()` como fonte única, e o link do Google Notícias (403 no clique) some
   em vez de virar fallback — inclusive no caminho ancorado, onde o conserto de 19/08 só
   tinha sido feito pela metade.
2. **O corte em 20 itens já esconde notícia hoje.** Medição do Apolo em 20/08: 25 alertas nas
   últimas 72 h. Sem declarar o corte, o modelo lia "consulta ok + não está na lista" e negava.

### Uma capacidade que eu ACEITEI perder — dito em voz alta

`_link_da_materia` devolve vazio para link do Google Notícias. Certo para o humano
(403 no clique), mas o link do Google **não é inútil para a máquina**:
`web_search.read_article` sabe tratá-lo (`resolve_google_news`, ~1 s, zero crédito;
falhando, `render=true`, ~35 créditos e 37–57 s). O caminho ancorado, portanto,
tinha como recuperar a matéria a partir dele — e não tem mais.

Tamanho da perda, medido: 5 de 25 linhas ficam sem link; **4 dessas têm `conteudo`
capturado** (o bloco `<noticia_citada>` já traz o texto e não precisa de link).
Sobra **1 linha em 25 (4%)** sem texto e sem link, onde o agente agora não tem por
onde recuperar a matéria. Aceito: 24 de 25 têm `conteudo`, a captura está saudável.
Se um dia isso incomodar, o caminho é um campo separado (`url_para_ferramenta`, com
ordem explícita de não exibir), **nunca** o fallback antigo no campo `url` — isso
reabriria o 403 na cara do usuário.

### Duas coisas latentes, medidas com ZERO ocorrências hoje

- **Sem `UNIQUE (news_log_id, phone)` em `news_log_messages`**, e o `_RetryTransport`
  repete POST. Duplicata encolheria a lista entre as duas consultas. O sinal
  `truncado` já saiu de `len(itens)` e passou para quem aplica o teto, então o
  defeito não morde mais o agente — mas o índice ainda é barato e correto.
- **`log_alert_messages` é best-effort** (engole exceção; descarta entrega sem
  `message_id`). Se secar, o agente nega para quem recebeu. `/api/health` passou a
  vigiar com `entregas_registradas`.

### ✅ PROVA DE CAMPO — as 5 feitas em WhatsApp real (4 em 20/08, a 5ª em 31/08)

| # | Prova | Resultado |
|---|---|---|
| 1 | "qual a última notícia que você me mandou?" | ✅ título, jornal, data e link, todos conferindo com a conversa |
| 2 | Clicar no 🔗 da resposta | ✅ abriu a matéria |
| 3 | Perguntar por alerta além do corte | ✅ **depois do conserto** — ver abaixo |
| 4 | Resposta citando alerta, cronometrada | ✅ 13 s citada contra 16 s de pergunta comum: a citada é **mais rápida**, a exceção do bloco ancorado pegou |
| 5 | Outro número, sem `alerts_enabled` | ✅ **31/08** — não inventou título nem horário |

**As cinco fecharam.** A prova 5 era a única que ainda podia produzir mentira com data e
fonte: outra pessoa, autorizada mas fora da lista de alertas, perguntando "qual a última
notícia que você me mandou?". O agente respondeu que não tinha notícia recente para ela,
sem inventar título nem horário — o filtro por `news_log_messages.phone` segurou.

⚠️ **Meio grau de folga na redação, anotado e não consertado:** a frase foi sobre O MUNDO
("não tem notícias recentes"), não sobre O REGISTRO ("não te mandei alerta nenhum"). O
risco real (título falso com hora) não aconteceu, mas a forma certa é falar do registro.
Se reaparecer, é aperto de uma frase na regra 7.

**A prova 3 passou TORTO na primeira vez, e foi o achado mais valioso do dia.** O
comportamento estava certo (não negou, pediu o link), mas a frase dizia *"os últimos ~90
dias"* — o **teto do parâmetro `horas`**, não o que ele leu. Ele tinha visto ~28 h.
Número grande e falso primeiro, ressalva vaga depois: a forma exata do defeito que este
projeto existe para matar. **Nenhum dos 571 testes pegaria isso** — teste não lê a frase
que chega no celular.

Conserto em `5a550df` (PR #16): regra 7a manda dar a data de `cobertura_desde` em
português, e a descrição do parâmetro parou de anunciar "90 dias" (era de lá que o modelo
tirava o número). Reconferido no mesmo alerta:

> "a lista cobre a partir de **19/08 pela manhã** e está truncada em 20 itens, então pode
> ser algo mais antigo ou do relatório diário"

Cruzamento independente: 20 itens ÷ 17 alertas/dia = **28,2 h**; 28 h antes das 11h46 de
20/08 cai em 19/08 de manhã. A data do agente e a conta batem por caminhos separados. De
quebra, a regra 8 (relatório diário) disparou sozinha na mesma frase.

### O roteiro das provas, para reusar

Com o que é passar e o que é falhar lado a lado:
https://claude.ai/code/artifact/f21bd8eb-00ea-4446-8dff-38756431a0e1

Resumo das cinco:

1. **Link:** pergunte sobre um alerta cujo `url_final` seja nulo e **clique no link** que ele
   devolver. Passa = abriu a matéria, ou o agente disse que não tem o endereço.
2. **Corte:** pergunte por uma notícia de anteontem. Passa = ele diz até onde enxerga e pede
   o link. Falha = "não te mandei nada sobre isso".
3. **Escopo:** um usuário SEM `alerts_enabled` pergunta "qual a última notícia que você me
   mandou?". Falha = veio título e data de um alerta que ele nunca recebeu.
4. **Ancorada:** responda citando um alerta e cronometre. Se aparecer
   `reporter tool round 1/6: ['get_sent_news']` no log da Vercel, a exceção do
   `<noticia_citada>` não pegou e o caminho determinístico está sendo roubado.

Quantos alertas existem na janela (o número que decide se o corte morde):
```bash
python -X utf8 -c "import os,pathlib;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];import datetime;from backend.services import supabase as s;c=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=72)).isoformat();r=s._client().get('/news_log?select=id,sent_at,url_final&sent_at=gte.'+c+'&order=sent_at.desc&limit=200').json();print(len(r),'alertas em 72h |',sum(1 for x in r if not x['url_final']),'sem url_final')"
```

**Rollback:** os três commits só tocam `reporter.py`, `supabase.py`, `main.py` e testes. Não
há migration nova. Reverter a branch derruba a ferramenta inteira sem mexer em banco.

---

## Estado em 19/08/2026 — os 3 defeitos da validação CONSERTADOS e EM PRODUÇÃO

Migration 009 rodada (conferida no sistema: `select=url_final` → 200), commit `18e9cb0`
pushado às 16h08, **build READY nos dois projetos Vercel** — o `trafilatura` coube no pacote,
que era o único risco não mensurável antes do deploy. `/api/health` respondeu 200 com tudo
`ok` e a Evolution `open`. Suíte verde (`pytest backend/tests/ -q` conta quantos).

✅ **PROVA DE CAMPO FEITA em 19/08, dois alertas reais:**

| | 16h16 · Backwardação de Cobre (oilprice, link direto) | 17h32 · CBOT Semanal (feed `GN USDA/WASDE`, Grainews) |
|---|---|---|
| `url_final` | URL completa do artigo (veio da canônica) | `grainews.ca/daily/cbot-weekly-crop-tour-usda-data-lift-prices/` — **resolvido pelo Google, do IP da Vercel** |
| `conteudo_fonte` | `read_article:trafilatura` | `read_article:trafilatura` |
| texto | 3149 chars, começa no 1º parágrafo | 3163 chars, começa na manchete + 1º parágrafo |

O segundo é o que importa: o link do Google (`news.google.com/rss/articles/CBMif0...`) foi
trocado pelo do jornal **em produção**. A hipótese de o `batchexecute` recusar IP de
datacenter — a única que não dava para testar da máquina local — caiu.

⚠️ **Defeito 2 (sigla) ainda NÃO foi exercitado**: nenhum dos dois títulos tinha sigla com
forma em português. `USDA` e `CBOT` ficaram como estão, que é o comportamento certo, mas
`OPEC→OPEP` só se confirma quando sair notícia de petróleo. Fica em observação.

Conferir de novo (o comando serve para qualquer alerta):
```bash
python -X utf8 -c "import os,pathlib;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];from backend.services import supabase as s;r=s._client().get('/news_log?select=sent_at,titulo_pt,url,url_final,conteudo_fonte,conteudo&order=sent_at.desc&limit=1').json()[0];print(r['sent_at'],r['titulo_pt']);print('url_final:',r['url_final']);print('fonte:',r['conteudo_fonte'],'|',len(r['conteudo'] or ''),'chars');print((r['conteudo'] or '')[:400])"
```

### O que mudou, defeito por defeito

**1. O 🔗 dava 403** — a mensagem levava o link do Google Notícias. O conserto que estava
planejado (ler a canônica da página que o `render=true` resolve) foi TROCADO por um caminho
mais simples achado na revisão: **o próprio Google responde o endereço real da matéria** pelo
endpoint `batchexecute` (`web_search.resolve_google_news`). Custa ~0,5s e ZERO crédito de
ScraperAPI, contra 35 créditos e ~57s do render. Efeitos em cadeia:

- O 🔗 sai com o link do publicador (`alert_checker._link_para_mensagem`).
- Com o endereço real na mão, a leitura da matéria **dispensa o render** — 1 crédito, ~3s.
- A captura do texto **continua DEPOIS do envio** — e agora depois também da marca de dedup (a
  inversão chegou a ser implementada e foi desfeita: ler a matéria antes de enviar põe o alerta
  atrás de uma chamada SEM teto real de tempo, e um estouro dos 300s da Vercel deixaria de sair
  alerta nenhum). ⚠️ O `timeout` do httpx é por OPERAÇÃO, não prazo absoluto: medido, 1,0s pedido
  virou 15,25s reais num servidor gotejando. Por isso a leitura ficou por último e o texto entra
  por um UPDATE (`supabase.update_news_log_conteudo`) — estourar ali custa o texto, nunca um
  reenvio da mesma notícia.
- A canônica (`_url_canonica`) ficou como **rede de segurança**, e só vale quando o host bate
  com o da página lida **ou** com o do publicador do feed (`<source url>` do RSS) — sem essa
  conferência, quem entrasse no índice do Google escolheria o destino do link que o bot entrega.
- A resolução tem prazo ABSOLUTO (`web_search._GN_PRAZO`), não o timeout por operação do httpx:
  medido, um servidor gotejando segura 40s com timeout de 10s.

⚠️ `resolve_google_news` usa endpoint INTERNO do Google, não documentado: pode mudar sem aviso,
e o IP de datacenter da Vercel pode receber uma página de consentimento em vez do artigo (medi
do IP daqui, não do de lá). Falhar devolve `""` e tudo volta ao comportamento anterior.

**2. Sigla em inglês no título em português** — parágrafo novo em `_NEWS_CLASSIFIER_SYSTEM`
mandando traduzir sigla de organização com forma consagrada (OPEC→OPEP, UN→ONU, WTO→OMC,
IMF→FMI, NATO→OTAN) e proibindo inventar tradução das que não têm (Fed, USDA, WASDE, EIA).

**3. O `conteudo` era entulho do site** — `trafilatura` extrai o corpo antes do truncamento
(`web_search._extrai_corpo`), com o caminho antigo (bs4 + remoção de tags) como rede. Duas
travas nasceram junto: piso de `_MIN_ARTICLE_CHARS` (a página não renderizada do Google devolve
a string `"Google News"`, 11 chars, e isso virava âncora) e rótulo do extrator em
`conteudo_fonte` (`read_article:trafilatura` × `read_article:html_bruto`), sem o qual não dá
para medir se o entulho voltou.

### Medir de novo (não confie no número escrito, rode o comando)

Ponta a ponta no último link do Google Notícias registrado — resolve, lê, e mostra de onde veio:

```bash
PYTHONPATH=. python -X utf8 -c "import os,pathlib,time;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];from backend.services import alert_checker as a, supabase as s;r=s._client().get('/news_log?select=titulo_pt,url&url=like.*news.google.com*&order=sent_at.desc&limit=1').json()[0];t=time.monotonic();L=a._link_para_mensagem(r['url']);print(f'{time.monotonic()-t:.1f}s',L);c=a._capture_conteudo(L);print(len(c.conteudo or ''),'chars ·',c.fonte);print((c.conteudo or '')[:300])"
```

Quantos alertas da semana caíram na rede de segurança do extrator (deve ser perto de zero):

```bash
PYTHONPATH=. python -X utf8 -c "import os,pathlib,collections;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];from backend.services import supabase as s;rows=s._client().get('/news_log?select=conteudo_fonte&order=sent_at.desc&limit=100').json();print(collections.Counter(r['conteudo_fonte'] for r in rows))"
```

### Ordem de deploy — a migration vem ANTES do push

Fora de ordem, o estrago é silencioso: com o código novo em produção e a coluna `url_final`
ausente, o PostgREST devolve 400, `log_sent_news` perde a linha INTEIRA e
`get_news_by_message_id` para de achar a notícia citada — a Story 1b morre calada. E
`get_news_log` (painel/Story 2) passa a devolver lista vazia com aviso, que é negativa
autoritária sobre notícia que EXISTIU.

Quando isso dispara: sempre que a RESOLUÇÃO do link der certo — não a captura. O `url_final`
do INSERT vem de `_link_para_mensagem`, que roda antes do envio; campo preenchido = payload
com coluna inexistente = 400. Medido em 19/08/2026: **39 de 40** links reais do Google
Notícias resolveram. Ou seja, ~97% dos alertas perderiam o registro, e o alerta continuaria
saindo normalmente — só um `logger.warning` denuncia.

1. Rodar `backend/migrations/009_news_log_url_final.sql` no SQL Editor do Supabase.
2. Conferir: `/news_log?select=url_final&limit=1` devolve 200.
3. `git push origin master`.
4. No primeiro alerta: o 🔗 abre no navegador? `conteudo` começa no corpo da matéria?

Rollback: `web_search.py` e a migration são compatíveis para trás; se algo der errado, reverter
só `alert_checker.py`.

---

## Estado em 18/08/2026, 23h — PRIMEIRA VALIDAÇÃO EM PRODUÇÃO: a âncora funciona, 3 defeitos (CONSERTADOS em 19/08 — ver acima)

Merge feito (`755b991`, deploy READY). Às 22:47 saiu o primeiro alerta com o código novo, e
às 23:04 o Matheus respondeu CITANDO a mensagem. **A ancoragem funcionou de ponta a ponta**:
o webhook casou o `stanzaId`, o bot leu o `conteudo` guardado e respondeu com a matéria na
mão. Notícia: *"Produção de Petróleo dos EAU Aproxima-se do Recorde Após Saída da OPEC"*
(fonte real EnergyNow, feed `GN OPEP`).

**Grounding medido, afirmação por afirmação, contra o `conteudo` guardado — 7 de 8 ancoradas:**
`3.8 million` ✅ · `June` ✅ · `May 1` ✅ · `ADNOC` ✅ · `126` ✅ · `72` ✅ · `OPEC exit` ✅ ·
**`April 2020` ✗ não está no texto capturado.**

Refazer a medição em qualquer notícia:
```bash
python -X utf8 -c "import os,pathlib;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];from backend.services import supabase as s;r=s._client().get('/news_log?select=titulo_pt,url,url_publisher,conteudo_fonte,conteudo&order=sent_at.desc&limit=1').json()[0];print(r['titulo_pt']);print(r['url'][:90]);print('conteudo:',len(r['conteudo'] or ''),'chars')"
```

### Os 3 defeitos, na ordem acertada com o Matheus (consertar ANTES da Story 2)

**1. O 🔗 da mensagem dá 403.** Mandamos o link do Google Notícias
(`news.google.com/rss/articles/CBMi...`), que o navegador recusa. A ironia: a captura
**funcionou** (`conteudo_fonte = read_article`, 4000 chars do EnergyNow) e sabemos o veículo
(`url_publisher = https://energynow.ca`) — só que `url_publisher` é o **domínio**, não o
artigo. **Conserto:** capturar o endereço canônico que o render resolveu (`<link rel=canonical>`
/ `og:url` da página lida) e mandar ESSE no 🔗. O link do Google continua no banco para dedup.

**2. Sigla em inglês dentro de título em português.** `titulo_pt` saiu *"...Após Saída da
OPEC"*. O bot respondeu "OPEP" — **o bot está certo**, o classificador é que traduziu a
manchete e deixou a sigla. **Conserto:** uma frase em `_NEWS_CLASSIFIER_SYSTEM` mandando
traduzir também sigla de organização (OPEC→OPEP, UN→ONU...).

**3. O `conteudo` capturado é majoritariamente ENTULHO do site.** Dos 4000 chars guardados, o
começo é menu, "Sign Up for FREE Daily Energy News" e **manchetes de OUTRAS notícias**
("Data Center Gas Plants...", "Venezuela Oil Output..."). `read_article` remove
`script/style/nav/footer/header/aside`, e o boilerplate deste site não está nessas tags.
Dois estragos: gasta o teto de 4000 chars com lixo (provavelmente foi o que cortou o miolo
onde estaria o `April 2020`), e enfia manchete de outro assunto dentro da âncora daquela
notícia. **Conserto:** extrair o corpo do artigo (heurística de densidade de texto, `<article>`,
ou similar) antes de truncar.

⚠️ **A leitura do Google Notícias é INSTÁVEL em tamanho.** A captura de produção trouxe 4000
chars; refazendo a mesma leitura 20 min depois vieram **520 chars**. Por isso **não dá para
afirmar que o bot inventou o "abril de 2020"** — pode ter sido truncado. Fica em aberto até
o defeito 3 estar consertado.

**Depois dos 3: Story 2** (ferramenta `get_sent_news` no chat).

---

## Estado em 18/08/2026 — alucinação em conversa: Story 1 ENTREGUE, faltam 2, 3 e 4

**O incidente.** Às 12:00–12:11 de 18/08 o agente respondeu cinco vezes sobre o mesmo
relatório do USDA e deu números e datas diferentes em cada uma (milho 67%→63%, depois
72%, depois 63%→61%; datas 12/08/2026, 12/08/2025, 04/08/2026, 10/08/2026). Numa das
respostas ele mesmo escreveu *"inventei percentuais que não vieram de fonte"* — e na
mensagem seguinte, para o outro número, inventou de novo. Os dois telefones
(`5534999945010` e `5516991016898`) receberam versões diferentes do mesmo fato.

Conversa lida direto de `conversation_history` no Supabase, não de memória.

**Três causas, medidas no código — não teorizadas:**

1. `services/integrity.py:54` — `validate_and_fix` retorna cedo quando a resposta não
   tem `ANALYSIS_MARKERS` (`📊`, `ANÁLISE`, `Visão Macro`…). Resposta de conversa nunca
   tem esses marcadores. **O validador anti-alucinação está desligado em 100% dos
   chats.** A correção anterior (jul/2026) cobriu só o relatório diário.
2. `services/integrity.py:56` — `build_fact_corpus(data)` monta o corpus só dos
   coletores (`market`, `crypto`, `indicators_*`, `commodities_br`, `news`). O que
   volta de `search_web`/`read_article` — a fonte real do número do USDA — **não entra
   no corpus**. Mesmo ligado, o validador conferiria contra o corpus errado.
3. `services/alert_checker.py:479-490` — o alerta de notícia sai por `_broadcast` e o
   único rastro é o hash em `sent_news` (`_mark_sent`). **Nunca há `save_message`**,
   nem título, link ou data em forma legível. Quando o usuário responde "me fale mais
   sobre essa notícia", o agente não tem vestígio nenhum dela e preenche do nada.

**Plano:** `docs/superpowers/plans/2026-08-18-noticias-ancoradas-e-antialucinacao.md`
4 stories, ordem obrigatória: (1) tabela `news_log` + link no alerta; (2) ferramenta
`get_sent_news` no chat; (3) validador ligado em chat com corpus de ferramenta + data
de hoje etiquetada `<hoje>`; (4) evals no CI com a conversa real como fixture.

### Story 1 — ENTREGUE no código (branch `feat/noticias-ancoradas`, não mergeada)

Tabela `news_log` (migration 007) com título, veículo real, link, data, resumo e nota;
`log_sent_news`/`get_news_log`; o alerta grava depois de entregar e mostra o 🔗 na
mensagem; cross-check no boletim diário acusa escrita silenciosa. Stories 2, 3 e 4
**não foram começadas**.

✅ **A migration FOI executada em 18/08** — conferido na fonte viva: tabela existe e as
15 colunas que o código lê respondem 200. Fica o aviso para o futuro: ela roda À MÃO no
SQL Editor, e se um dia alguém recriar o ambiente e esquecer, `log_sent_news` engole a
falha de propósito (para não derrubar alerta já entregue) e o registro fica vazio para
sempre — o sintoma aparece só no `/api/health` como `warn: registro indisponível`.
Conferir na fonte viva, nunca no documento:
```bash
python -X utf8 -c "import os,pathlib;[os.environ.setdefault(k.strip(),v.strip().strip(chr(34))) for k,v in (l.split('=',1) for l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines() if '=' in l and not l.strip().startswith('#'))];from backend.services import supabase as s;print('news_log ->', s._client().get('/news_log?select=id&limit=1').status_code)"
```
`200` = existe · `404` = não rodou.

**Limite conhecido da Story 1, medido:** para as notícias dos 6 feeds de busca do Google
Notícias — inclusive a do incidente — a âncora é fraca. O `url` é uma página JS que o
`read_article` não lê, o `url_publisher` é só o domínio, e o `resumo_fonte` do RSS vem
como markup (10 de 20 feeds) ou vazio (3 de 20). Sobra título + veículo. **A Story 1
sozinha não cura o caso do USDA** — depende da Story 3.

### Parte A/B/C — conteúdo capturado + id de mensagem + resposta ancorada (18/08, branch `feat/noticias-ancoradas`)

Os dois furos que o dono apontou na Story 1 (registro guarda PONTEIRO, não a notícia;
"qual notícia é essa" era o modelo escolhendo entre 20) — fechados no código, **migration
008 ainda não rodou em produção** (ver `backend/migrations/008_news_log_conteudo_e_mensagens.sql`,
igual à 007: SQL Editor, à mão).

- **Parte A** — `news_log.conteudo`/`conteudo_fonte`: `alert_checker._capture_conteudo`
  chama `web_search.read_article` DEPOIS do broadcast (alerta já entregue), grava o
  texto ou `None` (nunca markup, nunca a página de erro do Google).
- **Medição real dos 20 feeds (18/08/2026):** 14 de 20 (os RSS diretos) devolvem texto
  útil de cara. **Os 6 feeds `GN *` devolviam 404 em 6 de 6** — confirmado o que o ESTADO.md
  já suspeitava. Achado o caminho: `render=true` do ScraperAPI (executa o JS do
  redirecionamento) resolveu **6 de 6** na medição original. Implementado em
  `web_search.read_article` — só ativa para host `news.google.com` (comparado por hostname,
  não substring — achado 3 da revisão do Apolo corrigiu um `"news.google.com" in url` que
  também casava domínio hostil tipo `evil.com/?x=news.google.com`), nunca para o tráfego
  geral da tool (o agente de chat também usa `read_article` livremente — por isso
  `read_article` impõe piso de 75s no timeout quando o render liga, achado 2 da revisão).
  **Números corrigidos pela revisão do Apolo (achado 5, mesma data, 5 chamadas reais lendo
  o header `sa-credit-cost`):** custo real é **35 créditos por chamada, não 10** (a medição
  original tinha lido errado); tempo real é **37,4–56,6s por link, não 18–49s**; e **1 das 4
  chamadas com render devolveu HTTP 500** — a medição original ("6 de 6") não tinha pegado
  essa falha. Custo diário: no máximo 1 render por rodada de `check-alerts` (só quando a
  notícia VENCEDORA é de feed GN), teto de 24 alertas/dia → pior caso **~840 créditos/dia**
  (não ~240). A decisão sobrevive à correção: conta tinha `creditsLeft 87129` de `100000`
  em 18/08 (medir de novo: `curl "https://api.scraperapi.com/account?api_key=$SCRAPER_API_KEY"`),
  basal ~460 créditos/dia sem render + ~840 com render ≈ 1.300/dia ≈ 39.000/mês — cabe
  dentro dos 100.000/mês. `_CONTEUDO_TIMEOUT` = 75s (~1,3× o pior caso medido, 56,6s — não
  1,5×), roda só depois do alerta já ter saído.
- **Parte B** — `news_log_messages` (novo, migration 008): `alert_checker._broadcast_com_ids`
  (nova função, só usada por `_check_news` — os outros 3 chamadores de `_broadcast`
  ficaram intocados) devolve `(phone, message_id)` de cada entrega; `log_sent_news` passou
  a devolver o `id` da linha inserida; `supabase.log_alert_messages` grava um par por
  destinatário.
- **Parte C** — `main.py:_extract_quoted_message_id` lê `contextInfo.stanzaId` do TOPO do
  registro (formato medido ao vivo em 18/08 para texto simples) com fallback para dentro
  de `extendedTextMessage`; `supabase.get_news_by_message_id` casa por igualdade de string;
  se achou, `reporter.generate_report(..., anchored_news=noticia)` injeta um bloco
  `<noticia_citada>` no prompt (`reporter._format_anchored_news`) — determinístico, o
  modelo não escolhe entre candidatas. Sem conteúdo capturado, o bloco diz explicitamente
  "não capturado — diga isso e não invente". O bloco escapa `<`/`>`/`&` de todo campo
  (`reporter._escape_untrusted_text`) e avisa que o conteúdo é DADO de terceiro, não
  ORDEM — fechado na revisão do Apolo de 18/08 (achado 1: artigo hostil conseguia fechar
  a tag e injetar instrução no turno do usuário).
- Testes: `backend/tests/test_news_log.py` (Partes A/B), `test_web_search.py` (render
  fallback, piso de timeout do render, host do Google Notícias por hostname),
  `test_reporter_sections.py` (bloco ancorado + neutralização de injeção),
  `test_alert_checker.py` (`_broadcast_com_ids` executada de verdade, não só mockada),
  `test_webhook_anchored_news.py` (novo arquivo, extração do id + integração do webhook).
  `pytest backend -m unit` → 391 passed, 0 failed (era 341 no início da sessão, 381 antes
  da revisão do Apolo de 18/08).

### Varredura de credencial (fora do plano, virou metade da sessão)

Revisando a Story 1, o Apolo achou que erro de fornecedor voltava CRU para o contexto
do agente e para o `conversation_history`. Como o ScraperAPI põe a chave no endereço,
a `SCRAPER_API_KEY` vazava — e o Matheus a rotacionou em 18/08. A varredura completa
achou **6 caminhos**, não 1: `web_search`, `agro_search`, `market`, `esalq`, `eia`
(chave da EIA) e `investing_calendar` (esse vazava por três saídas ao mesmo tempo:
log, WhatsApp do admin e resposta pública da API). `indicators_us` não tinha proteção
por série nenhuma — um soluço do FRED mandava a chave dele para toda conversa.

Fechado com `services/secrets_mask.py` (módulo neutro, para coletor não depender de
serviço) e máscara nos dois `_safe_collect`, que são os pontos únicos por onde todo
coletor passa antes de entrar no prompt. **Regra que ficou: erro de fornecedor externo
nunca volta cru para dentro do contexto do agente.**

**Como conferir que a correção pegou, depois de implementada:**
`python -m backend.evals.news_recall_eval` — meta: `recuperou_do_log` igual a `casos`,
`armadilhas` em zero.

## Estado em 14/08/2026 — alerta de notícia sem o parágrafo de análise

A pedido do Matheus, o alerta de notícia passou a ser **manchete + fonte + linha de
impacto**. O parágrafo de análise (campo `resumo` do classificador) saiu da mensagem.

**O campo `resumo` continua no JSON do prompt de propósito** — não é sobra para limpar.
Ele é escrito antes de `ativos`/`direcao` e funciona como rascunho para eles. Medido em
14/08 sobre 36 notícias reais: tirar o campo do prompt muda a lista de ativos em ~metade
dos casos e **não economiza token** — sem o campo, o modelo escreve a análise em prosa
solta depois do JSON, que o leitor descarta. Há teste prendendo tanto o formatador
quanto o caminho real de envio (`test_alert_checker.py`).

Observar: se aparecer alerta "pelado" (sem a linha de impacto), é porque o classificador
devolveu `ativos` vazio — nesse caso a mensagem fica só com o título. Não foi observado
em produção; o conserto barato seria exigir `ativos` no prompt para nota ≥ 5.

⚠️ **A medição das 36 notícias é datada (14/08/2026) e NÃO tem comando que a refaça** —
foi feita à mão, rodando as mesmas notícias pelos dois prompts e comparando `ativos` e
contagem de tokens. Quem quiser contestar precisa repetir assim. O que ficou automático
é só a trava: `test_classifier_prompt_tem_contrato_v2` reprova se o campo `resumo` sair
do prompt.

## Estado em 13/08/2026 — suíte de testes estabilizada e portão do CI ampliado

O pedido era consertar falhas intermitentes da suíte, atribuídas a bloqueio de cota
(rate limit) das APIs de fornecedor. **A instabilidade não reproduziu:** 8 rodadas
completas no dia, todas verdes. O bloqueio do CoinGecko é episódico, não permanente —
a evidência da manhã é real, mas não se reproduz sob demanda.

O que a medição achou de fato:

1. **O portão do CI mentia.** O `ci.yml` roda `pytest backend -m unit`, e o marcador
   `unit` promete "sem rede". Um teste marcado assim saía para a internet. Pior: o
   furo **pulava de teste em teste** conforme a ordem, porque a configuração fica
   guardada em memória e só o primeiro da fila paga a conexão.
2. **O portão cobria pouco.** 265 dos 334 testes ficavam fora dele — inclusive os 47
   de `test_alert_checker.py`, o coração do pipeline de alertas.
3. **Três testes do `alert_checker` batiam no Supabase de PRODUÇÃO.** Esqueceram de
   simular `get_recent_sent_titles`; o resultado dependia dos dados do dia.
4. **Dois bugs de dado no relatório** (achados de tabela, não pedidos):
   `crypto.py` transformava variação ausente em `0,00%` — "não sei" publicado no
   WhatsApp como "não mudou" —, e os testes de cripto conferiam se a CHAVE existia,
   nunca se o VALOR era número, então preço nulo passava.

Consertos: variação ausente vira `None` e o prompt `_CAMBIO_CRIPTO` aprendeu a tratar
nulo (sem isso, o conserto trocaria "0%" mentiroso por lixo); conferência de cripto
olha o valor; `coleta_unica()` no `conftest.py` faz UMA chamada real por arquivo em vez
de uma por teste (a chamada real continua — some só a repetição, então a detecção de
contrato quebrado fica intacta); e uma trava faz o teste `unit` **falhar** se abrir
conexão, para o marcador nunca mais mentir calado.

⚠️ **`test_admin_sources.py` passava só em máquina com `.env`** — dependia de
`NEWS_API_KEY` existir no ambiente, não do código. Havia mais um caso assim, e pode
haver outros: teste que lê o ambiente em vez do código passa em casa e reprova no CI.

🔴 **PENDENTE — `test_preferences.py` GRAVA no Supabase de produção.** Ele cria um
usuário falso (`add_authorized("test_lid_0000000000", ...)`) com horário 08:00 e limpa
no `teardown_function`. Se a suíte for interrompida entre a gravação e a limpeza
(Ctrl+C, tempo esgotado, falha antes do teardown), o usuário falso **fica** na tabela
de autorizados, e a rotina horária passa a tentar mandar relatório para um número que
não existe, todo dia, calado. `test_health.py` também bate no banco real (só lê).
Ficou fora do recorte desta sessão — é o próximo candidato ao mesmo tratamento dado ao
`test_alert_checker.py`.

⚠️ **A trava de rede não é garantia total.** Ela pega conexão síncrona e assíncrona
(inclusive o caminho do Windows, que não passa pelo mesmo ponto do Linux). NÃO pega:
exceção engolida por `asyncio.gather(return_exceptions=True)`, rede aberta dentro de
thread (a conexão é barrada, mas o teste segue verde), conexão já aberta antes do teste,
e consulta de nome (DNS). Os quatro casos estão medidos e escritos no cabeçalho de
`backend/tests/_trava_rede.py`, com os pontos de `polls_br.py` que os exercem. Todos
latentes em 13/08 — zero ocorrência no portão do CI.

⚠️ **Armadilha do `conftest.py`: ele é carregado DUAS vezes** (como `conftest` e como
`backend.tests.conftest`, objetos distintos), porque existe `backend/tests/__init__.py`
sem `backend/__init__.py`. Enquanto o arquivo não guardar estado, é inofensivo. Guardou
— contador, cache, classe de exceção — e metade do sistema enxerga uma cópia, metade a
outra. Foi exatamente esse o defeito que fez a primeira versão da trava de rede não
funcionar: duas classes de erro diferentes. Por isso a trava mora em
`backend/tests/_trava_rede.py`, importada pelo caminho absoluto, e não no conftest.

⚠️ **Este worktree não tem `.env`, mas alcança a internet mesmo assim:** o
`load_dotenv()` sobe as pastas e acha o `.env` do repositório principal. Rodar teste
"isolado" aqui NÃO é o mesmo que rodar no CI.

Medir (não cravar número aqui):
```
python -m pytest backend/tests/ -q -p backend.tools.medir_rede_testes
```
Confere quantas conexões externas a suíte abre e QUEM abre. Rodar um arquivo sozinho é
o que revela a verdade daquele arquivo — na suíte inteira a conexão é atribuída a quem
chegou primeiro, não a quem depende dela.

Conferir o tamanho do portão do CI e se ele passa sem credencial nenhuma:
```
python -m pytest backend -m unit -q
```

## Estado em 13/08/2026 — volume de alertas freado

O boletim de saúde de 13/08 acusou o efeito colateral previsto do dia 11: **64 alertas
em 12/08**, contra média de ~5,4/dia antes das 20 fontes entrarem. O conteúdo estava
bom (WASDE, Conab, Ormuz, OPEP, CPI, Moratória da Soja — 3 discutíveis em 51 lidos);
o problema era vazão.

Causa que ninguém tinha percebido: **a trava global é conferida uma vez por RODADA,
não por mensagem**. O laço então despejava até 5 de uma vez — "30 min entre alertas"
nunca significou um alerta a cada meia hora. Em 7 dias, 20 rajadas com 3-4 grudadas.

Consertos (`9c62ae0`): uma mensagem por rodada, a de maior nota; corte de nota 3→5;
trava 0,5→1,0 h. E um bug anterior que apareceu junto — a vencedora era marcada como
enviada mesmo com entrega falhando, o que com a Evolution fora do ar queimaria a melhor
notícia de cada rodada sem ninguém ver.

**Passou a existir teto duro de 24 alertas/dia** — o `_check_news` envia uma vez e tem
um só chamador. Antes não havia teto nenhum.

Medir (não cravar número aqui):
```
python -m backend.tools.medir_volume_alertas --dias 3 --sem-classificar
```
Acima de 25/dia é impossível pelo desenho — se aparecer, há caminho de envio não
mapeado, reverter. Abaixo de 8/dia por dois dias, a trava está apertada: voltar a 0,75.

## Estado em 11/08/2026 — pipeline de notícias reconstruído

Dúvida de 04/08 resolvida: o merge de 22/07 **entrou** (`57cfa96`, na master).

A sessão começou com um alerta datando "Julho de 2024" em agosto de 2026. A causa
tinha quatro camadas, cada uma escondendo a seguinte — as três primeiras eram sintoma:

1. O prompt do classificador não recebia data nenhuma. `publicado_em` era coletado pelo
   `news.py` e descartado no `_build_classifier_input`. Sem âncora, o Haiku preenchia o
   ano de memória do treino. → `<hoje>` e `<publicado_em>` injetados, ambos em BRT.
2. `_is_fresh` estourava `TypeError` com data sem fuso e o `except` devolvia "fresca" —
   fonte que omite o fuso alimentava notícia velha para sempre. → assume UTC.
3. 5 das 6 fontes RSS estavam mortas (Corriere parado desde 05/2024). → 20 fontes de
   commodities/macro, incluindo buscas do Google Notícias para USDA, OPEP, Fed, Rússia,
   Ucrânia e China, que bloqueiam acesso direto.
4. **A causa-raiz:** ninguém ficava sabendo. O `news.py` não registra nada e o boletim
   diário só conferia se a `NEWS_API_KEY` existe, nunca se alguma fonte trazia algo.
   → `source_health()` mede pelo coletor real e o boletim reporta fonte morta pelo nome.

Também nesta sessão: rodízio de fontes na ordenação (a posição na lista decidia o que o
classificador via, já que o `alert_checker` varre só os 20 primeiros); `User-Agent` de
navegador (o Nasdaq pendurava até o timeout); teto de 6s por requisição RSS (20 fontes a
15s encostavam nos 300s da Vercel); e `source_health` fora do `collect_status`, porque
`GET /api/health` é público e sem senha.

Commits: `111aeef` e `bd55893`.

## ⚠️ A lista de fontes vive no CÓDIGO, não no painel

A tabela `agent_config` do Supabase sombreava o código em silêncio: `_feeds()` só cai no
default quando o banco está vazio, e o banco tinha as 6 fontes mortas. Editar o código
não mudava nada em produção — foi assim que a podridão durou meses.

As 6 chaves `news.*` foram **apagadas** em 11/08/2026. Agora o código manda.

**O botão "Salvar" da tela de Fontes grava as SEIS chaves de uma vez**
(`frontend/components/fontes-form.tsx`), inclusive as que ninguém tocou — um clique
volta a sombrear o código. Mudança de fonte deve ser feita **no código, por deploy**.

Conferir se alguma chave voltou a sombrear:
```
python -c "from backend.collectors import news; from backend.services import config; config.clear_cache(); print([k for k in ['rss_feeds','rss_feeds_ai','sources_finance','sources_tech','finance_query','ai_query'] if config.get('news.'+k,None) is not None] or 'nenhuma')"
```

Medir as fontes vivas (é o que o boletim diário faz):
```
python -c "from backend.collectors import news; print(news.source_health())"
```

## Aberto

- [x] ~~Rodar as migrations 007 e 008~~ — **FEITO em 18/08 e conferido na fonte viva**
      (tabelas e as 17 colunas juntas respondem 200). Merge feito e deploy READY (`755b991`).
- [x] ~~**Os 3 defeitos da primeira validação em produção (18/08 23h)**~~ — **FEITOS e
      provados em alerta real em 19/08** (`18e9cb0` + `a08e12a`). O defeito 2 (sigla) segue
      em observação: nenhum título com sigla traduzível saiu desde então.
- [x] ~~**PROVA DE CAMPO da Story 2**~~ — **5 de 5 feitas** em WhatsApp real (4 em 20/08, a
      do segundo número em 31/08). Detalhe na seção de 20/08.
- [x] ~~**Stories 3 e 4**~~ — **as duas em produção** (PR #20 e #21). O plano
      anti-alucinação está completo.
- [x] ~~**Prova de campo da Story 3**~~ — **FEITA em 01/09/2026**, pergunta sobre preço do
      boi gordo (força busca + leitura de matéria). O corretor **não apagou dado bom**: a
      resposta voltou com faixa do físico, variação do dia, spot da B3, três vencimentos
      futuros e quatro estados. Latência 16 s — sem regressão. Ressalva honesta: "o corretor
      rodou" é INFERIDO (números ricos + tempo compatível), não observado; o que está provado
      é a ausência do dano, que era o risco. Detalhe na seção de 31/08.
- [ ] 🔴 **Alarme fora do WhatsApp.** Em 04/09 o bot ficou mudo ~35 h e nenhum aviso chegou:
      o boletim de saúde e o `notify_admin` viajam pelo canal que caiu. Opção mais barata:
      UptimeRobot (grátis) batendo em `/api/health` e mandando e-mail se `status != ok`.
- [ ] 🟡 Tirar `restart: always` da v1.8.2 TAMBÉM no compose antigo (feito só via `docker
      update`; se alguém subir a stack v1 pelo compose, volta). Ou apagar o container de vez.
- [ ] 🟡 **O `<hoje>` NÃO chega ao relatório diário de verdade.** Ele existe em
      `reporter._build_system`, que serve o chat e o fallback do `send_report`. O cron sai por
      `cron_report.py` → `report_engine` → `report_prompts`, e ali não há data nenhuma
      (conferido: zero ocorrências de `hoje`/`datetime` no arquivo). Se o incidente dos anos
      misturados foi no relatório diário, o remédio foi para o outro paciente.
- [x] ~~`build_fact_corpus` com dado bom E `"erro"` juntos~~ — **decidido na Story 3**:
      `integrity._com_fato` descarta só a entrada que é SÓ erro; degradação parcial (aviso
      junto com dado) continua valendo, senão perdia o dado bom.
- [ ] 🟡 `CREATE UNIQUE INDEX ON news_log_messages (news_log_id, phone)` — o
      `_RetryTransport` repete POST e a 008 não tem trava. Zero duplicatas medidas em 20/08;
      o sinal `truncado` já não depende disso, mas o índice é barato e correto.
- [ ] 🟡 Achados do revisor deixados para depois (nenhum trava a entrega): prompt de
      commodities pode preencher número quando o scraping cai inteiro; `BRAPI_TOKEN` vai
      na URL e a máscara não cobre `token=` (hoje não vaza, `stocks.py` engole o erro);
      `score = result.get("score", 0)` devolve
      `None` se o classificador mandar `null`.
- [ ] **Conferir o volume em 16/08** com o comando acima (esperado ~18/dia). É a
      primeira medição depois do freio de `9c62ae0`.
- [ ] Testes que batem em API externa (`test_crypto.py`, `test_indicators_br.py`) falham
      de forma intermitente quando a suíte inteira roda — bloqueio por excesso de
      requisições. O sintoma esconde o problema real: `collectors/crypto.py` não tem
      repetição nem tratamento de 429, então em produção ele simplesmente falha quando
      o CoinGecko cortar. Não resolver pondo simulação no teste — esconderia a falha.
- [ ] Nome real do veículo nas buscas do Google — hoje chega `GN OPEP` ao usuário.
- [ ] Resumo das buscas do Google vem como HTML do agregador: o classificador julga sem
      resumo e ainda paga o token. Limpar ou descartar.
- [ ] `_parse_rss_date` devolve data sem fuso quando o feed manda `-0000` (G1). Sai certo
      na Vercel, que roda em UTC; erra em medição feita no PC.
- [ ] Consulta `country=br` do NewsAPI devolve zero sempre (`news.py`).
- [ ] `defusedxml` no lugar de `xml.etree.ElementTree` — dívida antiga, risco baixo aqui
      porque as fontes são pré-definidas.
