# LID Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o webhook responder pelo mesmo JID que chegou (`remote_jid`), corrigir a mensagem de boas-vindas na autorização para usar `pending["lid"]`, e notificar o usuário não autorizado que seu pedido foi enviado ao admin.

**Architecture:** Mudança cirúrgica em `backend/api/main.py` apenas. Três sítios: (1) introduzir `target_jid = remote_jid` e trocar os dois `send_message(target_phone, ...)` no bloco de usuário autorizado; (2) adicionar `send_message(remote_jid, ...)` no bloco de usuário não autorizado com try/except; (3) trocar `send_message(phone, ...)` por `send_message(pending["lid"], ...)` em `_handle_admin_command`. `whatsapp.py` não precisa de mudança — já aceita JID.

**Tech Stack:** Python 3.12, FastAPI, pytest, unittest.mock

---

## Estrutura de arquivos

| Arquivo | Ação |
|---|---|
| `backend/api/main.py` | Modificar — 3 sítios descritos acima |
| `backend/tests/test_webhook_lid.py` | Criar — testes unitários das 3 mudanças |
| `backend/tests/test_webhook_prefs.py` | Modificar — corrigir asserção de `send_message` na linha 56 |

---

## Task 1: `target_jid` — respostas a usuários autorizados usam remote_jid

**Files:**
- Create: `backend/tests/test_webhook_lid.py`
- Modify: `backend/api/main.py:199-235`
- Modify: `backend/tests/test_webhook_prefs.py:56`

- [ ] **Step 1: Criar arquivo de teste e escrever testes que falham**

```python
# backend/tests/test_webhook_lid.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

_REMOTE_JID = "139247134720249@lid"
_USER_PHONE = "5534999301855"
_AUTHORIZED = {"lid": _REMOTE_JID, "phone": _USER_PHONE, "name": "Ricardim"}


def _payload(remote_jid=_REMOTE_JID, text="olá"):
    return {
        "data": {
            "key": {"fromMe": False, "remoteJid": remote_jid},
            "pushName": "Teste",
            "message": {"conversation": text},
        }
    }


def test_resposta_normal_usa_remote_jid():
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_REMOTE_JID, "resposta")


def test_confirmacao_preferencia_usa_remote_jid():
    intent = {
        "intent": "preference",
        "sections": None,
        "report_time": None,
        "reset": False,
        "reply": "Feito!",
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload(text="quero só crypto"))
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_REMOTE_JID, "Feito!")
```

- [ ] **Step 2: Rodar testes para confirmar que falham**

```
pytest backend/tests/test_webhook_lid.py -v
```

Esperado: FAIL — `send_message` é chamado com `"5534999301855"` em vez de `"139247134720249@lid"`.

- [ ] **Step 3: Implementar `target_jid` em `main.py`**

Em `backend/api/main.py`, após a linha `target_phone = authorized["phone"]` (linha 199), adicionar:

```python
target_jid = remote_jid
```

Depois trocar as duas chamadas de `send_message` que usam `target_phone` no bloco de usuário autorizado.

Linha 222 — de:
```python
whatsapp.send_message(target_phone, reply)
```
Para:
```python
whatsapp.send_message(target_jid, reply)
```

Linha 235 — de:
```python
whatsapp.send_message(target_phone, reply)
```
Para:
```python
whatsapp.send_message(target_jid, reply)
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```
pytest backend/tests/test_webhook_lid.py::test_resposta_normal_usa_remote_jid backend/tests/test_webhook_lid.py::test_confirmacao_preferencia_usa_remote_jid -v
```

Esperado: PASS.

- [ ] **Step 5: Corrigir teste quebrado em `test_webhook_prefs.py`**

Em `backend/tests/test_webhook_prefs.py`, `test_webhook_preferencia_salva_e_responde` (linha 56):

De:
```python
    mock_send.assert_called_once_with(
        "5534999301855",
        "Feito! Seu relatório vai incluir apenas notícias e criptomoedas."
    )
```

Para:
```python
    mock_send.assert_called_once_with(
        "553499930185@lid",
        "Feito! Seu relatório vai incluir apenas notícias e criptomoedas."
    )
```

(O `remote_jid` no `_make_webhook` desse teste é `"553499930185@lid"`.)

- [ ] **Step 6: Rodar todos os testes para confirmar sem regressões**

```
pytest backend/tests/test_webhook_prefs.py backend/tests/test_webhook_lid.py -v
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_webhook_lid.py backend/api/main.py backend/tests/test_webhook_prefs.py
git commit -m "fix: webhook replies use remote_jid instead of phone number"
```

---

## Task 2: Notificar usuário não autorizado

**Files:**
- Modify: `backend/tests/test_webhook_lid.py`
- Modify: `backend/api/main.py:189-197`

- [ ] **Step 1: Adicionar testes que falham**

No final de `backend/tests/test_webhook_lid.py`, adicionar:

```python
def test_usuario_nao_autorizado_recebe_confirmacao():
    with patch("backend.api.main.supabase.get_authorized", return_value=None), \
         patch("backend.api.main.supabase.upsert_pending"), \
         patch("backend.api.main._admin_phone", return_value="5534999945010"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["reason"] == "pending auth"
    calls = [c.args[0] for c in mock_send.call_args_list]
    assert _REMOTE_JID in calls


def test_usuario_nao_autorizado_confirmacao_falha_silenciosa():
    def raise_on_user_jid(number, text):
        if number == _REMOTE_JID:
            raise Exception("connection error")

    with patch("backend.api.main.supabase.get_authorized", return_value=None), \
         patch("backend.api.main.supabase.upsert_pending"), \
         patch("backend.api.main._admin_phone", return_value="5534999945010"), \
         patch("backend.api.main.whatsapp.send_message", side_effect=raise_on_user_jid):
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["reason"] == "pending auth"
```

- [ ] **Step 2: Rodar testes para confirmar que falham**

```
pytest backend/tests/test_webhook_lid.py::test_usuario_nao_autorizado_recebe_confirmacao backend/tests/test_webhook_lid.py::test_usuario_nao_autorizado_confirmacao_falha_silenciosa -v
```

Esperado: FAIL — nenhuma chamada a `send_message` com `_REMOTE_JID`; segunda falha com `AssertionError` ou exception.

- [ ] **Step 3: Implementar notificação ao usuário não autorizado**

Em `backend/api/main.py`, no bloco `if not authorized:` (logo após a notificação ao admin, antes do `return`):

De:
```python
        if not authorized:
            # Não autorizado → cria pendência e notifica admin
            supabase.upsert_pending(remote_jid, push_name, text)
            if admin_phone:
                whatsapp.send_message(
                    admin_phone,
                    f"Novo pedido de acesso:\n\n*{push_name}* mandou: \"{text}\"\n\nResponda com o número da pessoa (ex: 5534999999999) para autorizar.",
                )
            return {"status": "ok", "reason": "pending auth"}
```

Para:
```python
        if not authorized:
            # Não autorizado → cria pendência e notifica admin
            supabase.upsert_pending(remote_jid, push_name, text)
            if admin_phone:
                whatsapp.send_message(
                    admin_phone,
                    f"Novo pedido de acesso:\n\n*{push_name}* mandou: \"{text}\"\n\nResponda com o número da pessoa (ex: 5534999999999) para autorizar.",
                )
            try:
                whatsapp.send_message(
                    remote_jid,
                    "Vou enviar uma mensagem para o admin liberar o seu acesso, só um momento! 🙏",
                )
            except Exception:
                logger.warning("failed to notify pending user %s", remote_jid)
            return {"status": "ok", "reason": "pending auth"}
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```
pytest backend/tests/test_webhook_lid.py::test_usuario_nao_autorizado_recebe_confirmacao backend/tests/test_webhook_lid.py::test_usuario_nao_autorizado_confirmacao_falha_silenciosa -v
```

Esperado: PASS.

- [ ] **Step 5: Rodar suite completa para confirmar sem regressões**

```
pytest backend/tests/test_webhook_prefs.py backend/tests/test_webhook_lid.py -v
```

Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_webhook_lid.py backend/api/main.py
git commit -m "feat: notify unauthorized user that access request was sent to admin"
```

---

## Task 3: Mensagem de boas-vindas usa `pending["lid"]`

**Files:**
- Modify: `backend/tests/test_webhook_lid.py`
- Modify: `backend/api/main.py:117`

- [ ] **Step 1: Adicionar teste que falha**

No final de `backend/tests/test_webhook_lid.py`, adicionar:

```python
def test_autorizacao_envia_boas_vindas_pelo_lid():
    _ADMIN_PHONE = "5534999945010"
    admin_jid = "999000111@lid"
    admin_authorized = {"lid": admin_jid, "phone": _ADMIN_PHONE, "name": "Matheus"}
    new_user_lid = "555888777@lid"
    pending_user = {"lid": new_user_lid, "push_name": "Ricardim", "last_message": "oi"}

    with patch("backend.api.main.supabase.get_authorized", return_value=admin_authorized), \
         patch("backend.api.main._admin_phone", return_value=_ADMIN_PHONE), \
         patch("backend.api.main.supabase.pop_oldest_pending", return_value=pending_user), \
         patch("backend.api.main.supabase.add_authorized"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload(remote_jid=admin_jid, text="5534999301855"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "admin command"
    calls = [c.args[0] for c in mock_send.call_args_list]
    assert new_user_lid in calls
    assert _USER_PHONE not in calls
```

- [ ] **Step 2: Rodar teste para confirmar que falha**

```
pytest backend/tests/test_webhook_lid.py::test_autorizacao_envia_boas_vindas_pelo_lid -v
```

Esperado: FAIL — `send_message` é chamado com `"5534999301855"` (o telefone), não com `"555888777@lid"` (o LID).

- [ ] **Step 3: Corrigir `_handle_admin_command` em `main.py`**

Em `backend/api/main.py`, função `_handle_admin_command`, linha 117:

De:
```python
        whatsapp.send_message(phone, "Olá! Você foi autorizado a conversar com o agente Notícias GG. Pode mandar suas perguntas sobre mercado, cotações e notícias financeiras.")
```

Para:
```python
        whatsapp.send_message(pending["lid"], "Olá! Você foi autorizado a conversar com o agente Notícias GG. Pode mandar suas perguntas sobre mercado, cotações e notícias financeiras.")
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```
pytest backend/tests/test_webhook_lid.py -v
```

Esperado: todos PASS.

- [ ] **Step 5: Rodar suite completa**

```
pytest backend/tests/ -v
```

Esperado: todos PASS (sem regressões).

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_webhook_lid.py backend/api/main.py
git commit -m "fix: send welcome message to new user via their LID, not phone number"
```
