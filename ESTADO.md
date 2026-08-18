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

- [ ] 🔴 **Rodar a migration `007_news_log.sql` no SQL Editor do Supabase.** Sem ela a
      Story 1 está no código e morta no banco, em silêncio. Comando de conferência na
      seção de 18/08.
- [ ] 🔴 **Stories 2, 3 e 4 do plano anti-alucinação** —
      `docs/superpowers/plans/2026-08-18-noticias-ancoradas-e-antialucinacao.md`.
      Enquanto não forem feitas, o agente segue inventando número e data quando
      perguntam sobre notícia do RSS: a Story 1 guarda o registro, mas **ninguém o lê
      ainda** (a ferramenta `get_sent_news` é da Story 2).
- [ ] 🟡 Achados do revisor deixados para depois (nenhum trava a entrega): prompt de
      commodities pode preencher número quando o scraping cai inteiro; `BRAPI_TOKEN` vai
      na URL e a máscara não cobre `token=` (hoje não vaza, `stocks.py` engole o erro);
      `build_fact_corpus` descarta a entrada inteira se ela tiver dado bom E `"erro"`
      juntos — decidir a regra na Story 3; `score = result.get("score", 0)` devolve
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
