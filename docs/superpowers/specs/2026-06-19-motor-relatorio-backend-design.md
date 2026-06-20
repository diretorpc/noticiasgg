# Motor de Relatório no Backend — Design

**Data:** 2026-06-19
**Escopo:** Item 1 da migração do motor de relatório do n8n → backend. Apenas o **motor de geração** das seções. Agendamento, edição no painel e cutover do n8n são specs separadas (itens 2, 3, 4).

## Contexto

Hoje o relatório diário é gerado por um workflow n8n de 72 nós ("Noticias finanças", id `Z8CLrlBvZoi3SQ8u`): 6 chamadas Claude separadas, uma por seção, cada uma com seu prompt e formato fixo. O backend tem um motor diferente (`reporter.generate_report`, chamada única com tools) usado só no chat/webhook e como fallback. Os prompts do n8n já estão extraídos (verbatim, scrubbed) em `docs/n8n/report-prompts.json`.

Este projeto traz o **motor de geração** para o backend, replicando fielmente o layout que os usuários recebem hoje, de forma data-driven e pronta para edição futura pelo painel — **sem** alterar agendamento nem enviar mensagens automaticamente, e **sem** tocar o motor de chat existente.

## Decomposição (contexto)

A migração completa tem 4 subsistemas independentes. Esta spec cobre **só o item 1**:

1. **Motor de relatório no backend** ← esta spec
2. Agendamento data-driven + cron Vercel confiável
3. Edição de schedules/prompts no painel
4. Cutover: rodar paralelo ao n8n → comparar → desligar o n8n

## Requisitos

- **Fidelidade:** mesmo layout/estrutura do n8n (mesmas seções, ordem, emojis, cabeçalhos, tom). Números variam (dados coletados em momentos diferentes) e textos de IA variam (não-determinístico). Critério de aceite: um humano olha os dois relatórios e diz "é o mesmo relatório".
- **6 seções**, cada uma com prompt verbatim do n8n, sua própria chamada Claude e **sua própria mensagem** (igual n8n envia mensagens separadas): Commodities, Bolsas, Câmbio/Cripto, Notícias, Análise, Política+Pesquisas.
- **Saudação única:** remover o greeting repetido que hoje aparece em toda seção. A 1ª mensagem do lote leva `Bom dia, *<PrimeiroNome>*! | DD/MM/YYYY` (saudação calculada pela hora BRT). As demais seções vêm direto no título.
- **Não enviar** nada automaticamente. Verificação via endpoint de preview que retorna o texto sem mandar pro WhatsApp.
- **Não tocar** `reporter.generate_report` nem `backend/api/main.py`. Os dois motores coexistem até o cutover.
- **Tolerância a falha:** falha de uma seção não derruba o relatório inteiro.

## Constraints globais

- Python 3.12, FastAPI, deploy Vercel (`vercel.json` legado, `maxDuration` 300s).
- IA: Claude `claude-sonnet-4-6` via SDK `anthropic`, com `timeout` explícito (cabe nos 300s).
- Validador de integridade: `claude-haiku-4-5-20251001`.
- Auth dos endpoints admin: JWKS (mesma dependência `auth.verify_supabase_jwt` dos outros admin endpoints). Sem secrets no backend.
- Sem mock de banco em testes (regra CLAUDE.md). Monkeypatch de API paga não-determinística (Claude) é permitido.
- Prompts copiados **verbatim** de `docs/n8n/report-prompts.json`, exceto a remoção do greeting.

## Arquitetura

### Módulo `backend/services/report_engine.py`

Uma função por seção (unidades isoladas e testáveis) + um orquestrador:

```
build_commodities(data, user)    -> str    # 🌱 COMMODITIES
build_bolsas(data, user)         -> str    # 🌎 BOLSAS
build_cambio_cripto(data, user)  -> str    # 💵 CÂMBIO / ₿ CRIPTOMOEDAS
build_noticias(data, user)       -> str    # 📰 NOTÍCIAS
build_analise(data, user)        -> str    # 📊 ANÁLISE DO CENÁRIO
build_politica(data, user)       -> str    # 🏛️ POLÍTICA / 🗳️ PESQUISAS
generate_sections(sections, user) -> list[str]   # orquestrador
```

- `sections`: dict `{nome_secao: bool}` indicando seções ativas (mesmo formato de `user_preferences.sections`).
- `user`: dict com pelo menos `name` (e `phone` para contexto).
- Retorno do orquestrador: **lista de strings**, uma por seção, na ordem fixa acima. Quem envia (cron/teste, fora desta spec) manda uma por uma.

### Prompts

Constantes no código (`backend/services/report_prompts.py` ou dict em `report_engine.py`), copiadas verbatim do `report-prompts.json`, **lidas via `config.py`** (padrão Supabase + fallback hardcoded já existente). Chaves de config: `report_prompt_bolsas`, `report_prompt_commodities`, `report_prompt_cambio_cripto`, `report_prompt_noticias`, `report_prompt_analise`, `report_prompt_politica`. Assim o item 3 (editar no painel) só grava no Supabase — o motor já lê de lá. Os prompts perdem a instrução de greeting (campo SAUDACAO) nesta migração.

### Saudação

Helper único reaproveitando a lógica de `send_report.py` (`_current_greeting` + primeiro nome). O orquestrador prefixa, **só na 1ª mensagem do lote**, a linha `<Saudação>, *<PrimeiroNome>*! | DD/MM/YYYY`. As funções de seção não emitem saudação.

## Fluxo de dados

Cada seção puxa só os coletores que precisa, via `_safe_collect` (tolerante a falha, já existente):

| Seção | Coletores |
|-------|-----------|
| 🌎 Bolsas | `market` |
| 🌱 Commodities | `commodities_br` |
| 💵 Câmbio/Cripto | `market` (câmbio) + `crypto` |
| 📰 Notícias | `news` |
| 📊 Análise | `market` + `crypto` + `indicators_br` + `indicators_us` + `news` |
| 🏛️ Política | `politics_br` + `polls_br` |

**Adaptadores de dados:** os prompts do n8n esperam campos específicos no JSON (ex: o de bolsas lê `data.bolsas` com `variacao_pct`). A saída dos collectors do backend precisa ser mapeada para o formato que cada prompt espera. Cada seção tem um adaptador fino (função pura) `collector_output -> prompt_context`. O plano de implementação deve verificar a forma real de saída de cada collector e escrever o adaptador correspondente — este é o principal ponto de risco/trabalho.

### Orquestrador `generate_sections`

1. Recebe `sections` ativas + `user`.
2. Para cada seção ativa (na ordem fixa): coleta os dados → adapta → chama Claude com o prompt da seção (sem greeting) → recebe o texto.
3. Seções de texto (notícias, análise, política) passam pelo validador de integridade (ver abaixo).
4. Prefixa a saudação na 1ª mensagem do resultado.
5. Devolve `list[str]`.

## Integridade factual (runtime)

As seções de **texto gerado por IA** (notícias, análise, política) passam pela função de validação já existente (`reporter._validate_and_fix`, Haiku — compara o texto contra os dados coletados e remove afirmações sem fonte). As seções de dados (bolsas, commodities, câmbio/cripto) são números formatados e não passam pelo validador. Se for preciso extrair `_validate_and_fix`/`_build_fact_corpus` de `reporter.py` para reuso, fazer um move mínimo para um módulo compartilhado sem alterar comportamento.

## Verificação (preview)

Endpoint **`POST /api/admin/preview-report`** em `backend/api/admin.py`, atrás de `auth.verify_supabase_jwt`:

- Body: `{ "phone": str, "sections": {<secao>: bool} | null }`. Se `sections` for null, usa todas.
- Resolve o usuário por telefone (`supabase.get_authorized_by_phone`, fallback nome vazio).
- Chama `report_engine.generate_sections`.
- Resposta: `{ "messages": [str, ...] }`. **Não envia pro WhatsApp.**

Fluxo de aceite: dispara o preview → compara com o relatório que o n8n mandou no mesmo dia → confere layout/estrutura.

## Erros

- Falha de **coletor** → tratada por `_safe_collect`; o prompt recebe `{"erro": ...}` e segue (os prompts lidam com dado ausente sem inventar).
- Falha da **chamada Claude** de uma seção → a seção é **omitida** do resultado e logada (`logger.exception`); as demais seguem. Relatório parcial > relatório nenhum.
- Cliente Anthropic com `timeout` explícito (mesmo padrão de `reporter.py`), cabendo no `maxDuration` 300s.

## Testes (pytest)

- **Adaptadores de dados** (collector → contexto do prompt): funções puras, testadas direto com fixtures de saída real dos collectors. Coração do risco.
- **Montagem** (orquestrador): saudação só na 1ª mensagem; ordem das seções; seleção por `sections`; omissão de seção cuja chamada Claude falha. Cliente Anthropic via **monkeypatch** (sem gastar token, sem depender de saída de IA).
- **Smoke test** marcado (`@pytest.mark.smoke`, fora do CI default): 1 chamada real por seção para conferência visual de layout sob demanda.

## CI e checagem de alucinação

### Camada 1 — Gate determinístico (bloqueia merge)

GitHub Actions (`.github/workflows/ci.yml`) rodando `pytest backend/tests/` (excluindo `smoke`) em cada PR e push para `master`. Pega erro de código, regressão, import quebrado. Bloqueia merge.

### Camada 2a — Rede de proteção em runtime

O validador Haiku (`_validate_and_fix`) aplicado às seções de texto, descrito em "Integridade factual" acima. Roda em produção, em todo relatório.

### Camada 2b — Eval de alucinação (NÃO bloqueia merge)

Harness `backend/evals/hallucination_eval.py` (LLM-as-judge):

- Pega **fixtures de dados congelados** (JSON salvo de uma coleta real, versionado) → gera as seções de texto → um juiz Claude marca cada afirmação como "ancorada nos dados" ou "inventada" → emite um **score por seção**.
- Workflow GitHub Actions separado (`.github/workflows/hallucination-eval.yml`) com `workflow_dispatch` (sob demanda) **e** `schedule` semanal. Gera relatório de score como artifact/summary. **Não bloqueia merge** (é pago e não-determinístico).

## Fora de escopo (itens futuros)

- Agendamento / cron / disparo automático (item 2).
- Botão de preview e edição de prompts no painel (item 3).
- Desligar o n8n (item 4).
- Alterar `reporter.generate_report` ou o webhook `main.py`.
