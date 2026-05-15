# News Feedback Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando o usuário diz quais notícias do relatório foram relevantes, o agente armazena esse feedback no Supabase e usa-o para priorizar temas nas próximas curadoria de notícias.

**Architecture:** Nova tabela `news_feedback` no Supabase acumula tópicos importantes/irrelevantes por usuário. O webhook detecta mensagens de feedback via Claude Haiku (mesmo padrão de `_detect_preference_intent`), salva e responde com confirmação + pergunta de refinamento gerada pelo Claude. Em toda chamada a `generate_report`, os feedbacks acumulados são injetados no system prompt de `_SYSTEM_MARKET`.

**Tech Stack:** FastAPI, Anthropic SDK (claude-haiku-4-5-20251001 para detecção), Supabase REST API via httpx, pytest + unittest.mock.

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| Supabase migration | criar | Tabela `news_feedback` + índice |
| `backend/services/supabase.py` | modificar | +3 funções: save/get/delete news_feedback |
| `backend/tests/test_news_feedback.py` | criar | Testes de integração das funções Supabase |
| `backend/services/reporter.py` | modificar | +parâmetro `news_feedback`, injeção no system prompt |
| `backend/tests/test_reporter_sections.py` | modificar | +3 testes de injeção de feedback |
| `backend/api/main.py` | modificar | +`_NEWS_FEEDBACK_SYSTEM`, `_detect_news_feedback()`, `_generate_feedback_confirmation()`, webhook atualizado |
| `backend/tests/test_webhook_news_feedback.py` | criar | Testes do fluxo de feedback no webhook |
| `backend/api/cron_report.py` | modificar | Passar `news_feedback` no loop do cron |
| `backend/tests/test_cron_report.py` | modificar | Atualizar mocks + novo teste de passagem do feedback |

---

## Task 1: Supabase — Criar tabela `news_feedback`

**Files:**
- Supabase project: `gswwsvwjkycvcszxblmt`

- [ ] **Step 1: Aplicar migration via MCP Supabase**

Use a ferramenta `mcp__plugin_supabase_supabase__apply_migration` com:
```json
{
  "project_id": "gswwsvwjkycvcszxblmt",
  "name": "create_news_feedback",
  "query": "CREATE TABLE public.news_feedback (\n    id                 bigint generated always as identity primary key,\n    phone              text        not null,\n    important_topics   jsonb       not null default '[]'::jsonb,\n    unimportant_topics jsonb       not null default '[]'::jsonb,\n    raw_feedback       text,\n    created_at         timestamptz not null default now()\n);\nCREATE INDEX news_feedback_phone_idx ON public.news_feedback (phone);"
}
```

- [ ] **Step 2: Verificar que a tabela foi criada**

Use `mcp__plugin_supabase_supabase__list_tables` com `project_id: gswwsvwjkycvcszxblmt` e confirme que `public.news_feedback` aparece na lista.

---

## Task 2: `supabase.py` — Funções de feedback

**Files:**
- Modify: `backend/services/supabase.py`
- Create: `backend/tests/test_news_feedback.py`

- [ ] **Step 1: Escrever os testes (falhos)**

Criar `backend/tests/test_news_feedback.py`:

```python
import pytest
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase

PHONE_TEST = "5500000000001"


def teardown_function():
    supabase.delete_news_feedback(PHONE_TEST)


def test_save_and_get_news_feedback():
    supabase.save_news_feedback(
        PHONE_TEST,
        important=["Fed", "juros"],
        unimportant=["eleições"],
        raw="só a notícia do Fed foi boa",
    )
    records = supabase.get_news_feedback(PHONE_TEST)
    assert len(records) == 1
    assert "Fed" in records[0]["important_topics"]
    assert "eleições" in records[0]["unimportant_topics"]


def test_get_news_feedback_vazio():
    supabase.delete_news_feedback(PHONE_TEST)
    records = supabase.get_news_feedback(PHONE_TEST)
    assert records == []


def test_delete_news_feedback():
    supabase.save_news_feedback(PHONE_TEST, ["SELIC"], [], "boa notícia sobre SELIC")
    supabase.delete_news_feedback(PHONE_TEST)
    assert supabase.get_news_feedback(PHONE_TEST) == []


def test_save_multiplos_feedbacks_acumula():
    supabase.save_news_feedback(PHONE_TEST, ["Fed"], [], "feedback 1")
    supabase.save_news_feedback(PHONE_TEST, ["SELIC"], ["política"], "feedback 2")
    records = supabase.get_news_feedback(PHONE_TEST)
    assert len(records) == 2
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest backend/tests/test_news_feedback.py -v
```

Esperado: `AttributeError: module 'backend.services.supabase' has no attribute 'save_news_feedback'`

- [ ] **Step 3: Implementar as três funções em `supabase.py`**

Adicionar ao final de `backend/services/supabase.py` (após `get_users_for_hour`):

```python
def save_news_feedback(phone: str, important: list, unimportant: list, raw: str) -> None:
    with _client() as c:
        r = c.post("/news_feedback", json={
            "phone": phone,
            "important_topics": important,
            "unimportant_topics": unimportant,
            "raw_feedback": raw,
        })
        r.raise_for_status()


def get_news_feedback(phone: str, limit: int = 15) -> list[dict]:
    with _client() as c:
        r = c.get(
            f"/news_feedback?phone=eq.{phone}"
            f"&select=important_topics,unimportant_topics"
            f"&order=created_at.desc&limit={limit}"
        )
        r.raise_for_status()
        return r.json()


def delete_news_feedback(phone: str) -> None:
    with _client() as c:
        r = c.delete(f"/news_feedback?phone=eq.{phone}")
        r.raise_for_status()
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```
pytest backend/tests/test_news_feedback.py -v
```

Esperado: 4 testes PASS

- [ ] **Step 5: Commit**

```
git add backend/services/supabase.py backend/tests/test_news_feedback.py
git commit -m "feat: add news_feedback supabase functions and table"
```

---

## Task 3: `reporter.py` — Parâmetro `news_feedback` e injeção no system prompt

**Files:**
- Modify: `backend/services/reporter.py:155-160` (assinatura de `generate_report`)
- Modify: `backend/tests/test_reporter_sections.py`

- [ ] **Step 1: Adicionar testes ao `test_reporter_sections.py`**

Adicionar ao final do arquivo `backend/tests/test_reporter_sections.py`:

```python
def test_generate_report_injeta_news_feedback_no_system():
    feedback = [
        {"important_topics": ["Fed", "juros"], "unimportant_topics": ["eleições"]},
    ]
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="relatório")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA, \
         patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, n, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        MockA.return_value.messages.create.side_effect = capture_create
        reporter.generate_report("relatório", news_feedback=feedback)
    assert "PRIORIZAR" in captured_system[0]
    assert "Fed" in captured_system[0]
    assert "eleições" in captured_system[0]
    assert "EVITAR" in captured_system[0]


def test_generate_report_sem_feedback_nao_injeta():
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="relatório")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA, \
         patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, n, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        MockA.return_value.messages.create.side_effect = capture_create
        reporter.generate_report("relatório", news_feedback=None)
    assert "PRIORIZAR" not in captured_system[0]


def test_generate_report_feedback_nao_injeta_em_chat():
    """news_feedback não deve afetar _SYSTEM_CHAT (quando sections={}, sem dados de mercado)."""
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="resposta")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA:
        MockA.return_value.messages.create.side_effect = capture_create
        # sections={} → _collect_all retorna {} → _SYSTEM_CHAT
        reporter.generate_report("olá", news_feedback=feedback, sections={})
    assert "PRIORIZAR" not in captured_system[0]
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest backend/tests/test_reporter_sections.py::test_generate_report_injeta_news_feedback_no_system -v
```

Esperado: `TypeError: generate_report() got an unexpected keyword argument 'news_feedback'`

- [ ] **Step 3: Implementar em `reporter.py`**

Substituir a assinatura e adicionar o bloco de injeção em `generate_report` (linhas 155–188 atuais). A assinatura muda de:

```python
def generate_report(
    user_message: str,
    history: list[dict] | None = None,
    user_name: str | None = None,
    sections: dict | None = None,
) -> str:
```

Para:

```python
def generate_report(
    user_message: str,
    history: list[dict] | None = None,
    user_name: str | None = None,
    sections: dict | None = None,
    news_feedback: list[dict] | None = None,
) -> str:
```

Depois do bloco `if user_name:` (linha ~173) e antes de `ticker_data = _extract_ticker_data(user_message)`, adicionar:

```python
    if data and news_feedback:
        important: list[str] = []
        unimportant: list[str] = []
        for fb in news_feedback:
            important.extend(fb.get("important_topics") or [])
            unimportant.extend(fb.get("unimportant_topics") or [])
        seen_i: set = set()
        seen_u: set = set()
        unique_important = [x for x in important if not (x in seen_i or seen_i.add(x))]
        unique_unimportant = [x for x in unimportant if not (x in seen_u or seen_u.add(x))]
        if unique_important or unique_unimportant:
            fb_text = "\n\nPREFERÊNCIAS DE NOTÍCIAS DO USUÁRIO (baseado em feedbacks anteriores):"
            if unique_important:
                fb_text += f"\nPRIORIZAR temas: {', '.join(unique_important)}"
            if unique_unimportant:
                fb_text += f"\nEVITAR ou desprioritizar: {', '.join(unique_unimportant)}"
            fb_text += "\nAo selecionar e destacar notícias no relatório, filtre de acordo com essas preferências."
            system += fb_text
```

- [ ] **Step 4: Rodar todos os testes do reporter**

```
pytest backend/tests/test_reporter_sections.py -v
```

Esperado: todos os testes PASS (incluindo os 3 novos e os 3 anteriores)

- [ ] **Step 5: Commit**

```
git add backend/services/reporter.py backend/tests/test_reporter_sections.py
git commit -m "feat: inject news_feedback preferences into reporter system prompt"
```

---

## Task 4: `main.py` — Detecção de feedback e webhook atualizado

**Files:**
- Modify: `backend/api/main.py`
- Create: `backend/tests/test_webhook_news_feedback.py`

- [ ] **Step 1: Escrever os testes (falhos)**

Criar `backend/tests/test_webhook_news_feedback.py`:

```python
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

AUTHORIZED = {"lid": "553499930185@lid", "phone": "5534999301855", "name": "Ricardim"}


def _make_webhook(text):
    return {
        "data": {
            "key": {"fromMe": False, "remoteJid": "553499930185@lid"},
            "pushName": "Ricardim",
            "message": {"conversation": text},
        }
    }


def test_webhook_news_feedback_salva_e_confirma():
    intent = {"intent": "news_feedback", "important": ["Fed"], "unimportant": ["eleições"]}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value=intent), \
         patch("backend.api.main.supabase.save_news_feedback") as mock_save, \
         patch("backend.api.main._generate_feedback_confirmation", return_value="Anotado!"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("só a notícia do Fed foi boa"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "news_feedback_saved"
    mock_save.assert_called_once_with("5534999301855", ["Fed"], ["eleições"], "só a notícia do Fed foi boa")
    mock_send.assert_called_once_with("5534999301855", "Anotado!")


def test_webhook_news_reset_apaga_e_confirma():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value={"intent": "news_reset"}), \
         patch("backend.api.main.supabase.delete_news_feedback") as mock_delete, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("apaga minhas preferências de notícias"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "news_feedback_reset"
    mock_delete.assert_called_once_with("5534999301855")
    mock_send.assert_called_once()


def test_webhook_mensagem_normal_passa_news_feedback_para_reporter():
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_news_feedback", return_value=feedback), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta") as mock_gen, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_make_webhook("qual o dólar?"))
    assert resp.status_code == 200
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs.get("news_feedback") == feedback


def test_webhook_save_news_feedback_falha_nao_bloqueia_resposta():
    intent = {"intent": "news_feedback", "important": ["Fed"], "unimportant": []}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value=intent), \
         patch("backend.api.main.supabase.save_news_feedback", side_effect=Exception("timeout")), \
         patch("backend.api.main._generate_feedback_confirmation", return_value="Anotado!"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("só a notícia do Fed foi boa"))
    assert resp.status_code == 200
    mock_send.assert_called_once_with("5534999301855", "Anotado!")


def test_detect_news_feedback_retorna_message_quando_listas_vazias():
    """Se Haiku retorna news_feedback mas com listas vazias, trata como message."""
    from backend.api.main import _detect_news_feedback
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"intent": "news_feedback", "important": [], "unimportant": []}')]
    with patch("backend.api.main.Anthropic") as MockA:
        MockA.return_value.messages.create.return_value = mock_response
        result = _detect_news_feedback("olá tudo bem")
    assert result["intent"] == "message"


def test_detect_news_feedback_fallback_em_excecao():
    from backend.api.main import _detect_news_feedback
    with patch("backend.api.main.Anthropic", side_effect=Exception("network error")):
        result = _detect_news_feedback("só a notícia do Fed foi boa")
    assert result["intent"] == "message"
```

- [ ] **Step 2: Rodar para confirmar falha**

```
pytest backend/tests/test_webhook_news_feedback.py -v
```

Esperado: `ImportError` ou `AttributeError` em `_detect_news_feedback` e `_generate_feedback_confirmation` (ainda não existem).

- [ ] **Step 3: Adicionar `_NEWS_FEEDBACK_SYSTEM`, `_FEEDBACK_CONFIRM_SYSTEM`, `_detect_news_feedback()` e `_generate_feedback_confirmation()` em `main.py`**

Após o bloco `_PREFERENCE_SYSTEM` e `_detect_preference_intent` existentes (antes de `@app.post("/api/webhook")`), adicionar:

```python
_NEWS_FEEDBACK_SYSTEM = """Você é um classificador de intenções. Analise a mensagem do usuário e classifique em uma categoria.

CATEGORIA 1 — Feedback sobre quais notícias foram relevantes (ex: "só a notícia X foi importante", "a notícia sobre Y foi boa, o resto não", "quero mais sobre Z, menos sobre W"):
Responda SOMENTE com JSON:
{
  "intent": "news_feedback",
  "important": ["tema ou assunto que o usuário achou relevante"],
  "unimportant": ["tema ou assunto que o usuário achou irrelevante"]
}

CATEGORIA 2 — Pedido de reset das preferências de notícias (ex: "esquece o feedback de notícias", "apaga minhas preferências", "volta ao padrão de notícias"):
Responda SOMENTE com JSON: {"intent": "news_reset"}

CATEGORIA 3 — Qualquer outra mensagem:
Responda SOMENTE com JSON: {"intent": "message"}

Use o contexto do último relatório enviado (se disponível) para identificar os temas corretos quando o usuário referenciar "notícia 1", "segunda notícia", etc."""

_FEEDBACK_CONFIRM_SYSTEM = """Você é um assistente financeiro pelo WhatsApp. O usuário acabou de dar feedback sobre quais notícias do relatório foram relevantes. Confirme o recebimento de forma amigável e natural (2-3 linhas, tom de conversa de WhatsApp) e faça UMA pergunta de refinamento para entender melhor a preferência. Use *negrito* quando útil, emojis com moderação."""


def _detect_news_feedback(text: str, last_report: str | None = None) -> dict:
    messages = []
    if last_report:
        messages.append({"role": "assistant", "content": last_report})
    messages.append({"role": "user", "content": text})
    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_NEWS_FEEDBACK_SYSTEM,
            messages=messages,
        )
        result = json.loads(response.content[0].text)
        if result.get("intent") == "news_feedback":
            if not result.get("important") and not result.get("unimportant"):
                return {"intent": "message"}
        return result
    except Exception:
        return {"intent": "message"}


def _generate_feedback_confirmation(important: list, unimportant: list) -> str:
    parts = []
    if important:
        parts.append(f"Tópicos que o usuário achou relevantes: {', '.join(important)}")
    if unimportant:
        parts.append(f"Tópicos que o usuário achou irrelevantes: {', '.join(unimportant)}")
    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_FEEDBACK_CONFIRM_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        return response.content[0].text
    except Exception:
        return "Anotado! Vou priorizar essas preferências nos próximos relatórios."
```

- [ ] **Step 4: Atualizar o bloco do webhook em `main.py`**

Localizar o trecho que começa com `# Buscar histórico e gerar resposta` e substituir até o final do `try` block pelo seguinte:

```python
        # Buscar histórico e gerar resposta
        history = supabase.get_history(target_phone, limit=10)
        anthropic_history = [{"role": h["role"], "content": h["content"]} for h in history]

        # Detectar feedback/reset de notícias (usa último relatório como contexto)
        last_report = next((h["content"] for h in reversed(history) if h["role"] == "assistant"), None)
        news_intent = _detect_news_feedback(text, last_report=last_report)

        if news_intent.get("intent") == "news_feedback":
            try:
                supabase.save_news_feedback(
                    target_phone,
                    news_intent.get("important", []),
                    news_intent.get("unimportant", []),
                    text,
                )
            except Exception:
                logger.exception("save_news_feedback failed")
            confirmation = _generate_feedback_confirmation(
                news_intent.get("important", []),
                news_intent.get("unimportant", []),
            )
            whatsapp.send_message(target_phone, confirmation)
            return {"status": "ok", "reason": "news_feedback_saved"}

        if news_intent.get("intent") == "news_reset":
            try:
                supabase.delete_news_feedback(target_phone)
            except Exception:
                logger.exception("delete_news_feedback failed")
            whatsapp.send_message(
                target_phone,
                "Preferências de notícias apagadas! Voltarei a enviar a curadoria padrão nos próximos relatórios.",
            )
            return {"status": "ok", "reason": "news_feedback_reset"}

        sections = current_sections if _needs_market_data(text) else {}

        news_feedback = supabase.get_news_feedback(target_phone)
        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(
            text,
            history=anthropic_history,
            user_name=authorized.get("name"),
            sections=sections,
            news_feedback=news_feedback,
        )
        supabase.save_message(target_phone, "assistant", reply)

        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
```

- [ ] **Step 5: Rodar todos os testes do webhook de feedback**

```
pytest backend/tests/test_webhook_news_feedback.py -v
```

Esperado: 6 testes PASS

- [ ] **Step 6: Atualizar `test_webhook_prefs.py` para incluir os novos patches**

Após a mudança no webhook, dois novos mocks são necessários em **todos os testes que passam pelo fluxo de mensagem normal** em `test_webhook_prefs.py`:
- `patch("backend.api.main._detect_news_feedback", return_value={"intent": "message"})`
- `patch("backend.api.main.supabase.get_news_feedback", return_value=[])`

O teste `test_webhook_mensagem_normal_nao_salva_preferencias` precisa ser atualizado para:

```python
def test_webhook_mensagem_normal_nao_salva_preferencias():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._detect_preference_intent",
               return_value={"intent": "message"}), \
         patch("backend.api.main._detect_news_feedback",
               return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_news_feedback", return_value=[]), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message"), \
         patch("backend.api.main.supabase.save_preferences") as mock_save:
        resp = client.post("/api/webhook", json=_make_webhook("qual é o dólar hoje?"))
    assert resp.status_code == 200
    mock_save.assert_not_called()
```

Após atualizar, rodar:

```
pytest backend/tests/test_webhook_prefs.py -v
```

Esperado: todos PASS

- [ ] **Step 7: Commit**

```
git add backend/api/main.py backend/tests/test_webhook_news_feedback.py
git commit -m "feat: add news feedback detection and webhook flow"
```

---

## Task 5: `cron_report.py` — Passar `news_feedback` no relatório diário

**Files:**
- Modify: `backend/api/cron_report.py`
- Modify: `backend/tests/test_cron_report.py`

- [ ] **Step 1: Adicionar teste falho em `test_cron_report.py`**

Adicionar ao final de `backend/tests/test_cron_report.py`:

```python
def test_cron_report_passa_news_feedback_para_reporter():
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.supabase.get_news_feedback", return_value=feedback), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório") as mock_gen, \
         patch("backend.api.cron_report.whatsapp.send_message"):
        resp = client.get("/api/cron/report", headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs.get("news_feedback") == feedback
```

- [ ] **Step 2: Atualizar o teste existente `test_cron_report_envia_para_usuarios_do_horario`**

O teste atual falhará porque o cron agora chama `supabase.get_news_feedback` antes de `generate_report`. Adicionar o patch no teste existente:

```python
def test_cron_report_envia_para_usuarios_do_horario():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.supabase.get_news_feedback", return_value=[]), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório"), \
         patch("backend.api.cron_report.whatsapp.send_message") as mock_send:
        resp = client.get("/api/cron/report",
                          headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1
    mock_send.assert_called_once_with("5534999301855", "relatório")
```

- [ ] **Step 3: Rodar para confirmar falha**

```
pytest backend/tests/test_cron_report.py -v
```

Esperado: `test_cron_report_passa_news_feedback_para_reporter` FAIL e `test_cron_report_envia_para_usuarios_do_horario` possivelmente FAIL por falta do mock `get_news_feedback`.

- [ ] **Step 4: Implementar em `cron_report.py`**

Substituir o loop `for user in users:` por:

```python
    for user in users:
        try:
            feedback = supabase.get_news_feedback(user["phone"])
            text = reporter.generate_report(
                "Gere o relatório diário.",
                sections=user.get("sections"),
                user_name=user.get("name"),
                news_feedback=feedback,
            )
            whatsapp.send_message(user["phone"], text)
            sent += 1
        except Exception:
            logger.exception("cron_report failed for %s", user["phone"])
```

- [ ] **Step 5: Rodar todos os testes do cron**

```
pytest backend/tests/test_cron_report.py -v
```

Esperado: 4 testes PASS

- [ ] **Step 6: Rodar a suite completa para garantir nenhuma regressão**

```
pytest backend/tests/ -v
```

Esperado: todos os testes PASS

- [ ] **Step 7: Commit final**

```
git add backend/api/cron_report.py backend/tests/test_cron_report.py
git commit -m "feat: pass news_feedback to cron daily report"
```

---

## Checklist Final

- [ ] Tabela `news_feedback` existe no Supabase com índice em `phone`
- [ ] `supabase.save_news_feedback / get_news_feedback / delete_news_feedback` funcionam (integração real)
- [ ] `reporter.generate_report` injeta preferências apenas no `_SYSTEM_MARKET` (não no `_SYSTEM_CHAT`)
- [ ] Webhook detecta feedback → salva → responde com confirmação gerada pelo Claude
- [ ] Webhook detecta reset → apaga tudo → responde com texto fixo
- [ ] Falha em `save_news_feedback` não bloqueia a resposta ao usuário
- [ ] Cron passa `news_feedback` no `generate_report` de cada usuário
- [ ] `pytest backend/tests/ -v` → 100% PASS
