# Notícias Ancoradas e Anti-Alucinação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o agente lembrar das notícias que ele mesmo enviou e parar de inventar número e data quando o usuário pergunta sobre elas.

**Architecture:** Três camadas independentes. (1) O alerta de notícia passa a gravar um registro rico (`news_log`) além do hash de dedup que já existe. (2) O agente de chat ganha uma ferramenta que lê esse registro, então "essa notícia" vira um fato recuperável em vez de um título solto colado pelo usuário. (3) O validador anti-alucinação — hoje desligado em conversa — passa a rodar no caminho de chat e a receber o corpus das ferramentas (busca web/artigo), que é de onde os números realmente vêm. A Story 4 prende tudo com testes determinísticos e evals.

**Tech Stack:** Python 3.12, FastAPI, httpx, PostgREST (Supabase), Anthropic SDK (`claude-sonnet-4-6` no chat, `claude-haiku-4-5-20251001` no validador e no classificador), pytest.

## Global Constraints

- Python: `snake_case` para funções/variáveis, `PascalCase` para classes.
- Commits em inglês, imperativos.
- Comentário só quando o "porquê" não é óbvio.
- Sem mock de banco: os testes determinísticos mockam `supabase._client` / `httpx`, nunca introduzem um banco falso paralelo.
- Todo teste novo que deve rodar no portão do CI leva `@pytest.mark.unit` (o CI roda `pytest backend -m unit -v`).
- Nenhum teste pode tocar a rede: `backend/tests/_trava_rede.py` já está ativo — se um teste novo estourar a trava, o mock está incompleto.
- Migrations vão em `backend/migrations/NNN_nome.sql`, executadas à mão no SQL Editor do Supabase (não há runner automático).
- Nada de API key em código: tudo por `os.environ`.

## Contexto — a causa medida (não teorizada)

Três defeitos independentes, todos confirmados no código em 18/08/2026:

1. `backend/services/integrity.py:54` — `validate_and_fix` retorna cedo se a resposta não contiver um `ANALYSIS_MARKERS` (`📊`, `ANÁLISE`, `Visão Macro`…). Resposta de conversa nunca tem esses marcadores, então **o validador nunca roda em chat**.
2. `backend/services/integrity.py:56` — `build_fact_corpus(data)` monta o corpus só a partir dos coletores (`market`, `crypto`, `indicators_*`, `commodities_br`, `news`…). O que voltou de `search_web` / `read_article` **não entra no corpus**. Mesmo se o validador rodasse, ele não teria como conferir um número do USDA.
3. `backend/services/alert_checker.py:479` — o alerta de notícia sai via `_broadcast` e o único registro que fica é o hash em `sent_news` (`_mark_sent`, linha 486). **Nunca há `supabase.save_message`**, nem título, link ou data guardados de forma legível. Quando o usuário responde "me fale mais sobre essa notícia", o agente não tem nenhum vestígio dela.

## File Structure

| Arquivo | Responsabilidade | Story |
|---|---|---|
| `backend/migrations/007_news_log.sql` | Criar (novo) — tabela `news_log`, registro rico da notícia entregue | 1 |
| `backend/services/supabase.py` | Modificar — `log_sent_news`, `get_news_log` | 1 |
| `backend/services/alert_checker.py` | Modificar — carregar `url`/`publicado_em` na candidata, gravar no log, pôr o link na mensagem | 1 |
| `backend/tests/test_news_log.py` | Criar (novo) — testes determinísticos do registro | 1 |
| `backend/services/reporter.py` | Modificar — ferramenta `get_sent_news` + regra de prompt + coleta de `tool_corpus` + data de hoje | 2 e 3 |
| `backend/tests/test_reporter_news_tool.py` | Criar (novo) — a ferramenta é oferecida e despachada | 2 |
| `backend/services/integrity.py` | Modificar — corpus de ferramentas, portão novo, prompt de chat | 3 |
| `backend/tests/test_integrity_chat.py` | Criar (novo) — validador roda em chat e usa o corpus de ferramentas | 3 |
| `backend/evals/fixtures/grounding_cases.json` | Modificar — caso real do USDA de 18/08/2026 | 4 |
| `backend/evals/news_recall_eval.py` | Criar (novo) — eval do caminho "pergunta sobre notícia enviada" | 4 |
| `.github/workflows/hallucination-eval.yml` | Modificar — rodar os três evals | 4 |
| `ESTADO.md` | Modificar — registrar a mudança | 4 |

**Ordem obrigatória:** 1 → 2 → 3 → 4. A Story 2 lê a tabela que a 1 cria. A Story 4 testa o comportamento das 1–3.

---

## Story 1 — O alerta grava a notícia que enviou

**Por quê:** sem isto, nada mais funciona. É a peça central.

**Files:**
- Create: `backend/migrations/007_news_log.sql`
- Modify: `backend/services/supabase.py` (acrescentar após `get_recent_sent_titles`, ~linha 334)
- Modify: `backend/services/alert_checker.py:327-351` (`_format_news_alert`), `:452-453` (montagem da candidata), `:475-490` (bloco de envio)
- Test: `backend/tests/test_news_log.py`

**Interfaces:**
- Consumes: `supabase._client()`, `supabase._f()` (já existem)
- Produces:
  - `supabase.log_sent_news(entry: dict) -> None` — grava uma linha em `news_log`. Chaves aceitas: `news_id` (str, obrigatória), `titulo_pt`, `titulo_original`, `fonte`, `url`, `categoria`, `resumo`, `direcao`, `score` (int), `ativos` (list[str]), `publicado_em` (str ISO ou None). Nunca levanta exceção para o chamador.
  - `supabase.get_news_log(hours: int = 72, limit: int = 20) -> list[dict]` — as notícias entregues na janela, mais recentes primeiro. Cada dict tem as chaves acima mais `sent_at` (str ISO).

### Task 1.1: Tabela `news_log`

- [ ] **Step 1: Criar a migration**

Criar `backend/migrations/007_news_log.sql`:

```sql
-- Migration 007: news_log
-- Registro LEGÍVEL da notícia entregue como alerta. Separado de `sent_news`
-- de propósito: `sent_news` é um índice de dedup (duas linhas por notícia —
-- hash do título e hash da URL) com limpeza de 7 dias. Aqui a notícia é a
-- linha, e ela precisa sobreviver mais tempo para o agente conseguir
-- responder "me fale mais sobre aquela notícia".
-- Executar no Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS news_log (
    id              BIGSERIAL   PRIMARY KEY,
    news_id         TEXT        NOT NULL,
    titulo_pt       TEXT,
    titulo_original TEXT,
    fonte           TEXT,
    url             TEXT,
    categoria       TEXT,
    resumo          TEXT,
    direcao         TEXT,
    score           INT,
    ativos          JSONB,
    publicado_em    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS news_log_sent_at_idx ON news_log (sent_at DESC);

ALTER TABLE news_log ENABLE ROW LEVEL SECURITY;

-- Limpeza sugerida (rodar à mão ou via pg_cron):
-- DELETE FROM news_log WHERE sent_at < now() - interval '90 days';
```

- [ ] **Step 2: Rodar a migration no Supabase**

Abrir o SQL Editor do projeto Supabase, colar o conteúdo do arquivo, executar. Conferir que a tabela existe:

```bash
python -c "from backend.services import supabase; c=supabase._client(); r=c.get('/news_log?select=id&limit=1'); print(r.status_code, r.text[:200])"
```

Esperado: `200 []`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/007_news_log.sql
git commit -m "feat: add news_log table for delivered news alerts"
```

### Task 1.2: `log_sent_news` e `get_news_log`

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_news_log.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services import supabase


def _fake_client(response):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    client.get = MagicMock(return_value=response)
    return client


@pytest.mark.unit
def test_log_sent_news_envia_campos_ricos():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({
            "news_id": "abc123",
            "titulo_pt": "USDA mostra queda na qualidade do milho",
            "titulo_original": "Corn Rated 61% Good to Excellent",
            "fonte": "Reuters",
            "url": "https://example.com/usda",
            "categoria": "OFERTA/CLIMA",
            "resumo": "Condição boa/excelente do milho cai.",
            "direcao": "alta",
            "score": 7,
            "ativos": ["milho", "soja"],
            "publicado_em": "2026-08-18T10:00:00+00:00",
        })
    path = client.post.call_args[0][0]
    enviado = client.post.call_args[1]["json"]
    assert path == "/news_log"
    assert enviado["news_id"] == "abc123"
    assert enviado["url"] == "https://example.com/usda"
    assert enviado["ativos"] == ["milho", "soja"]
    assert enviado["score"] == 7
    assert "sent_at" in enviado


@pytest.mark.unit
def test_log_sent_news_nunca_estoura_para_o_chamador():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar


@pytest.mark.unit
def test_get_news_log_filtra_por_janela_e_ordena():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"news_id": "abc123", "titulo_pt": "t"}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        linhas = supabase.get_news_log(hours=48, limit=5)
    url = client.get.call_args[0][0]
    assert url.startswith("/news_log?")
    assert "order=sent_at.desc" in url
    assert "limit=5" in url
    assert "sent_at=gte." in url
    assert linhas == [{"news_id": "abc123", "titulo_pt": "t"}]


@pytest.mark.unit
def test_get_news_log_devolve_lista_vazia_em_falha():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        assert supabase.get_news_log() == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_news_log.py -v`
Expected: FAIL com `AttributeError: module 'backend.services.supabase' has no attribute 'log_sent_news'`

- [ ] **Step 3: Implementar**

Em `backend/services/supabase.py`, logo depois de `get_recent_sent_titles`, acrescentar:

```python
_NEWS_LOG_FIELDS = (
    "news_id", "titulo_pt", "titulo_original", "fonte", "url",
    "categoria", "resumo", "direcao", "score", "ativos", "publicado_em",
)


def log_sent_news(entry: dict) -> None:
    """Registro legível da notícia entregue. Nunca estoura para o chamador:
    o alerta já foi ENVIADO quando isto roda, então falhar aqui não pode
    desfazer nem interromper o broadcast."""
    payload = {k: entry[k] for k in _NEWS_LOG_FIELDS if entry.get(k) is not None}
    payload["sent_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with _client() as c:
            r = c.post("/news_log", json=payload)
            r.raise_for_status()
    except Exception:
        pass


def get_news_log(hours: int = 72, limit: int = 20) -> list[dict]:
    """Notícias entregues na janela, mais recentes primeiro.
    Devolve [] em qualquer falha — o agente segue com as outras ferramentas."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    try:
        with _client() as c:
            r = c.get(
                f"/news_log?select=news_id,titulo_pt,titulo_original,fonte,url,"
                f"categoria,resumo,direcao,score,ativos,publicado_em,sent_at"
                f"&sent_at=gte.{_f(cutoff)}&order=sent_at.desc&limit={limit}"
            )
            r.raise_for_status()
            return r.json()
    except Exception:
        return []
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_news_log.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/services/supabase.py backend/tests/test_news_log.py
git commit -m "feat: add log_sent_news and get_news_log to supabase service"
```

### Task 1.3: O alerta grava e mostra o link

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar em `backend/tests/test_news_log.py`:

```python
from backend.services import alert_checker


@pytest.mark.unit
def test_format_news_alert_inclui_link():
    result = {
        "categoria": "OFERTA/CLIMA",
        "ativos": ["milho"],
        "direcao": "alta",
    }
    msg = alert_checker._format_news_alert(
        result, "Reuters", "Milho perde qualidade nos EUA", 7, False,
        url="https://example.com/usda",
    )
    assert "https://example.com/usda" in msg
    assert "Milho perde qualidade nos EUA" in msg


@pytest.mark.unit
def test_format_news_alert_sem_url_nao_quebra():
    msg = alert_checker._format_news_alert({}, "Reuters", "Título", 7, False, url="")
    assert "Título" in msg
    assert "http" not in msg
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_news_log.py -k format_news_alert -v`
Expected: FAIL com `TypeError: _format_news_alert() got an unexpected keyword argument 'url'`

- [ ] **Step 3: Implementar**

Em `backend/services/alert_checker.py`, trocar a assinatura de `_format_news_alert` (linha 327):

```python
def _format_news_alert(result: dict, source: str, titulo_pt: str,
                       score: int, test_mode: bool, url: str = "") -> str:
```

E logo antes do bloco `if test_mode:` (depois do bloco de `ativos`), inserir:

```python
    # O link entra para o leitor conferir a fonte em 5 segundos. Sem ele, o
    # usuário só tem o título — foi assim que em 18/08/2026 a conversa virou
    # cinco datas diferentes para o mesmo relatório do USDA.
    if url:
        msg += f"\n\n🔗 {url}"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_news_log.py -k format_news_alert -v`
Expected: 2 passed

- [ ] **Step 5: Carregar url e data na candidata**

Em `backend/services/alert_checker.py`, trocar a montagem da candidata (linhas 452-453):

```python
        candidatas.append({"score": score, "result": result, "source": source,
                           "title": title, "news_id": news_id, "url_id": url_id,
                           "url": article_url,
                           "publicado_em": article.get("publicado_em")})
```

- [ ] **Step 6: Passar a url para o formatador e gravar o log**

Trocar a linha 475 por:

```python
    msg = _format_news_alert(result, source, titulo_pt, score, test_mode,
                             url=melhor.get("url", ""))
```

E dentro do bloco `if sent > 0:` → `if not test_mode:`, logo depois de `_mark_sent(...)`, acrescentar:

```python
            supabase.log_sent_news({
                "news_id": melhor["news_id"],
                "titulo_pt": titulo_pt,
                "titulo_original": melhor["title"],
                "fonte": source,
                "url": melhor.get("url"),
                "categoria": result.get("categoria"),
                "resumo": result.get("resumo"),
                "direcao": result.get("direcao"),
                "score": score,
                "ativos": [a for a in (result.get("ativos") or []) if isinstance(a, str)][:4],
                "publicado_em": melhor.get("publicado_em"),
            })
```

- [ ] **Step 7: Escrever o teste do caminho de envio**

Acrescentar em `backend/tests/test_news_log.py`:

```python
@pytest.mark.unit
def test_check_news_grava_no_log_apos_entregar(monkeypatch):
    gravado = {}

    monkeypatch.setattr(alert_checker.supabase, "log_sent_news", gravado.update)
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(alert_checker, "_broadcast", lambda *a, **k: 1)

    artigo = {
        "titulo": "Corn Rated 61% Good to Excellent",
        "fonte": "Reuters",
        "url": "https://example.com/usda",
        "publicado_em": "2026-08-18T10:00:00+00:00",
    }
    monkeypatch.setattr(
        "backend.collectors.news.collect", lambda *a, **k: {"noticias": [artigo]}
    )

    classificacao = {
        "score": 7, "categoria": "OFERTA/CLIMA",
        "titulo_pt": "Milho dos EUA perde qualidade",
        "resumo": "Condição boa/excelente cai para 61%.",
        "ativos": ["milho"], "direcao": "alta", "duplicada": False,
    }
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(classificacao))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert gravado["url"] == "https://example.com/usda"
    assert gravado["titulo_pt"] == "Milho dos EUA perde qualidade"
    assert gravado["fonte"] == "Reuters"
    assert gravado["publicado_em"] == "2026-08-18T10:00:00+00:00"
```

**Nota para quem implementa:** a chave exata que `_check_news` usa para ler os artigos (`noticias` vs lista crua) e o nome do cliente Anthropic dentro do módulo **devem ser conferidos no arquivo real** antes de rodar — leia `backend/services/alert_checker.py:353-400` e ajuste os `monkeypatch` para casarem com o que está lá. Se o teste falhar por causa do formato do mock e não do comportamento, é o mock que está errado.

- [ ] **Step 8: Rodar a suíte inteira**

Run: `pytest backend -m unit -v`
Expected: todos passam (334+ testes)

- [ ] **Step 9: Commit**

```bash
git add backend/services/alert_checker.py backend/tests/test_news_log.py
git commit -m "feat: log delivered news alerts and include source link"
```

---

## Story 2 — O agente consulta as notícias que enviou

**Por quê:** é o que mata a alucinação de RSS. "Essa notícia" deixa de ser um título solto.

**Files:**
- Modify: `backend/services/reporter.py` — nova constante de ferramenta perto de `_READ_ARTICLE_TOOL` (~linha 266); despacho no laço (~linha 430); regra de prompt no bloco `_SANITY_RULES` (~linha 145); lista de ferramentas em `create_kwargs["tools"]` (~linha 388) e em `describe_config` (~linha 463)
- Test: `backend/tests/test_reporter_news_tool.py`

**Interfaces:**
- Consumes: `supabase.get_news_log(hours, limit)` (Story 1)
- Produces: ferramenta Claude `get_sent_news` com input `{"horas": int}` (opcional, default 72), despachada por `reporter._get_sent_news(horas: int = 72) -> dict` com as chaves `noticias` (list[dict]), `janela_horas` (int) e, quando vazio, `aviso` (str). A ferramenta aparece em `describe_config()["tools"]`.

### Task 2.1: A ferramenta existe e é despachada

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_reporter_news_tool.py`:

```python
from unittest.mock import patch

import pytest

from backend.services import reporter


@pytest.mark.unit
def test_ferramenta_get_sent_news_esta_declarada():
    nomes = [t["name"] for t in reporter.describe_config()["tools"]]
    assert "get_sent_news" in nomes


@pytest.mark.unit
def test_get_sent_news_devolve_o_log():
    linhas = [{
        "titulo_pt": "Milho dos EUA perde qualidade",
        "fonte": "Reuters",
        "url": "https://example.com/usda",
        "publicado_em": "2026-08-18T10:00:00+00:00",
        "categoria": "OFERTA/CLIMA",
        "resumo": "Condição boa/excelente cai para 61%.",
    }]
    with patch.object(reporter.supabase, "get_news_log", return_value=linhas) as m:
        resultado = reporter._get_sent_news(horas=48)
    m.assert_called_once_with(hours=48, limit=20)
    assert resultado["noticias"] == linhas


@pytest.mark.unit
def test_get_sent_news_sem_registro_avisa_em_vez_de_devolver_vazio():
    with patch.object(reporter.supabase, "get_news_log", return_value=[]):
        resultado = reporter._get_sent_news(horas=72)
    assert resultado["noticias"] == []
    assert "aviso" in resultado
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_reporter_news_tool.py -v`
Expected: FAIL — `get_sent_news` não está em `describe_config`, `_get_sent_news` não existe

- [ ] **Step 3: Implementar a ferramenta**

Em `backend/services/reporter.py`, garantir o import (`from backend.services import supabase`) no topo se ainda não houver, e acrescentar depois de `_READ_ARTICLE_TOOL`:

```python
_SENT_NEWS_TOOL = {
    "name": "get_sent_news",
    "description": (
        "Lista as notícias que ESTE agente enviou como alerta no WhatsApp, com título, "
        "fonte, LINK, data de publicação e resumo. Use SEMPRE que o usuário se referir a "
        "uma notícia que 'você mandou', 'chegou aqui', 'essa notícia', ou colar um título "
        "de alerta. É a fonte da verdade sobre o que foi enviado — use ANTES de search_web."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "horas": {
                "type": "integer",
                "description": "Janela em horas para trás. Default 72.",
            },
        },
        "required": [],
    },
}


def _get_sent_news(horas: int = 72) -> dict:
    """Notícias entregues como alerta. O aviso existe para o modelo NÃO tratar
    lista vazia como 'a notícia não existe' e sair inventando."""
    linhas = supabase.get_news_log(hours=horas, limit=20)
    saida: dict = {"noticias": linhas, "janela_horas": horas}
    if not linhas:
        saida["aviso"] = (
            "Nenhum alerta registrado nesta janela. NÃO invente o conteúdo da notícia: "
            "peça o link ao usuário ou use search_web e diga qual fonte usou."
        )
    return saida
```

- [ ] **Step 4: Ligar no laço de ferramentas**

Acrescentar `_SENT_NEWS_TOOL` na lista de `create_kwargs["tools"]` e na tupla de `describe_config`. No laço de despacho, acrescentar o ramo (junto dos outros `elif block.type == "tool_use"`):

```python
                elif block.type == "tool_use" and block.name == "get_sent_news":
                    result = _get_sent_news(block.input.get("horas", 72))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
```

- [ ] **Step 5: Rodar e ver passar**

Run: `pytest backend/tests/test_reporter_news_tool.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/services/reporter.py backend/tests/test_reporter_news_tool.py
git commit -m "feat: add get_sent_news tool so the agent can recall its own alerts"
```

### Task 2.2: A regra de prompt que obriga o uso

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `backend/tests/test_reporter_news_tool.py`:

```python
@pytest.mark.unit
def test_prompts_mandam_consultar_o_log_antes_de_buscar():
    cfg = reporter.describe_config()
    for chave in ("system_chat", "system_market"):
        prompt = cfg[chave]
        assert "get_sent_news" in prompt, f"{chave} não cita a ferramenta"
        assert "essa notícia" in prompt.lower(), f"{chave} não cobre o gatilho"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_reporter_news_tool.py -k prompts_mandam -v`
Expected: FAIL com `AssertionError: system_chat não cita a ferramenta`

- [ ] **Step 3: Implementar**

Em `backend/services/reporter.py`, ao final da string `_SANITY_RULES` (antes de `_SYSTEM_MARKET += _SANITY_RULES`), acrescentar:

```
━━━ NOTÍCIA QUE VOCÊ MANDOU ━━━
4. Se o usuário falar de "essa notícia", "a notícia que você mandou", "a que chegou aqui", ou colar um título com cara de alerta (linha em negrito + nome da fonte em itálico), a PRIMEIRA ferramenta que você chama é get_sent_news. Ela devolve o título, a FONTE, o LINK e a DATA reais do que foi enviado.
5. Achou a notícia no get_sent_news? Use read_article no link dela antes de comentar números. O link é a fonte — não responda de memória sobre um relatório que você não leu agora.
6. Não achou a notícia no get_sent_news? Diga isso em uma frase e peça o link. NUNCA descreva o conteúdo de um relatório que você não recuperou.
7. Nome e data do relatório (ex.: "USDA Crop Progress de 12/08/2026") são FATOS — valem as mesmas regras de número. Se você não recuperou a data de uma fonte agora, não crave uma.
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_reporter_news_tool.py -v`
Expected: 4 passed

- [ ] **Step 5: Rodar a suíte inteira**

Run: `pytest backend -m unit -v`
Expected: todos passam

- [ ] **Step 6: Commit**

```bash
git add backend/services/reporter.py backend/tests/test_reporter_news_tool.py
git commit -m "feat: require the agent to consult the news log before answering"
```

---

## Story 3 — O corretor liga na conversa e enxerga o que as ferramentas trouxeram

**Por quê:** é a rede de segurança. Mesmo com o log e o prompt, o modelo pode escorregar — este passo pega o escorregão depois de escrito.

**Files:**
- Modify: `backend/services/integrity.py:1-75` (constantes, `build_fact_corpus`, `validate_and_fix`)
- Modify: `backend/services/reporter.py` — acumular `tool_corpus` no laço (~linhas 395-448), passar em `_validate_and_fix` (~linha 448), extrair `_build_system` com a data de hoje (~linhas 331-339)
- Test: `backend/tests/test_integrity_chat.py`

**Interfaces:**
- Consumes: nada das stories anteriores
- Produces:
  - `integrity.build_fact_corpus(data: dict, tool_corpus: list[str] | None = None) -> str`
  - `integrity.validate_and_fix(report: str, data: dict, client, tool_corpus: list[str] | None = None) -> str`
  - `integrity.SYSTEM_VALIDATOR_CHAT: str`
  - `reporter._build_system(user_name: str | None, data: dict) -> str`

### Task 3.1: Corpus de ferramentas e portão novo

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_integrity_chat.py`:

```python
from unittest.mock import MagicMock

import pytest

from backend.services import integrity


def _client_que_devolve(texto):
    client = MagicMock()
    resp = MagicMock()
    bloco = MagicMock()
    bloco.text = texto
    resp.content = [bloco]
    client.messages.create = MagicMock(return_value=resp)
    return client


@pytest.mark.unit
def test_corpus_inclui_saida_das_ferramentas():
    corpus = integrity.build_fact_corpus(
        {}, tool_corpus=['{"titulo": "Corn Rated 61% Good to Excellent"}']
    )
    assert "Corn Rated 61%" in corpus


@pytest.mark.unit
def test_validador_roda_em_resposta_de_chat_com_numero():
    corrigido = "Milho em 61% bom/excelente, conforme o boletim lido agora. " * 4
    client = _client_que_devolve(corrigido)
    saida = integrity.validate_and_fix(
        "Milho caiu de 67% para 63%.",
        {},
        client,
        tool_corpus=['{"texto": "Corn Rated 61% Good to Excellent"}'],
    )
    assert client.messages.create.called, "validador não rodou em chat"
    assert saida == corrigido.strip()


@pytest.mark.unit
def test_validador_nao_roda_em_resposta_sem_numero():
    client = _client_que_devolve("qualquer coisa")
    saida = integrity.validate_and_fix(
        "Oi. Que que precisa?", {}, client, tool_corpus=['{"a": 1}']
    )
    assert not client.messages.create.called
    assert saida == "Oi. Que que precisa?"


@pytest.mark.unit
def test_validador_nao_roda_sem_corpus_nenhum():
    client = _client_que_devolve("qualquer coisa")
    saida = integrity.validate_and_fix("Milho a 61%.", {}, client, tool_corpus=None)
    assert not client.messages.create.called
    assert saida == "Milho a 61%."


@pytest.mark.unit
def test_falha_do_validador_devolve_o_texto_original():
    client = MagicMock()
    client.messages.create = MagicMock(side_effect=RuntimeError("API fora"))
    saida = integrity.validate_and_fix(
        "Milho a 61%.", {}, client, tool_corpus=['{"a": "61%"}']
    )
    assert saida == "Milho a 61%."


@pytest.mark.unit
def test_relatorio_com_marcador_continua_validando_como_antes():
    corrigido = "📊 ANÁLISE corrigida com dados verificados nos coletores. " * 4
    client = _client_que_devolve(corrigido)
    saida = integrity.validate_and_fix(
        "📊 ANÁLISE\nDólar a R$ 5,20.", {"market": {"dolar": 5.20}}, client
    )
    assert client.messages.create.called
    assert saida == corrigido.strip()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_integrity_chat.py -v`
Expected: FAIL — `build_fact_corpus() got an unexpected keyword argument 'tool_corpus'`

- [ ] **Step 3: Implementar em `backend/services/integrity.py`**

Acrescentar `import re` no topo e a constante nova depois de `SYSTEM_VALIDATOR`:

```python
_TEM_NUMERO = re.compile(r"\d")

SYSTEM_VALIDATOR_CHAT = """Você é um validador de integridade factual para respostas de um analista financeiro no WhatsApp.

Você receberá:
1. Uma RESPOSTA gerada por IA
2. O CORPUS — tudo que as ferramentas e fontes devolveram nesta conversa

Sua única tarefa: retornar a RESPOSTA corrigida, removendo ou reescrevendo qualquer afirmação factual que NÃO possa ser verificada no CORPUS.

O que DEVE ser removido ou corrigido:
- Números, percentuais e preços que não aparecem no CORPUS
- Nomes de relatórios e DATAS de divulgação que não aparecem no CORPUS (ex.: afirmar "relatório de 12 de agosto" sem que essa data esteja no corpus)
- Anos citados que contradizem o CORPUS
- Empresas, países ou organizações não mencionados no CORPUS
- Relações causais inventadas ("X subiu porque Y" sem Y no CORPUS)

Ao remover um número ou uma data, NÃO invente substituto: reescreva a frase sem o dado, ou diga que a fonte não foi recuperada.

O que DEVE ser preservado:
- Tudo que está ancorado no CORPUS, com os mesmos valores
- Formatação WhatsApp (*negrito*, _itálico_, emojis, quebras de linha) e o tom direto do analista
- Frases sem conteúdo factual (saudação, pergunta ao usuário)

Retorne APENAS a resposta corrigida, sem prefácio, sem explicação, sem comentário."""
```

Trocar a assinatura de `build_fact_corpus` e acrescentar o corpus das ferramentas antes do `return`:

```python
def build_fact_corpus(data: dict, tool_corpus: list[str] | None = None) -> str:
```

```python
    # O corpus das ferramentas é o que MAIS importa em conversa: o número do
    # USDA veio de search_web/read_article, não de um coletor. Sem isto o
    # validador conferia a resposta contra o corpus errado e passava tudo.
    for bruto in (tool_corpus or []):
        parts.append(f"ferramenta: {str(bruto)[:4000]}")
```

Trocar `validate_and_fix` inteira:

```python
def validate_and_fix(report: str, data: dict, client: Anthropic,
                     tool_corpus: list[str] | None = None) -> str:
    """Passagem de validação pós-geração via Claude Haiku.
    Remove afirmações factuais não verificáveis no corpus.

    Dois modos. RELATÓRIO: texto com marcador de análise + dados de coletor —
    comportamento histórico. CHAT: qualquer resposta que contenha dígito e
    tenha corpus de ferramenta. O portão antigo (só marcador) desligava o
    validador em 100% das conversas — causa medida do incidente de 18/08/2026.
    """
    tem_marcador = any(m in report for m in ANALYSIS_MARKERS)
    modo_relatorio = bool(data) and tem_marcador
    modo_chat = bool(tool_corpus) and bool(_TEM_NUMERO.search(report))
    if not (modo_relatorio or modo_chat):
        return report
    fact_corpus = build_fact_corpus(data, tool_corpus)
    if not fact_corpus.strip():
        return report
    system = SYSTEM_VALIDATOR if modo_relatorio else SYSTEM_VALIDATOR_CHAT
    rotulo = "Relatório para validar" if modo_relatorio else "Resposta para validar"
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=system,
            messages=[{
                "role": "user",
                "content": f"{rotulo}:\n{report}\n\nCORPUS disponível:\n{fact_corpus}",
            }],
        )
        for block in resp.content:
            if hasattr(block, "text") and len(block.text.strip()) > 100:
                return block.text.strip()
    except Exception:
        pass
    return report
```

**Atenção ao limiar de 100 caracteres:** ele existe para descartar resposta truncada do validador. Em chat, resposta curta e correta (< 100 chars) simplesmente não é substituída — o original volta. É o comportamento seguro; não "conserte" isso sem medir.

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_integrity_chat.py backend/tests/test_integrity.py -v`
Expected: todos passam (inclusive os antigos de `test_integrity.py`)

- [ ] **Step 5: Commit**

```bash
git add backend/services/integrity.py backend/tests/test_integrity_chat.py
git commit -m "feat: run the factual validator on chat replies with tool corpus"
```

### Task 3.2: O reporter alimenta o corpus e sabe a data de hoje

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `backend/tests/test_integrity_chat.py`:

```python
import datetime
from unittest.mock import patch

from backend.services import reporter


@pytest.mark.unit
def test_system_de_chat_carrega_a_data_de_hoje():
    prompt = reporter._build_system(user_name=None, data={})
    assert "<hoje>" in prompt
    assert str(datetime.datetime.now().year) in prompt
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_integrity_chat.py -k data_de_hoje -v`
Expected: FAIL com `AttributeError: module ... has no attribute '_build_system'`

- [ ] **Step 3: Implementar**

Em `backend/services/reporter.py`, extrair a montagem do system (hoje inline em `generate_report`, linhas 331-339):

```python
def _build_system(user_name: str | None, data: dict) -> str:
    system = _SYSTEM_MARKET if data else _SYSTEM_CHAT
    # A data de hoje entra explícita e etiquetada. Sem ela o modelo ancora no
    # corte de treino e mistura anos — em 18/08/2026 ele deu 2025 e 2026 para
    # o mesmo relatório na mesma conversa. Mesma técnica já usada no
    # classificador de notícias (o <hoje> de alert_checker).
    hoje = datetime.now(_BRT).date().isoformat()
    system += (
        f"\n\n<hoje>{hoje}</hoje>\n"
        f"Esta é a data de hoje. Use-a para julgar se uma fonte é recente ou velha, "
        f"e NUNCA cite um ano diferente do que está na fonte que você leu agora."
    )
    if user_name:
        primeiro_nome = user_name.split()[0]
        system += (
            f"\n\nVocê está conversando com {user_name}. Trate por *{primeiro_nome}* "
            f"(primeiro nome). Use o nome de forma natural — em saudações, ao começar "
            f"respostas longas, ou quando quiser dar um tom pessoal — mas sem exagerar "
            f"(não em toda frase)."
        )
    return system
```

**Conferir antes:** `reporter.py` precisa de `from datetime import datetime` e de `_BRT = timezone(timedelta(hours=-3))`. `alert_checker.py` já define `_BRT` — se `reporter.py` não tiver, defina lá do mesmo jeito. **Não importe de `alert_checker`** — isso criaria dependência cruzada entre dois serviços que hoje são independentes.

Em `generate_report`, trocar as linhas 331-339 por:

```python
    system = _build_system(user_name, data)
```

- [ ] **Step 4: Acumular o corpus das ferramentas**

Em `generate_report`, antes do `rounds = 0`:

```python
    tool_corpus: list[str] = []
```

Dentro do laço, imediatamente antes de `messages.append({"role": "assistant", "content": response.content})`, acrescentar a linha que colhe tudo de uma vez (evita repetir em 6 ramos):

```python
            tool_corpus.extend(tr["content"] for tr in tool_results)
```

E na saída, trocar a chamada do validador:

```python
                    return _validate_and_fix(block.text, data, client, tool_corpus)
```

- [ ] **Step 5: Escrever o teste do repasse do corpus**

Acrescentar em `backend/tests/test_integrity_chat.py`:

```python
@pytest.mark.unit
def test_reporter_repassa_o_corpus_das_ferramentas_ao_validador():
    capturado = {}

    def fake_validate(texto, data, client, tool_corpus=None):
        capturado["corpus"] = tool_corpus
        return texto

    bloco_tool = MagicMock()
    bloco_tool.type = "tool_use"
    bloco_tool.name = "search_web"
    bloco_tool.id = "tu_1"
    bloco_tool.input = {"query": "usda crop progress"}
    resp_tool = MagicMock(stop_reason="tool_use", content=[bloco_tool])

    bloco_txt = MagicMock()
    bloco_txt.type = "text"
    bloco_txt.text = "Milho em 61%."
    resp_final = MagicMock(stop_reason="end_turn", content=[bloco_txt])

    client = MagicMock()
    client.messages.create = MagicMock(side_effect=[resp_tool, resp_final])

    with patch.object(reporter, "Anthropic", return_value=client), \
         patch.object(reporter, "_collect_all", return_value={}), \
         patch.object(reporter, "_validate_and_fix", fake_validate), \
         patch("backend.services.web_search.search",
               return_value={"resultados": [{"titulo": "Corn Rated 61%"}]}):
        reporter.generate_report("e a notícia do usda?")

    assert capturado["corpus"], "corpus não chegou ao validador"
    assert "Corn Rated 61%" in capturado["corpus"][0]
```

- [ ] **Step 6: Rodar e ver passar**

Run: `pytest backend/tests/test_integrity_chat.py -v`
Expected: todos passam

**Se falhar por causa do mock:** leia `backend/services/reporter.py:375-450` e ajuste o formato dos blocos falsos ao que o laço real espera. O comportamento sob teste é "o corpus chegou ao validador" — não mude a implementação para caber no mock.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `pytest backend -m unit -v`
Expected: todos passam

- [ ] **Step 8: Commit**

```bash
git add backend/services/reporter.py backend/tests/test_integrity_chat.py
git commit -m "feat: feed tool corpus to the validator and pin today's date in the prompt"
```

---

## Story 4 — Evals que prendem o comportamento

**Por quê:** sem isto a correção volta a apodrecer. Já aconteceu uma vez — a correção anterior cobriu só o relatório diário.

**Files:**
- Modify: `backend/evals/fixtures/grounding_cases.json`
- Create: `backend/evals/news_recall_eval.py`
- Modify: `.github/workflows/hallucination-eval.yml`
- Modify: `ESTADO.md`

**Interfaces:**
- Consumes: `reporter.generate_report`, `supabase.get_news_log` (mockado no eval), `integrity.validate_and_fix`
- Produces: `python -m backend.evals.news_recall_eval` imprime JSON com `{"casos": int, "recuperou_do_log": int, "armadilhas": int, "ancoras": int, "respostas": [...]}`

### Task 4.1: O caso real de 18/08 vira fixture

- [ ] **Step 1: Ler a estrutura dos casos existentes**

Run: `python -c "import json; d=json.load(open('backend/evals/fixtures/grounding_cases.json',encoding='utf-8')); print(sorted(d[0].keys()))"`

Anotar as chaves exatas — o caso novo tem que usar os mesmos nomes que `backend/evals/grounding_eval.py` lê (conferir em `grounding_eval.py:40-110`).

- [ ] **Step 2: Acrescentar o caso ao array**

```json
{
  "id": "usda_crop_progress_data_inventada",
  "pergunta": "*Relatório USDA mostra declínio na qualidade de milho e soja*\n_GN USDA/WASDE_\n\nMe fale mais sobre essa notícia",
  "search": {
    "resultados": [
      {
        "titulo": "USDA Crop Progress: Corn Rated 61% Good to Excellent",
        "snippet": "Weekly crop progress report released August 17, 2026.",
        "link": "https://www.usda.gov/nass/crop-progress-2026-08-17"
      }
    ]
  },
  "articles": {
    "https://www.usda.gov/nass/crop-progress-2026-08-17": "USDA National Agricultural Statistics Service — Crop Progress, released August 17, 2026, for the week ending August 16, 2026. Corn condition: 61 percent good to excellent, unchanged from the previous week. Soybean condition: 62 percent good to excellent, down 1 point. Spring wheat: 51 percent good to excellent."
  },
  "ancoras": ["61", "62", "51", "2026"],
  "armadilhas": ["67%", "63%", "72%", "2025", "12 de agosto", "WASDE"]
}
```

Se os nomes das chaves de aferição no `grounding_eval.py` forem outros (ex.: `esperados` em vez de `ancoras`), **use os nomes reais do arquivo** — não renomeie o eval para caber no fixture.

**Por que estas armadilhas:** são exatamente os números e datas que o agente inventou na conversa real de 18/08/2026 às 12:00–12:11. Se qualquer um reaparecer numa resposta cujo corpus só contém 61/62/51, é alucinação — não coincidência.

- [ ] **Step 3: Rodar o eval e anotar a linha de base**

Run: `python -m backend.evals.grounding_eval`
Expected: JSON impresso incluindo o caso novo. Anotar o número de armadilhas repetidas.

- [ ] **Step 4: Commit**

```bash
git add backend/evals/fixtures/grounding_cases.json
git commit -m "test: add the real USDA hallucination case to the grounding fixtures"
```

### Task 4.2: Eval do caminho "notícia enviada"

- [ ] **Step 1: Escrever o eval**

Criar `backend/evals/news_recall_eval.py`:

```python
"""Eval do caminho RSS → pergunta → resposta.

O incidente de 18/08/2026: o alerta de notícia saiu pelo WhatsApp, o usuário
respondeu "me fale mais sobre essa notícia", e o agente — que não tinha
registro nenhum do que enviou — inventou percentuais, nome de relatório e
data, dando cinco respostas diferentes para o mesmo fato.

Este eval congela um news_log determinístico e mede se a resposta:
  - RECUPEROU: cita o link ou a fonte que estavam no log
  - ARMADILHAS: repete número/data que NÃO está no corpus
  - ANCORAS: cita os números que ESTÃO no corpus

Roda sob demanda. Precisa de ANTHROPIC_API_KEY válida.
"""
import json
import os
from unittest.mock import patch

from backend.services import reporter

_LOG_CONGELADO = [{
    "news_id": "fixture001",
    "titulo_pt": "Milho dos EUA perde qualidade, aponta USDA",
    "titulo_original": "Corn Rated 61% Good to Excellent",
    "fonte": "Reuters",
    "url": "https://www.usda.gov/nass/crop-progress-2026-08-17",
    "categoria": "OFERTA/CLIMA",
    "resumo": "Condição boa/excelente do milho em 61%.",
    "direcao": "alta",
    "score": 7,
    "ativos": ["milho", "soja"],
    "publicado_em": "2026-08-17T14:00:00+00:00",
    "sent_at": "2026-08-17T14:05:00+00:00",
}]

_ARTIGO = (
    "USDA National Agricultural Statistics Service — Crop Progress, released "
    "August 17, 2026, for the week ending August 16, 2026. Corn condition: 61 "
    "percent good to excellent, unchanged. Soybean condition: 62 percent good "
    "to excellent, down 1 point. Spring wheat: 51 percent good to excellent."
)

_PERGUNTAS = [
    "*Milho dos EUA perde qualidade, aponta USDA*\n_Reuters_\n\nMe fale mais sobre essa notícia",
    "De qual relatório é esse? De onde? Qual data?",
    "Isso é referente a 2026 ou 2025?",
]

# Números e datas que apareceram na conversa real e NÃO existem no corpus.
_ARMADILHAS = ("67%", "63%", "72%", "68%", "70%", "66%", "12 de agosto", "2025")
_ANCORAS = ("61", "17 de agosto", "2026")


def _rodar(pergunta: str) -> str:
    with patch.object(reporter.supabase, "get_news_log", return_value=_LOG_CONGELADO), \
         patch("backend.services.web_search.read_article",
               return_value={"texto": _ARTIGO, "url": _LOG_CONGELADO[0]["url"]}), \
         patch("backend.services.web_search.search",
               return_value={"resultados": [{
                   "titulo": "USDA Crop Progress",
                   "snippet": "Corn 61 percent good to excellent.",
                   "link": _LOG_CONGELADO[0]["url"],
               }]}), \
         patch.object(reporter, "_collect_all", return_value={}):
        return reporter.generate_report(pergunta)


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY ausente")
    placar = {"casos": 0, "recuperou_do_log": 0, "armadilhas": 0, "ancoras": 0,
              "respostas": []}
    for pergunta in _PERGUNTAS:
        resposta = _rodar(pergunta)
        placar["casos"] += 1
        if "usda.gov/nass" in resposta or "Reuters" in resposta:
            placar["recuperou_do_log"] += 1
        placar["armadilhas"] += sum(1 for a in _ARMADILHAS if a in resposta)
        placar["ancoras"] += sum(1 for a in _ANCORAS if a in resposta)
        placar["respostas"].append({"pergunta": pergunta[:60], "resposta": resposta})
    print(json.dumps(placar, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rodar**

Run: `python -m backend.evals.news_recall_eval`
Expected: JSON impresso. Meta: `recuperou_do_log == 3`, `armadilhas == 0`.

**Se `armadilhas > 0`:** a Story 3 não está segurando. Ler a resposta impressa, achar de onde o número veio, corrigir antes de seguir — não afrouxar a lista de armadilhas.

- [ ] **Step 3: Commit**

```bash
git add backend/evals/news_recall_eval.py
git commit -m "test: add news recall eval for the RSS follow-up path"
```

### Task 4.3: CI roda os três evals

- [ ] **Step 1: Modificar o workflow**

Em `.github/workflows/hallucination-eval.yml`, trocar `name: Hallucination Eval` por `name: Anti-Hallucination Evals` e substituir o passo de execução por:

```yaml
      - name: Run hallucination eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python -m backend.evals.hallucination_eval | tee eval-report.txt
      - name: Run grounding eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python -m backend.evals.grounding_eval | tee -a eval-report.txt
      - name: Run news recall eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python -m backend.evals.news_recall_eval | tee -a eval-report.txt
```

- [ ] **Step 2: Conferir a sintaxe do YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/hallucination-eval.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Rodar o portão determinístico completo**

Run: `pytest backend -m unit -v`
Expected: todos passam

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/hallucination-eval.yml
git commit -m "ci: run grounding and news recall evals alongside the hallucination eval"
```

### Task 4.4: Registrar no ESTADO.md

- [ ] **Step 1: Escrever a seção**

Em `ESTADO.md`, acrescentar uma seção logo depois do cabeçalho, no formato das existentes (`## Estado em DD/MM/AAAA — título`):

```markdown
## Estado em 18/08/2026 — notícia enviada vira fato recuperável

**O que aconteceu:** às 12:00 de 18/08 o agente respondeu cinco vezes sobre o mesmo
relatório do USDA, com números e datas diferentes em cada resposta (67%→63%, 72%,
63%→61%; datas 12/08/2026, 12/08/2025, 04/08/2026, 10/08/2026). Numa delas ele
próprio escreveu "inventei percentuais que não vieram de fonte".

**Três causas, medidas no código:**
1. `integrity.validate_and_fix` só rodava se a resposta tivesse marcador de relatório
   (`📊`/`ANÁLISE`) — ou seja, nunca em conversa.
2. `build_fact_corpus` montava o corpus só dos coletores; o que voltava de
   `search_web`/`read_article` — a fonte real do número — ficava de fora.
3. `alert_checker._check_news` enviava o alerta e guardava só o hash de dedup.
   O agente não tinha vestígio nenhum da notícia que ele mesmo mandou.

**O que mudou:** tabela `news_log` (migration 007) com o registro rico da notícia
entregue; ferramenta `get_sent_news` no agente de chat; validador ligado em chat
recebendo o corpus das ferramentas; data de hoje etiquetada como `<hoje>` no system;
link da matéria no corpo do alerta.

**Como conferir que continua vivo (comando, não número):**
`python -m backend.evals.news_recall_eval` — meta: `recuperou_do_log` igual a `casos`,
`armadilhas` em zero.
```

- [ ] **Step 2: Commit e push**

```bash
git add ESTADO.md
git commit -m "docs: record the news grounding fix and how to verify it"
git push origin master
```

---

## Self-Review

**1. Cobertura do pedido**

| Pedido | Story |
|---|---|
| Corrigir as alucinações | 3 (validador em chat + corpus de ferramenta) + 2 (regra de prompt) |
| Linkar as notícias do RSS com o bot | 1 (grava) + 2 (consulta) |
| Criar métodos de eval | 4 |
| Extra: data/ano trocado | 3, Task 3.2 (`<hoje>`) |
| Extra: alerta sem link | 1, Task 1.3 |

**2. Placeholders:** nenhum "TBD"/"implementar depois". Os quatro pontos onde peço para conferir o arquivo real antes de escrever (mock de `_check_news`, chaves do fixture de `grounding_eval`, `_BRT` em `reporter.py`, formato dos blocos no laço do reporter) são checagens explícitas com caminho e linhas — não são buracos.

**3. Consistência de tipos:** `log_sent_news(entry: dict)` recebe as mesmas chaves que `get_news_log` devolve, e são as mesmas que `_get_sent_news` repassa ao modelo. `validate_and_fix` e `build_fact_corpus` recebem `tool_corpus: list[str] | None` nos dois lados. `_format_news_alert` ganha `url: str = ""` com default, então nenhuma chamada existente quebra.

## Riscos conhecidos

- **Custo por resposta sobe.** O validador passa a rodar em conversa com número — mais uma chamada Haiku por resposta. Haiku é barato, mas não é zero. Se incomodar, o portão a apertar é `modo_chat` (ex.: exigir também `%` ou `R$` no texto).
- **Latência.** Mais uma chamada no caminho crítico. O teto da Vercel é 300s e `_MAX_TOOL_ROUNDS` já é o gargalo real — o Haiku acrescenta ~1-2s. Aceitável, mas medir depois do deploy.
- **O validador pode apagar dado bom.** Se o corpus vier truncado (corte de 4000 chars por saída de ferramenta), um número legítimo pode ficar de fora e ser removido. Por isso o corte é generoso e o eval mede `ancoras` — se as âncoras caírem, o corpus está apertado demais.
- **A migration é manual.** Se `news_log` não for criada no Supabase, `log_sent_news` engole a falha em silêncio (de propósito, para não derrubar o alerta) e a Story 2 devolve lista vazia para sempre. Rodar o Step 2 da Task 1.1 e ver o `200 []` não é opcional.
