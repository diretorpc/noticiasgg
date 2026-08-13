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
