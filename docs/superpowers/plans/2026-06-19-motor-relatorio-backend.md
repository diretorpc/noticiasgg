# Motor de Relatório no Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trazer a geração do relatório diário (6 seções) do n8n para o backend, data-driven, fiel ao layout atual, sem enviar mensagens e sem tocar o motor de chat.

**Architecture:** Módulo novo `backend/services/report_engine.py` com adaptadores puros (collector→contexto), um renderizador por seção (chamada Claude) e um orquestrador que devolve `list[str]` (uma mensagem por seção), com saudação única na 1ª mensagem. Validador de integridade extraído para `backend/services/integrity.py` e reusado nas seções de texto. Endpoint admin `preview-report` para comparar com o n8n sem enviar. CI determinístico (gate) + eval de alucinação (não-bloqueante).

**Tech Stack:** Python 3.12, FastAPI, `anthropic` SDK (`claude-sonnet-4-6`; validador `claude-haiku-4-5-20251001`), pytest, GitHub Actions, deploy Vercel.

## Global Constraints

- IA: modelo `claude-sonnet-4-6`; validador `claude-haiku-4-5-20251001`. Cliente Anthropic sempre com `timeout` explícito e `max_retries=1` (cabe no `maxDuration` 300s da Vercel).
- Auth dos endpoints admin: `auth.verify_supabase_jwt` (JWKS). Sem secrets no backend.
- Prompts copiados **verbatim** de `docs/n8n/report-prompts.json`, exceto remoção do greeting.
- Sem mock de banco em testes. Monkeypatch do cliente Anthropic (API paga não-determinística) é permitido.
- Não alterar `backend/services/reporter.py` além da extração do validador (Task 1), nem `backend/api/main.py`.
- Ordem fixa das seções: `commodities, bolsas, cambio_cripto, noticias, analise, politica`.
- Seções de texto (passam pelo validador): `noticias, analise, politica`. Seções de dados (não passam): `commodities, bolsas, cambio_cripto`.
- Chaves de config (Supabase + fallback via `backend/services/config.py`): `report_prompt_commodities`, `report_prompt_bolsas`, `report_prompt_cambio_cripto`, `report_prompt_noticias`, `report_prompt_analise`, `report_prompt_politica`.

---

## File Structure

- `backend/services/integrity.py` — **Criar.** Validador de integridade factual (movido de `reporter.py`): `build_fact_corpus(data)`, `validate_and_fix(report, data, client)`, markers.
- `backend/services/reporter.py` — **Modificar.** Importar o validador de `integrity.py` (mantendo comportamento).
- `backend/services/report_prompts.py` — **Criar.** Constantes dos 6 prompts (greeting removido) + `get_prompt(section)` (lê via `config.py`).
- `backend/services/report_engine.py` — **Criar.** Adaptadores puros, `_collect`, `_render`, `_greeting_header`, `generate_sections`.
- `backend/api/admin.py` — **Modificar.** Endpoint `POST /api/admin/preview-report`.
- `backend/tests/test_integrity.py` — **Criar.**
- `backend/tests/test_report_prompts.py` — **Criar.**
- `backend/tests/test_report_adapters.py` — **Criar.**
- `backend/tests/test_report_engine.py` — **Criar.**
- `backend/tests/test_preview_report.py` — **Criar.**
- `backend/pytest.ini` — **Criar.** Registrar markers `unit` e `smoke`.
- `.github/workflows/ci.yml` — **Criar.** Gate determinístico (`-m unit`).
- `backend/evals/__init__.py`, `backend/evals/hallucination_eval.py`, `backend/evals/fixtures/sample_data.json` — **Criar.** Harness de eval.
- `.github/workflows/hallucination-eval.yml` — **Criar.** `workflow_dispatch` + schedule semanal.

---

### Task 1: Extrair validador de integridade para `integrity.py`

**Files:**
- Create: `backend/services/integrity.py`
- Modify: `backend/services/reporter.py:293-344` (remove as funções/constantes movidas; importa de `integrity`)
- Test: `backend/tests/test_integrity.py`

**Interfaces:**
- Produces: `integrity.build_fact_corpus(data: dict) -> str`; `integrity.validate_and_fix(report: str, data: dict, client: Anthropic) -> str`; `integrity.ANALYSIS_MARKERS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_integrity.py
import pytest
from backend.services import integrity


@pytest.mark.unit
def test_build_fact_corpus_includes_market_and_truncates():
    data = {"market": {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}},
            "news": [{"titulo": "Manchete X"}, {"titulo": "Manchete Y"}]}
    corpus = integrity.build_fact_corpus(data)
    assert "IBOVESPA" in corpus
    assert "Manchete X" in corpus
    assert len(corpus) <= 6000


@pytest.mark.unit
def test_validate_and_fix_returns_original_when_no_analysis_markers():
    class _Client:  # nunca deve ser chamado
        pass
    report = "🌎 BOLSAS\n🇧🇷 IBOVESPA: 168277.55 pts 🔴 -0.1%"
    out = integrity.validate_and_fix(report, {"market": {}}, _Client())
    assert out == report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_integrity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.integrity'`

- [ ] **Step 3: Create `integrity.py` moving the code from `reporter.py`**

```python
# backend/services/integrity.py
import json
from anthropic import Anthropic

ANALYSIS_MARKERS = ("📊", "ANÁLISE", "Visão Macro", "Visão Brasil", "Visão Agro")

_SYSTEM_VALIDATOR = """Você é um validador de integridade factual para relatórios financeiros enviados via WhatsApp.

Você receberá:
1. Um relatório gerado por IA
2. Os dados brutos que o geraram (JSON)

Sua única tarefa: retornar o relatório corrigido, removendo ou reescrevendo qualquer afirmação factual que NÃO possa ser verificada nos dados recebidos.

O que DEVE ser removido ou corrigido:
- Números, percentuais ou preços que não aparecem nos dados
- Empresas, países ou organizações não mencionados nos dados ou nas notícias
- Atribuições geográficas não verificáveis ("empresa X é do país Y" sem base nos dados)
- Relações causais inventadas ("X subiu porque Y" se Y não está nos dados como fato real)
- Qualquer afirmação especulativa apresentada como verdade factual

O que DEVE ser preservado:
- Seções de dados diretos (câmbio, bolsas, cripto, indicadores) — esses vêm dos coletores e já são verificados
- Notícias que aparecem na lista de notícias dos dados
- Formatação WhatsApp (*negrito*, _itálico_, emojis, quebras de linha)
- Estrutura geral do relatório e tom de analista

Retorne APENAS o relatório corrigido, sem prefácio, sem explicação, sem comentário."""


def build_fact_corpus(data: dict) -> str:
    """Serializa as partes mais relevantes dos dados coletados para o validador.
    Limita o tamanho para manter custo de tokens baixo."""
    parts = []
    for key in ("market", "crypto", "indicators_br", "indicators_us", "commodities_br"):
        val = data.get(key)
        if val and not (isinstance(val, dict) and "erro" in val):
            parts.append(f"{key}: {json.dumps(val, ensure_ascii=False, default=str)}")
    for key, label, limit in (
        ("news", "Notícias", 10),
        ("politics_br", "Política", 5),
        ("polls_br", "Pesquisas", 3),
    ):
        val = data.get(key)
        if isinstance(val, list) and val:
            titles = [a.get("titulo", a.get("instituto", "")) for a in val[:limit]]
            parts.append(f"{label}: {json.dumps(titles, ensure_ascii=False)}")
    return "\n".join(parts)[:6000]


def validate_and_fix(report: str, data: dict, client: Anthropic) -> str:
    """Passagem de validação pós-geração via Claude Haiku.
    Remove afirmações factuais não verificáveis nos dados coletados.
    Retorna o relatório corrigido; em caso de falha retorna o original."""
    if not data or not any(m in report for m in ANALYSIS_MARKERS):
        return report
    fact_corpus = build_fact_corpus(data)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=_SYSTEM_VALIDATOR,
            messages=[{
                "role": "user",
                "content": (
                    f"Relatório para validar:\n{report}\n\n"
                    f"Dados brutos disponíveis:\n{fact_corpus}"
                ),
            }],
        )
        for block in resp.content:
            if hasattr(block, "text") and len(block.text.strip()) > 100:
                return block.text.strip()
    except Exception:
        pass
    return report
```

- [ ] **Step 4: Update `reporter.py` to import from `integrity` (preserve behavior)**

Em `backend/services/reporter.py`: remova `_SYSTEM_VALIDATOR`, `_build_fact_corpus`, `_validate_and_fix`, `_ANALYSIS_MARKERS` (linhas ~270-344) e adicione, junto aos imports do topo:

```python
from backend.services.integrity import (
    validate_and_fix as _validate_and_fix,
    build_fact_corpus as _build_fact_corpus,
    ANALYSIS_MARKERS as _ANALYSIS_MARKERS,
)
```

Mantenha a chamada existente `return _validate_and_fix(block.text, data, client)` intacta.

- [ ] **Step 5: Run tests to verify they pass and no regression**

Run: `pytest backend/tests/test_integrity.py backend/tests/test_reporter.py -v`
Expected: PASS (novos testes verdes; reporter sem regressão)

- [ ] **Step 6: Commit**

```bash
git add backend/services/integrity.py backend/services/reporter.py backend/tests/test_integrity.py
git commit -m "refactor: extract factual-integrity validator to integrity module"
```

---

### Task 2: Prompts das seções em `report_prompts.py`

**Files:**
- Create: `backend/services/report_prompts.py`
- Test: `backend/tests/test_report_prompts.py`

**Interfaces:**
- Consumes: `backend.services.config.get_str(key, default)`.
- Produces: `report_prompts.get_prompt(section: str) -> str`; `report_prompts.SECTIONS: tuple[str, ...]` = `("commodities","bolsas","cambio_cripto","noticias","analise","politica")`; constante `report_prompts.DEFAULTS: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_report_prompts.py
import pytest
from backend.services import report_prompts


@pytest.mark.unit
def test_all_sections_have_default_prompt():
    for s in report_prompts.SECTIONS:
        assert report_prompts.DEFAULTS[s].strip()


@pytest.mark.unit
def test_prompts_have_no_greeting_instruction():
    # greeting foi removido na migração
    for s in report_prompts.SECTIONS:
        body = report_prompts.DEFAULTS[s]
        assert "SAUDACAO" not in body
        assert "[SAUDACAO]" not in body


@pytest.mark.unit
def test_get_prompt_prefers_config(monkeypatch):
    monkeypatch.setattr(report_prompts.config, "get_str",
                        lambda key, default: "PROMPT DO PAINEL" if key == "report_prompt_bolsas" else default)
    assert report_prompts.get_prompt("bolsas") == "PROMPT DO PAINEL"


@pytest.mark.unit
def test_get_prompt_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(report_prompts.config, "get_str", lambda key, default: default)
    assert report_prompts.get_prompt("commodities") == report_prompts.DEFAULTS["commodities"]


@pytest.mark.unit
def test_get_prompt_unknown_section_raises():
    with pytest.raises(KeyError):
        report_prompts.get_prompt("inexistente")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_report_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.report_prompts'`

- [ ] **Step 3: Create `report_prompts.py`**

```python
# backend/services/report_prompts.py
from backend.services import config

SECTIONS = ("commodities", "bolsas", "cambio_cripto", "noticias", "analise", "politica")

_CONFIG_KEY = {s: f"report_prompt_{s}" for s in SECTIONS}

_BOLSAS = """Você é um agente financeiro. Você receberá uma string JSON. Faça o parse dela e encontre o campo data.bolsas para obter os preços. Use 🟢 se variacao_pct positiva, 🔴 se negativa, 🟡 se zero ou null. Se variacao_pct for null, exiba 🟡 e omita o percentual. Responda APENAS com o texto formatado, sem explicações. Formato exato:

🌎 BOLSAS
🇧🇷 IBOVESPA: [preco] pts [emoji] [variacao_pct]%
🇺🇸 S&P 500: [preco] pts [emoji] [variacao_pct]%
🇺🇸 NASDAQ: [preco] pts [emoji] [variacao_pct]%
🇺🇸 NYSE: [preco] pts [emoji] [variacao_pct]%
🇨🇳 Shanghai: [preco] pts [emoji] [variacao_pct]%
🇪🇺 Euronext: [preco] pts [emoji] [variacao_pct]%
🇯🇵 Nikkei: [preco] pts [emoji] [variacao_pct]%"""

_COMMODITIES = """Você é um agente especialista em agronegócio e commodities brasileiras. Gere APENAS a listagem de commodities no formato exato abaixo, sem texto adicional, sem explicações, sem parágrafos. Use 🟢 se variação positiva, 🔴 se variação negativa, 🟡 se zero ou estável. Nunca mostre cálculos. Formato obrigatório:

🌱 *COMMODITIES*

🛢️ Petróleo Brent: US$ X,XX/barril 🔴 -X,XX%
🐮 Boi Gordo SP: R$ XXX,XX/@ 🟢 +X,XX%
☕ Café Arábica SP: R$ X.XXX,XX/sc 60kg 🔴 -X,XX%
🌱 Soja PR: R$ XXX,XX/sc 60kg 🟢 +X,XX%
🌽 Milho SP: R$ XX,XX/sc 60kg 🔴 -X,XX%
🌾 Trigo PR: R$ X.XXX,XX/ton 🟢 +X,XX%
🫙 Açúcar Cristal SP: R$ XX,XX/sc 50kg 🔴 -X,XX%
🍗 Frango Congelado SP: R$ X,XX/kg 🟡 estável
🐷 Suíno Vivo PR: R$ X,XX/kg 🔴 -X,XX%
🍚 Arroz Tipo 1 RS: R$ XX,XX/sc 50kg 🔴 -X,XX%"""

_CAMBIO_CRIPTO = """Você é um agente especialista em finanças globais, mercado brasileiro, agronegócio e jornalismo econômico. Gere APENAS câmbio e cripto no formato exato abaixo, sem texto adicional, sem títulos com ##, sem tabelas markdown, sem traços separadores. Use texto simples com emojis. Use 🟢 se variação positiva, 🔴 se variação negativa e 🟡 se variação zero ou estável. Nunca mostre cálculos. Gere APENAS a seção de CÂMBIO e CRIPTOMOEDAS. Formato obrigatório:

💵 *CÂMBIO*
Dólar USD/BRL: R$ X,XX 🟢 +X,XX%
Euro EUR/BRL: R$ X,XX 🔴 -X,XX%

₿ *CRIPTOMOEDAS*
USDT – Volume 24h: US$ XX bilhões
BTC: US$ XX.XXX 🔴 -X,XX%
ETH: US$ X.XXX,XX 🟢 +X,XX%

Texto corrido, sem tabelas."""

_NOTICIAS = """Ignore qualquer data do contexto. Você é um editor sênior de economia e geopolítica de um grande jornal internacional. Com os dados recebidos, gere APENAS a seção de NOTÍCIAS. Selecione as 5 de MAIOR IMPACTO REAL — priorize eventos que mudaram mercados, políticas econômicas, relações geopolíticas ou fluxo de capital. Ignore notícias virais sem consequência concreta. Formato: 📰 NOTÍCIAS na primeira linha, depois liste as 5 principais notícias financeiras numeradas, cada uma com título em negrito, descrição de uma linha e fonte entre parênteses. Máximo 800 caracteres."""

_ANALISE = """Ignore qualquer data do contexto. Você é um agente especialista em finanças globais, mercado brasileiro e agronegócio. Com os dados recebidos, gere APENAS a ANÁLISE DO CENÁRIO em 3 partes. Formato: 📊 ANÁLISE DO CENÁRIO

*Visão Macro Global*
[2-3 frases sobre cenário econômico mundial]

*Visão Brasil*
[2-3 frases sobre economia e mercado brasileiro]

*Visão Agro BR*
[2-3 frases de análise ampla do agronegócio brasileiro: use câmbio, demanda global (especialmente China), geopolítica, safra, exportações, insumos e pecuária — analise com seu conhecimento do setor mesmo sem dados de commodities disponíveis. Nunca mencione ausência de dados]

[frase leve de encerramento]. Máximo 1600 caracteres."""

_POLITICA = """Ignore qualquer data do contexto. Você é um analista político brasileiro. Com os dados recebidos, gere APENAS as seções de POLÍTICA e PESQUISAS ELEITORAIS. Formato exato: 🏛️ POLÍTICA
1. **[título]** — [descrição em uma linha] ([fonte])
2. **[título]** — [descrição em uma linha] ([fonte])
3. **[título]** — [descrição em uma linha] ([fonte])
4. **[título]** — [descrição em uma linha] ([fonte])
5. **[título]** — [descrição em uma linha] ([fonte])

🗳️ PESQUISAS ELEITORAIS
· *[Instituto]* ([data]) — [turno]
[Candidato]: [x]%
[Candidato]: [x]%
[Candidato]: [x]%

Liste TODOS os candidatos presentes nos dados de cada pesquisa, sem omitir nenhum. Máximo 1200 caracteres."""

DEFAULTS = {
    "commodities": _COMMODITIES,
    "bolsas": _BOLSAS,
    "cambio_cripto": _CAMBIO_CRIPTO,
    "noticias": _NOTICIAS,
    "analise": _ANALISE,
    "politica": _POLITICA,
}


def get_prompt(section: str) -> str:
    key = _CONFIG_KEY[section]  # KeyError em seção desconhecida (intencional)
    return config.get_str(key, DEFAULTS[section])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_report_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/report_prompts.py backend/tests/test_report_prompts.py
git commit -m "feat: add report section prompts module (config-backed, greeting removed)"
```

---

### Task 3: Adaptadores de dados (puros)

**Files:**
- Create: `backend/services/report_engine.py` (só os adaptadores nesta task)
- Test: `backend/tests/test_report_adapters.py`

**Interfaces:**
- Produces (todos retornam `dict` no formato `{"data": {...}}`):
  - `adapt_bolsas(market_out: dict) -> dict`
  - `adapt_commodities(comm_out: dict) -> dict`
  - `adapt_cambio_cripto(market_out: dict, crypto_out: list) -> dict`
  - `adapt_noticias(news_out: list) -> dict`
  - `adapt_analise(market_out: dict, crypto_out: list, ind_br: dict, ind_us: dict, news_out: list) -> dict`
  - `adapt_politica(politics_out: list, polls_out: list) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_report_adapters.py
import pytest
from backend.services import report_engine as re


@pytest.mark.unit
def test_adapt_bolsas_extracts_bolsas_slice():
    market = {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}},
              "cambio": {"USD/BRL": {"preco": 5.17, "variacao_pct": 0.18}}}
    out = re.adapt_bolsas(market)
    assert out == {"data": {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}}}


@pytest.mark.unit
def test_adapt_bolsas_handles_collector_error():
    out = re.adapt_bolsas({"erro": "boom"})
    assert out == {"data": {"bolsas": {}}}


@pytest.mark.unit
def test_adapt_cambio_cripto_merges_cambio_and_crypto():
    market = {"bolsas": {}, "cambio": {"USD/BRL": {"preco": 5.17, "variacao_pct": 0.18}}}
    crypto = [{"simbolo": "BTC", "preco_usd": 64000, "variacao_24h_pct": -1.2}]
    out = re.adapt_cambio_cripto(market, crypto)
    assert out["data"]["cambio"]["USD/BRL"]["preco"] == 5.17
    assert out["data"]["cripto"] == crypto


@pytest.mark.unit
def test_adapt_commodities_wraps_output():
    comm = {"Boi Gordo SP": {"preco": 353.4, "variacao_pct": -0.11}}
    assert re.adapt_commodities(comm) == {"data": {"commodities": comm}}


@pytest.mark.unit
def test_adapt_noticias_wraps_list():
    news = [{"titulo": "X", "fonte": "Y"}]
    assert re.adapt_noticias(news) == {"data": {"noticias": news}}


@pytest.mark.unit
def test_adapt_analise_includes_all_sources():
    out = re.adapt_analise({"bolsas": {"IBOVESPA": {}}, "cambio": {"USD/BRL": {}}},
                           [{"simbolo": "BTC"}], {"selic": 13.75}, {"cpi": 3.1},
                           [{"titulo": "X"}])
    d = out["data"]
    assert set(d) == {"bolsas", "cambio", "cripto", "indicadores_br", "indicadores_us", "noticias"}


@pytest.mark.unit
def test_adapt_politica_wraps_both_lists():
    out = re.adapt_politica([{"titulo": "P"}], [{"instituto": "Datafolha"}])
    assert out == {"data": {"politica": [{"titulo": "P"}], "pesquisas": [{"instituto": "Datafolha"}]}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_report_adapters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.report_engine'`

- [ ] **Step 3: Create `report_engine.py` with the adapters**

```python
# backend/services/report_engine.py
def _safe_dict(val) -> dict:
    return val if isinstance(val, dict) and "erro" not in val else {}


def _safe_list(val) -> list:
    return val if isinstance(val, list) else []


def adapt_bolsas(market_out: dict) -> dict:
    return {"data": {"bolsas": _safe_dict(market_out).get("bolsas", {})}}


def adapt_commodities(comm_out: dict) -> dict:
    return {"data": {"commodities": _safe_dict(comm_out)}}


def adapt_cambio_cripto(market_out: dict, crypto_out: list) -> dict:
    return {"data": {
        "cambio": _safe_dict(market_out).get("cambio", {}),
        "cripto": _safe_list(crypto_out),
    }}


def adapt_noticias(news_out: list) -> dict:
    return {"data": {"noticias": _safe_list(news_out)}}


def adapt_analise(market_out: dict, crypto_out: list, ind_br: dict,
                  ind_us: dict, news_out: list) -> dict:
    m = _safe_dict(market_out)
    return {"data": {
        "bolsas": m.get("bolsas", {}),
        "cambio": m.get("cambio", {}),
        "cripto": _safe_list(crypto_out),
        "indicadores_br": _safe_dict(ind_br),
        "indicadores_us": _safe_dict(ind_us),
        "noticias": _safe_list(news_out),
    }}


def adapt_politica(politics_out: list, polls_out: list) -> dict:
    return {"data": {
        "politica": _safe_list(politics_out),
        "pesquisas": _safe_list(polls_out),
    }}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_report_adapters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/report_engine.py backend/tests/test_report_adapters.py
git commit -m "feat: add pure data adapters for report engine sections"
```

---

### Task 4: Coleta + renderização de uma seção

**Files:**
- Modify: `backend/services/report_engine.py` (adicionar `_collect`, `_render`, `_MAX_TOKENS`, `TEXT_SECTIONS`, `_ANTHROPIC_TIMEOUT`, imports)
- Test: `backend/tests/test_report_engine.py`

**Interfaces:**
- Consumes: adapters (Task 3); `report_prompts.get_prompt` (Task 2); `integrity.validate_and_fix` (Task 1); collectors `market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br`.
- Produces: `report_engine._collect(section: str) -> dict`; `report_engine._render(section: str, ctx: dict, client) -> str`; constantes `report_engine.TEXT_SECTIONS = ("noticias","analise","politica")`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_report_engine.py
import pytest
from backend.services import report_engine as re


class _Block:
    def __init__(self, text): self.text = text; self.type = "text"


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class _FakeClient:
    """Captura kwargs e devolve um texto fixo por chamada."""
    def __init__(self, text="🌎 BOLSAS\n🇧🇷 IBOVESPA: 168277.55 pts 🔴 -0.1%"):
        self._text = text
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._text)


@pytest.mark.unit
def test_render_uses_section_prompt_and_returns_text():
    client = _FakeClient()
    ctx = re.adapt_bolsas({"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}})
    out = re.render = re._render("bolsas", ctx, client)
    assert "IBOVESPA" in out
    assert client.calls[0]["model"] == "claude-sonnet-4-6"
    # prompt da seção foi usado como system
    assert "🌎 BOLSAS" in client.calls[0]["system"]


@pytest.mark.unit
def test_render_text_section_runs_validator(monkeypatch):
    seen = {}
    def fake_validate(report, data, client):
        seen["called"] = True
        return report + " [validado]"
    monkeypatch.setattr(re.integrity, "validate_and_fix", fake_validate)
    client = _FakeClient(text="📊 ANÁLISE DO CENÁRIO\n*Visão Macro Global*\nteste")
    ctx = re.adapt_analise({"bolsas": {}, "cambio": {}}, [], {}, {}, [])
    out = re._render("analise", ctx, client)
    assert seen.get("called") is True
    assert out.endswith("[validado]")


@pytest.mark.unit
def test_render_data_section_skips_validator(monkeypatch):
    def fail_validate(*a, **k):
        raise AssertionError("validator não deve rodar em seção de dados")
    monkeypatch.setattr(re.integrity, "validate_and_fix", fail_validate)
    client = _FakeClient()
    ctx = re.adapt_bolsas({"bolsas": {}})
    re._render("bolsas", ctx, client)  # não deve levantar


@pytest.mark.unit
def test_collect_bolsas_uses_adapter(monkeypatch):
    monkeypatch.setattr(re.market, "collect",
                        lambda: {"bolsas": {"IBOVESPA": {"preco": 1, "variacao_pct": 2}}, "cambio": {}})
    ctx = re._collect("bolsas")
    assert ctx == {"data": {"bolsas": {"IBOVESPA": {"preco": 1, "variacao_pct": 2}}}}


@pytest.mark.unit
def test_collect_tolerates_collector_failure(monkeypatch):
    def boom(): raise RuntimeError("down")
    monkeypatch.setattr(re.commodities_br, "collect", boom)
    ctx = re._collect("commodities")
    assert ctx == {"data": {"commodities": {}}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_report_engine.py -v`
Expected: FAIL — `AttributeError: module 'backend.services.report_engine' has no attribute '_render'`

- [ ] **Step 3: Add collection + render to `report_engine.py`**

Adicione no topo de `backend/services/report_engine.py`:

```python
import json
import logging

from backend.collectors import (
    market, crypto, indicators_us, indicators_br, news,
    commodities_br, politics_br, polls_br,
)
from backend.services import report_prompts, integrity

logger = logging.getLogger("noticiasgg")

_ANTHROPIC_TIMEOUT = 90.0
TEXT_SECTIONS = ("noticias", "analise", "politica")

_MAX_TOKENS = {
    "commodities": 1024, "bolsas": 1024, "cambio_cripto": 1024,
    "noticias": 1024, "analise": 1500, "politica": 1200,
}


def _safe_collect(fn):
    try:
        return fn()
    except Exception as e:
        return {"erro": str(e)}


def _collect(section: str) -> dict:
    if section == "bolsas":
        return adapt_bolsas(_safe_collect(market.collect))
    if section == "commodities":
        return adapt_commodities(_safe_collect(commodities_br.collect))
    if section == "cambio_cripto":
        return adapt_cambio_cripto(_safe_collect(market.collect), _safe_collect(crypto.collect))
    if section == "noticias":
        return adapt_noticias(_safe_collect(news.collect))
    if section == "analise":
        return adapt_analise(
            _safe_collect(market.collect), _safe_collect(crypto.collect),
            _safe_collect(indicators_br.collect), _safe_collect(indicators_us.collect),
            _safe_collect(news.collect),
        )
    if section == "politica":
        return adapt_politica(_safe_collect(politics_br.collect), _safe_collect(polls_br.collect))
    raise KeyError(section)


def _render(section: str, ctx: dict, client) -> str:
    prompt = report_prompts.get_prompt(section)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS[section],
        system=prompt,
        messages=[{"role": "user",
                   "content": json.dumps(ctx, ensure_ascii=False, default=str)}],
    )
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text = block.text
            break
    if section in TEXT_SECTIONS:
        text = integrity.validate_and_fix(text, ctx.get("data", {}), client)
    return text
```

> Nota: `_safe_collect` aqui devolve `{"erro": ...}` em falha; os adaptadores (`_safe_dict`/`_safe_list`) já neutralizam esse dict para `{}`/`[]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_report_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/report_engine.py backend/tests/test_report_engine.py
git commit -m "feat: add per-section collection and Claude render to report engine"
```

---

### Task 5: Orquestrador `generate_sections` + saudação

**Files:**
- Modify: `backend/services/report_engine.py` (adicionar `_SECTION_ORDER`, `DEFAULT_SECTIONS`, `_current_greeting`, `_greeting_header`, `generate_sections`)
- Test: `backend/tests/test_report_engine.py` (adicionar casos)

**Interfaces:**
- Consumes: `_collect`, `_render` (Task 4).
- Produces: `report_engine.generate_sections(sections: dict | None, user: dict, client=None) -> list[str]`; `report_engine._SECTION_ORDER`; `report_engine.DEFAULT_SECTIONS`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em backend/tests/test_report_engine.py
import datetime as _dt


@pytest.mark.unit
def test_generate_sections_orders_and_prefixes_greeting(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})
    monkeypatch.setattr(re, "_render", lambda s, ctx, client: f"CORPO::{s}")
    # hora fixa para saudação determinística
    class _FixedDate(_dt.datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 6, 19, 7, 0, 0, tzinfo=tz)
    monkeypatch.setattr(re._dt, "datetime", _FixedDate)

    out = re.generate_sections({"bolsas": True, "analise": True}, {"name": "Gustavo Mouro"},
                               client=object())
    assert len(out) == 2
    # ordem fixa: bolsas vem antes de analise
    assert out[0].endswith("CORPO::bolsas")
    assert out[1] == "CORPO::analise"
    # saudação só na 1ª mensagem, com primeiro nome e data
    assert out[0].startswith("Bom dia, *Gustavo*! | 19/06/2026")
    assert "Bom dia" not in out[1]


@pytest.mark.unit
def test_generate_sections_omits_failed_section(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})
    def render(s, ctx, client):
        if s == "bolsas":
            raise RuntimeError("claude down")
        return f"CORPO::{s}"
    monkeypatch.setattr(re, "_render", render)
    out = re.generate_sections({"bolsas": True, "commodities": True}, {"name": "X"}, client=object())
    assert out == [f"{re._greeting_header({'name': 'X'})}\n\nCORPO::commodities"]


@pytest.mark.unit
def test_generate_sections_none_uses_all(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})
    monkeypatch.setattr(re, "_render", lambda s, ctx, client: f"CORPO::{s}")
    out = re.generate_sections(None, {"name": "X"}, client=object())
    assert len(out) == len(re._SECTION_ORDER)


@pytest.mark.unit
def test_greeting_header_without_name():
    h = re._greeting_header({"name": ""})
    assert "*" not in h  # sem nome em negrito
    assert "|" in h      # mantém a data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_report_engine.py -v`
Expected: FAIL — `AttributeError: module 'backend.services.report_engine' has no attribute 'generate_sections'`

- [ ] **Step 3: Add orchestrator + greeting to `report_engine.py`**

Adicione aos imports do topo: `import datetime as _dt` e `import os`. Depois adicione:

```python
_SECTION_ORDER = ("commodities", "bolsas", "cambio_cripto", "noticias", "analise", "politica")
DEFAULT_SECTIONS = {s: True for s in _SECTION_ORDER}

_BRT = _dt.timezone(_dt.timedelta(hours=-3))


def _current_greeting() -> str:
    h = _dt.datetime.now(_BRT).hour
    if 5 <= h < 12:
        return "Bom dia"
    if h < 18:
        return "Boa tarde"
    return "Boa noite"


def _greeting_header(user: dict) -> str:
    data = _dt.datetime.now(_BRT).strftime("%d/%m/%Y")
    nome = (user.get("name") or "").strip()
    saud = _current_greeting()
    if nome:
        return f"{saud}, *{nome.split()[0]}*! | {data}"
    return f"{saud}! | {data}"


def generate_sections(sections: dict | None, user: dict, client=None) -> list[str]:
    if client is None:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                           timeout=_ANTHROPIC_TIMEOUT, max_retries=1)
    active = sections if sections is not None else DEFAULT_SECTIONS
    messages: list[str] = []
    for section in _SECTION_ORDER:
        if not active.get(section):
            continue
        try:
            ctx = _collect(section)
            text = _render(section, ctx, client)
            if text and text.strip():
                messages.append(text.strip())
        except Exception:
            logger.exception("report_engine: seção falhou: %s", section)
    if messages:
        messages[0] = f"{_greeting_header(user)}\n\n{messages[0]}"
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_report_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/report_engine.py backend/tests/test_report_engine.py
git commit -m "feat: add report engine orchestrator with single greeting and failure isolation"
```

---

### Task 6: Endpoint `POST /api/admin/preview-report`

**Files:**
- Modify: `backend/api/admin.py`
- Test: `backend/tests/test_preview_report.py`

**Interfaces:**
- Consumes: `report_engine.generate_sections`; `supabase.get_authorized_by_phone`; `auth.verify_supabase_jwt`.
- Produces: rota `POST /api/admin/preview-report`, body `{"phone": str, "sections": dict | null}`, resposta `{"messages": [str, ...]}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_preview_report.py
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, report_engine, supabase

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch):
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_preview_report_returns_messages(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "Gustavo"})
    monkeypatch.setattr(report_engine, "generate_sections",
                        lambda sections, user, **k: ["MSG1", "MSG2"])
    r = client.post("/api/admin/preview-report",
                    json={"phone": "5534999999999", "sections": {"bolsas": True}})
    assert r.status_code == 200
    assert r.json() == {"messages": ["MSG1", "MSG2"]}


@pytest.mark.unit
def test_preview_report_unknown_user_uses_empty_name(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone", lambda phone: None)
    captured = {}
    def gen(sections, user, **k):
        captured["user"] = user
        return []
    monkeypatch.setattr(report_engine, "generate_sections", gen)
    r = client.post("/api/admin/preview-report", json={"phone": "999", "sections": None})
    assert r.status_code == 200
    assert captured["user"]["name"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_preview_report.py -v`
Expected: FAIL — 404 (rota inexistente)

- [ ] **Step 3: Add the endpoint to `admin.py`**

Garanta o import no topo: `from backend.services import report_engine` (junto aos imports existentes `reporter, auth, supabase`). Adicione:

```python
class PreviewReportBody(BaseModel):
    phone: str
    sections: dict | None = None


@router.post("/api/admin/preview-report")
def preview_report(body: PreviewReportBody, _claims: dict = Depends(auth.verify_supabase_jwt)):
    user = supabase.get_authorized_by_phone(body.phone) or {"phone": body.phone, "name": ""}
    messages = report_engine.generate_sections(body.sections, user)
    return {"messages": messages}
```

> Use o mesmo estilo de dependência de auth dos outros endpoints admin já existentes neste arquivo (`Depends(auth.verify_supabase_jwt)`); se o nome do parâmetro/claims diferir, siga o padrão do arquivo.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_preview_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/admin.py backend/tests/test_preview_report.py
git commit -m "feat: add admin preview-report endpoint (no WhatsApp send)"
```

---

### Task 7: CI gate determinístico (GitHub Actions)

**Files:**
- Create: `backend/pytest.ini`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: marker `unit` aplicado a todos os testes determinísticos das Tasks 1-6.
- Produces: workflow que roda `pytest -m unit` em PR e push para `master`.

- [ ] **Step 1: Create the pytest marker config**

```ini
# backend/pytest.ini
[pytest]
markers =
    unit: testes determinísticos sem rede (rodam no CI gate)
    smoke: chamadas reais ao Claude para conferência visual (não rodam no CI)
```

- [ ] **Step 2: Verify the unit tests are collected by the marker**

Run: `pytest backend -m unit -v`
Expected: PASS — coleta apenas os testes marcados `@pytest.mark.unit` das Tasks 1-6, todos verdes, sem necessidade de secrets/rede.

- [ ] **Step 3: Create the CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
  push:
    branches: [master]

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: pip install -r backend/requirements.txt
      - name: Run deterministic test gate
        run: pytest -c backend/pytest.ini backend -m unit -v
```

- [ ] **Step 4: Validate the workflow locally (sanity)**

Run: `pytest -c backend/pytest.ini backend -m unit -v`
Expected: PASS (mesma invocação do CI)

- [ ] **Step 5: Commit**

```bash
git add backend/pytest.ini .github/workflows/ci.yml
git commit -m "ci: add deterministic pytest gate for report engine (-m unit)"
```

---

### Task 8: Eval de alucinação (não-bloqueante)

**Files:**
- Create: `backend/evals/__init__.py`
- Create: `backend/evals/fixtures/sample_data.json`
- Create: `backend/evals/hallucination_eval.py`
- Create: `.github/workflows/hallucination-eval.yml`
- Test: `backend/tests/test_report_engine.py` (1 caso unit para o parser de score)

**Interfaces:**
- Consumes: `report_engine` (render das seções de texto); cliente Anthropic real (apenas em runtime do eval, não em teste).
- Produces: `hallucination_eval.parse_judge_verdict(text: str) -> dict`; `hallucination_eval.run() -> dict`.

- [ ] **Step 1: Write the failing test (parser puro)**

```python
# adicionar em backend/tests/test_report_engine.py
from backend.evals import hallucination_eval as he


@pytest.mark.unit
def test_parse_judge_verdict_extracts_counts():
    judge = "ancoradas: 7\ninventadas: 1\nveredito: ok"
    out = he.parse_judge_verdict(judge)
    assert out["ancoradas"] == 7
    assert out["inventadas"] == 1


@pytest.mark.unit
def test_parse_judge_verdict_defaults_zero_when_absent():
    out = he.parse_judge_verdict("texto sem números")
    assert out == {"ancoradas": 0, "inventadas": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_report_engine.py -v -k parse_judge`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.evals'`

- [ ] **Step 3: Create fixtures and the eval module**

```json
// backend/evals/fixtures/sample_data.json
{
  "bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1},
             "S&P 500": {"preco": 746.74, "variacao_pct": 1.04}},
  "cambio": {"USD/BRL": {"preco": 5.17, "variacao_pct": 0.18}},
  "cripto": [{"simbolo": "BTC", "preco_usd": 64000, "variacao_24h_pct": -1.2}],
  "indicadores_br": {"selic": 13.75}, "indicadores_us": {"cpi": 3.1},
  "noticias": [{"titulo": "Ucrânia ataca refinaria em Moscou", "fonte": "AP"}],
  "politica": [{"titulo": "Lula no G7", "fonte": "BBC"}],
  "pesquisas": [{"instituto": "Datafolha", "Lula": 38, "Flávio Bolsonaro": 35}]
}
```

```python
# backend/evals/__init__.py
```

```python
# backend/evals/hallucination_eval.py
"""Eval de alucinação (LLM-as-judge). Roda sob demanda / agendado, NÃO bloqueia merge.

Para cada seção de texto: gera o texto a partir de dados congelados e pede a um
juiz Claude para contar afirmações ancoradas vs inventadas. Emite score por seção.
"""
import json
import os
import re as _re
from pathlib import Path

from anthropic import Anthropic

from backend.services import report_engine

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_data.json"

_JUDGE_SYSTEM = """Você é um juiz de integridade factual. Recebe um texto de relatório e os DADOS que o originaram (JSON). Conte quantas afirmações factuais do texto estão ANCORADAS nos dados e quantas são INVENTADAS (não verificáveis nos dados). Responda EXATAMENTE em 3 linhas:
ancoradas: <número>
inventadas: <número>
veredito: <ok|suspeito>"""

_CTX_BUILDERS = {
    "noticias": lambda d: report_engine.adapt_noticias(d.get("noticias", [])),
    "analise": lambda d: report_engine.adapt_analise(
        {"bolsas": d.get("bolsas", {}), "cambio": d.get("cambio", {})},
        d.get("cripto", []), d.get("indicadores_br", {}), d.get("indicadores_us", {}),
        d.get("noticias", [])),
    "politica": lambda d: report_engine.adapt_politica(d.get("politica", []), d.get("pesquisas", [])),
}


def parse_judge_verdict(text: str) -> dict:
    def _num(label):
        m = _re.search(rf"{label}:\s*(\d+)", text, _re.IGNORECASE)
        return int(m.group(1)) if m else 0
    return {"ancoradas": _num("ancoradas"), "inventadas": _num("inventadas")}


def run() -> dict:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=90.0, max_retries=1)
    scores = {}
    for section, build_ctx in _CTX_BUILDERS.items():
        ctx = build_ctx(data)
        text = report_engine._render(section, ctx, client)
        judge = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=200, system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content":
                       f"DADOS:\n{json.dumps(ctx['data'], ensure_ascii=False)}\n\nTEXTO:\n{text}"}],
        )
        verdict_text = next((b.text for b in judge.content if hasattr(b, "text")), "")
        scores[section] = parse_judge_verdict(verdict_text)
    print(json.dumps(scores, ensure_ascii=False, indent=2))
    return scores


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_report_engine.py -v -k parse_judge`
Expected: PASS

- [ ] **Step 5: Create the eval workflow (non-blocking)**

```yaml
# .github/workflows/hallucination-eval.yml
name: Hallucination Eval
on:
  workflow_dispatch:
  schedule:
    - cron: "0 9 * * 1"  # segundas, 09:00 UTC

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r backend/requirements.txt
      - name: Run hallucination eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python -m backend.evals.hallucination_eval | tee eval-report.txt
      - name: Publish summary
        if: always()
        run: |
          echo '## Hallucination eval' >> "$GITHUB_STEP_SUMMARY"
          echo '```json' >> "$GITHUB_STEP_SUMMARY"
          cat eval-report.txt >> "$GITHUB_STEP_SUMMARY"
          echo '```' >> "$GITHUB_STEP_SUMMARY"
```

> O secret `ANTHROPIC_API_KEY` precisa ser cadastrado em Settings → Secrets do repositório. Este workflow **não** roda em PR/push e **não** bloqueia merge.

- [ ] **Step 6: Commit**

```bash
git add backend/evals .github/workflows/hallucination-eval.yml backend/tests/test_report_engine.py
git commit -m "feat: add non-blocking hallucination eval harness and weekly workflow"
```

---

## Self-Review

**1. Spec coverage:**
- 6 seções com prompts verbatim (greeting removido) → Tasks 2, 3, 4. ✓
- Cada seção = 1 mensagem; `list[str]` → Task 5. ✓
- Saudação única na 1ª mensagem (`Bom dia, *Nome*! | DD/MM/YYYY`) → Task 5. ✓
- Não envia; preview endpoint → Task 6. ✓
- Não toca `reporter.generate_report` (só extrai validador) nem `main.py` → Task 1 limita o escopo. ✓
- Tolerância a falha por seção → Tasks 4 (`_safe_collect`) e 5 (omissão). ✓
- Validador nas seções de texto → Tasks 1 + 4. ✓
- Prompts via `config.py` (Supabase + fallback) → Task 2. ✓
- Adaptadores puros testados com fixtures → Task 3. ✓
- Montagem com monkeypatch do Anthropic → Tasks 4, 5. ✓
- Smoke marker → Task 7 (`pytest.ini`). ✓
- CI camada 1 (gate) → Task 7. ✓
- CI camada 2a (validador runtime) → Tasks 1+4. ✓
- CI camada 2b (eval não-bloqueante, sob demanda + semanal) → Task 8. ✓

**2. Placeholder scan:** Nenhum "TBD/TODO/fill in". Todo passo tem código real.

**3. Type consistency:** `generate_sections(sections, user, client=None) -> list[str]`, `_render(section, ctx, client) -> str`, `_collect(section) -> dict`, adapters `-> {"data": {...}}`, `get_prompt(section) -> str`, `validate_and_fix(report, data, client) -> str` — consistentes entre tasks. Seções engine (`commodities, bolsas, cambio_cripto, noticias, analise, politica`) usadas uniformemente; distintas das chaves do `reporter` (intencional, isolado no item 1).
