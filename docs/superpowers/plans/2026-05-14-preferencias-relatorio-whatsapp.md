# Preferências de Relatório por Usuário — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que cada usuário customize via WhatsApp quais seções receber e em qual horário, com o agente endereçando cada pessoa pelo nome.

**Architecture:** O n8n continua gerando e disparando os relatórios nos horários existentes, mas redireciona o envio para `/api/send-report` no Vercel (em vez de chamar a Evolution API diretamente). Esse endpoint consulta preferências no Supabase e decide se envia o texto do n8n, re-gera com seções filtradas, ou pula (quando o usuário tem horário customizado e o Vercel Cron cuida do envio). A detecção de preferência usa Claude Haiku no webhook existente.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK (`claude-haiku-4-5-20251001` para detecção de intent, `claude-sonnet-4-6` para geração), Supabase REST API, Evolution API v1.8.2, Vercel Cron.

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `backend/services/supabase.py` | Modificar | Adicionar CRUD de `user_preferences` |
| `backend/services/reporter.py` | Modificar | Aceitar parâmetro `sections` |
| `backend/api/send_report.py` | Criar | Endpoint `/api/send-report` |
| `backend/api/cron_report.py` | Criar | Endpoint `/api/cron/report` |
| `backend/api/main.py` | Modificar | Detecção de preferência + registrar routers |
| `scripts/seed_users.py` | Criar | Seed inicial dos 4 usuários |
| `vercel.json` | Modificar | Adicionar cron |
| `backend/tests/test_send_report.py` | Criar | Testes do endpoint send-report |
| `backend/tests/test_cron_report.py` | Criar | Testes do cron |
| `backend/tests/test_preferences.py` | Criar | Testes do CRUD de preferências |

---

## Constantes Compartilhadas

As seções disponíveis são referenciadas em múltiplos arquivos. Adicionar em `reporter.py`:

```python
ALL_SECTIONS = ["market", "crypto", "indicators_us", "indicators_br", "news", "commodities_br", "politics_br", "polls_br"]
DEFAULT_SECTIONS = {s: True for s in ALL_SECTIONS}
```

---

## Task 1: Supabase — tabela `user_preferences` + funções CRUD

**Files:**
- Modify: `backend/services/supabase.py`
- Create: `backend/tests/test_preferences.py`

- [ ] **Step 1: Criar tabela no Supabase**

Rodar o SQL abaixo no SQL Editor do Supabase dashboard (ou via MCP `execute_sql`):

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
  phone       TEXT PRIMARY KEY,
  sections    JSONB,
  report_time TEXT,
  updated_at  TIMESTAMPTZ DEFAULT now()
);
```

- [ ] **Step 2: Escrever os testes**

Criar `backend/tests/test_preferences.py`:

```python
import pytest
import os
from backend.services import supabase

PHONE_TEST = "5500000000000"


def teardown_function():
    supabase.delete_preferences(PHONE_TEST)


def test_get_preferences_inexistente():
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None


def test_save_and_get_preferences_sections():
    sections = {"market": True, "crypto": False, "indicators_us": True, "indicators_br": True,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    supabase.save_preferences(PHONE_TEST, sections=sections, report_time=None)
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs is not None
    assert prefs["sections"]["crypto"] is False
    assert prefs["sections"]["market"] is True
    assert prefs["report_time"] is None


def test_save_and_get_preferences_horario():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs["report_time"] == "08:00"
    assert prefs["sections"] is None


def test_save_preferences_upsert():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="19:00")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs["report_time"] == "19:00"


def test_delete_preferences():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None


def test_get_users_for_hour_retorna_usuario_com_horario():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    users = supabase.get_users_for_hour("08:00")
    phones = [u["phone"] for u in users]
    assert PHONE_TEST in phones


def test_get_users_for_hour_nao_retorna_outros_horarios():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    users = supabase.get_users_for_hour("19:00")
    phones = [u["phone"] for u in users]
    assert PHONE_TEST not in phones
```

- [ ] **Step 3: Rodar testes — confirmar falha**

```bash
pytest backend/tests/test_preferences.py -v
```

Esperado: `AttributeError: module 'backend.services.supabase' has no attribute 'get_preferences'`

- [ ] **Step 4: Implementar as funções em `supabase.py`**

Adicionar ao final de `backend/services/supabase.py`:

```python
def get_preferences(phone: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/user_preferences?phone=eq.{phone}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def save_preferences(phone: str, sections: dict | None, report_time: str | None) -> None:
    with _client() as c:
        r = c.post(
            "/user_preferences",
            json={"phone": phone, "sections": sections, "report_time": report_time},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def delete_preferences(phone: str) -> None:
    with _client() as c:
        r = c.delete(f"/user_preferences?phone=eq.{phone}")
        r.raise_for_status()


def get_users_for_hour(hour_brt: str) -> list[dict]:
    with _client() as c:
        r = c.get(f"/user_preferences?report_time=eq.{hour_brt}&select=phone,sections")
        r.raise_for_status()
        prefs = r.json()
    result = []
    for p in prefs:
        user = get_authorized_by_phone(p["phone"])
        result.append({
            "phone": p["phone"],
            "name": user.get("name") if user else None,
            "sections": p.get("sections"),
        })
    return result
```

- [ ] **Step 5: Rodar testes — confirmar aprovação**

```bash
pytest backend/tests/test_preferences.py -v
```

Esperado: todos os testes PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/supabase.py backend/tests/test_preferences.py
git commit -m "feat: add user_preferences CRUD to supabase service"
```

---

## Task 2: `reporter.py` — parâmetro `sections`

**Files:**
- Modify: `backend/services/reporter.py`

- [ ] **Step 1: Escrever teste**

Adicionar em `backend/tests/test_reporter_sections.py`:

```python
from unittest.mock import patch, MagicMock
from backend.services import reporter


def _mock_anthropic(text="relatório de teste"):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_collect_all_sem_sections_retorna_todas():
    with patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, ius, ibr, n, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        result = reporter._collect_all(sections=None)
    assert set(result.keys()) == {"market", "crypto", "indicators_us", "indicators_br",
                                   "news", "commodities_br", "politics_br", "polls_br"}


def test_collect_all_com_sections_filtra_coletores():
    sections = {"market": True, "crypto": False, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.news") as n:
        m.collect.return_value = {"ok": True}
        n.collect.return_value = {"ok": True}
        result = reporter._collect_all(sections=sections)
    assert "market" in result
    assert "news" in result
    assert "crypto" not in result
    assert "politics_br" not in result


def test_generate_report_passa_sections():
    sections = {"market": True, "crypto": True, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
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
            mod.collect.return_value = {}
        MockA.return_value = _mock_anthropic()
        result = reporter.generate_report("teste", sections=sections)
    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: Rodar testes — confirmar falha**

```bash
pytest backend/tests/test_reporter_sections.py -v
```

Esperado: `TypeError` ou `ImportError` pois `commodities_br`, `politics_br`, `polls_br` não são importados e `sections` não existe.

- [ ] **Step 3: Atualizar `reporter.py`**

Substituir o conteúdo de `backend/services/reporter.py`:

```python
import os
import json
from anthropic import Anthropic

from backend.collectors import (
    market, crypto, indicators_us, indicators_br, news,
    commodities_br, politics_br, polls_br,
)

ALL_SECTIONS = [
    "market", "crypto", "indicators_us", "indicators_br",
    "news", "commodities_br", "politics_br", "polls_br",
]
DEFAULT_SECTIONS = {s: True for s in ALL_SECTIONS}

SYSTEM_PROMPT = """Você é um analista financeiro brasileiro especialista em mercados, indicadores macroeconômicos e geopolítica.

Você recebe dados estruturados (JSON) com cotações de bolsas, câmbio, criptomoedas, indicadores econômicos (BR/EUA) e notícias. Sua tarefa é gerar um resumo claro, conciso e acionável em português, formatado para WhatsApp (use *negrito*, _itálico_, emojis com moderação, sem markdown de código).

Regras:
- Comece com um resumo de 1-2 linhas do dia
- Destaque variações relevantes (>1%) em bolsas, câmbio e cripto
- Mencione indicadores econômicos novos
- Cite as 2-3 notícias mais relevantes
- Termine com uma análise breve do cenário
- Máximo 1500 caracteres
- Se o usuário fizer pergunta específica, responda diretamente sem o formato de resumo"""


def _safe_collect(fn):
    try:
        return fn()
    except Exception as e:
        return {"erro": str(e)}


_COLLECTORS = {
    "market": lambda: market.collect(),
    "crypto": lambda: crypto.collect(),
    "indicators_us": lambda: indicators_us.collect(),
    "indicators_br": lambda: indicators_br.collect(),
    "news": lambda: news.collect(),
    "commodities_br": lambda: commodities_br.collect(),
    "politics_br": lambda: politics_br.collect(),
    "polls_br": lambda: polls_br.collect(),
}


def _collect_all(sections: dict | None = None) -> dict:
    active = sections or DEFAULT_SECTIONS
    return {
        k: _safe_collect(fn)
        for k, fn in _COLLECTORS.items()
        if active.get(k, False)
    }


def generate_report(
    user_message: str,
    history: list[dict] | None = None,
    user_name: str | None = None,
    sections: dict | None = None,
) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    data = _collect_all(sections=sections)

    system = SYSTEM_PROMPT
    if user_name:
        primeiro_nome = user_name.split()[0]
        system += (
            f"\n\nVocê está conversando com {user_name}. Trate por *{primeiro_nome}* "
            f"(primeiro nome). Use o nome de forma natural — em saudações, ao começar "
            f"respostas longas, ou quando quiser dar um tom pessoal — mas sem exagerar "
            f"(não em toda frase)."
        )

    user_content = (
        f"Mensagem do usuário: {user_message}\n\n"
        f"Dados de mercado coletados agora:\n{json.dumps(data, ensure_ascii=False, default=str)}"
    )

    messages = list(history or [])
    messages.append({"role": "user", "content": user_content})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=messages,
    )

    return response.content[0].text
```

- [ ] **Step 4: Rodar testes — confirmar aprovação**

```bash
pytest backend/tests/test_reporter_sections.py -v
```

Esperado: todos PASS.

- [ ] **Step 5: Garantir que testes anteriores continuam passando**

```bash
pytest backend/tests/ -v
```

Esperado: nenhum teste regressivo.

- [ ] **Step 6: Commit**

```bash
git add backend/services/reporter.py backend/tests/test_reporter_sections.py
git commit -m "feat: add sections filtering to reporter collect_all"
```

---

## Task 3: Seed dos usuários

**Files:**
- Create: `scripts/seed_users.py`

- [ ] **Step 1: Criar o script**

Criar `scripts/seed_users.py`:

```python
#!/usr/bin/env python3
"""Seed inicial dos usuários autorizados. Rodar uma vez."""
import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

USERS = [
    {"phone": "5534999945010", "name": "Matheus",  "lid": "5534999945010"},
    {"phone": "5534999301855", "name": "Ricardim", "lid": "5534999301855"},
    {"phone": "5534996568291", "name": "Cassiano", "lid": "5534996568291"},
    {"phone": "5534988162802", "name": "Jorge",    "lid": "5534988162802"},
]


def seed():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    with httpx.Client(base_url=f"{url}/rest/v1", headers=headers, timeout=15) as c:
        for user in USERS:
            r = c.post("/authorized_users", json=user)
            r.raise_for_status()
            print(f"✓ {user['name']} ({user['phone']})")
    print(f"\nSeed completo: {len(USERS)} usuários inseridos/atualizados.")


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: Rodar o script**

```bash
python scripts/seed_users.py
```

Esperado:
```
✓ Matheus (5534999945010)
✓ Ricardim (5534999301855)
✓ Cassiano (5534996568291)
✓ Jorge (5534988162802)

Seed completo: 4 usuários inseridos/atualizados.
```

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_users.py
git commit -m "feat: add seed script for initial authorized users"
```

---

## Task 4: Endpoint `/api/send-report`

**Files:**
- Create: `backend/api/send_report.py`
- Create: `backend/tests/test_send_report.py`

- [ ] **Step 1: Escrever os testes**

Criar `backend/tests/test_send_report.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

PAYLOAD_DEFAULT = {
    "number": "5534999945010",
    "textMessage": {"text": "Relatório do n8n aqui."}
}


def _mock_prefs(sections=None, report_time=None):
    if sections is None and report_time is None:
        return None
    return {"phone": "5534999945010", "sections": sections, "report_time": report_time}


def test_send_report_sem_preferencias_envia_texto_n8n():
    with patch("backend.api.send_report.supabase.get_preferences", return_value=None), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_send.assert_called_once()
    args = mock_send.call_args[0]
    assert "Matheus" in args[1]


def test_send_report_com_horario_customizado_pula():
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"phone": "5534999945010", "sections": None, "report_time": "08:00"}):
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


def test_send_report_com_sections_gera_novo_relatorio():
    sections = {"market": True, "crypto": False, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"phone": "5534999945010", "sections": sections, "report_time": None}), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.reporter.generate_report",
               return_value="relatório filtrado") as mock_gen, \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    mock_gen.assert_called_once_with(
        "Gere o relatório diário.",
        sections=sections,
        user_name="Matheus",
    )
    mock_send.assert_called_once_with("5534999945010", "relatório filtrado")
```

- [ ] **Step 2: Rodar testes — confirmar falha**

```bash
pytest backend/tests/test_send_report.py -v
```

Esperado: `404 Not Found` pois o endpoint não existe.

- [ ] **Step 3: Criar `backend/api/send_report.py`**

```python
from fastapi import APIRouter
from pydantic import BaseModel

from backend.services import reporter, whatsapp, supabase

router = APIRouter()


class TextMessage(BaseModel):
    text: str


class SendReportPayload(BaseModel):
    number: str
    textMessage: TextMessage


@router.post("/api/send-report")
async def send_report(payload: SendReportPayload):
    number = payload.number
    n8n_text = payload.textMessage.text

    prefs = supabase.get_preferences(number)

    if prefs and prefs.get("report_time"):
        return {"status": "skipped", "reason": "custom_time"}

    user = supabase.get_authorized_by_phone(number)
    user_name = user.get("name") if user else None

    if prefs and prefs.get("sections"):
        text = reporter.generate_report(
            "Gere o relatório diário.",
            sections=prefs["sections"],
            user_name=user_name,
        )
    else:
        if user_name:
            primeiro_nome = user_name.split()[0]
            text = f"Bom dia, *{primeiro_nome}!* 👋\n\n{n8n_text}"
        else:
            text = n8n_text

    whatsapp.send_message(number, text)
    return {"status": "ok"}
```

- [ ] **Step 4: Registrar router em `main.py`**

Adicionar em `backend/api/main.py` após os outros `app.include_router`:

```python
from backend.api import send_report
# ...
app.include_router(send_report.router)
```

- [ ] **Step 5: Rodar testes — confirmar aprovação**

```bash
pytest backend/tests/test_send_report.py -v
```

Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/api/send_report.py backend/api/main.py backend/tests/test_send_report.py
git commit -m "feat: add /api/send-report endpoint with preferences support"
```

---

## Task 5: Endpoint `/api/cron/report` + `vercel.json`

**Files:**
- Create: `backend/api/cron_report.py`
- Create: `backend/tests/test_cron_report.py`
- Modify: `vercel.json`

- [ ] **Step 1: Escrever os testes**

Criar `backend/tests/test_cron_report.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

USERS_08 = [
    {"phone": "5534999301855", "name": "Ricardim", "sections": None},
]


def test_cron_report_sem_usuarios_retorna_ok():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=[]), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"):
        resp = client.get("/api/cron/report",
                          headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 0


def test_cron_report_envia_para_usuarios_do_horario():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório"), \
         patch("backend.api.cron_report.whatsapp.send_message") as mock_send:
        resp = client.get("/api/cron/report",
                          headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1
    mock_send.assert_called_once_with("5534999301855", "relatório")


def test_cron_report_sem_header_retorna_401():
    resp = client.get("/api/cron/report")
    assert resp.status_code == 401
```

- [ ] **Step 2: Rodar testes — confirmar falha**

```bash
pytest backend/tests/test_cron_report.py -v
```

Esperado: `404 Not Found`.

- [ ] **Step 3: Criar `backend/api/cron_report.py`**

```python
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException

from backend.services import reporter, whatsapp, supabase

router = APIRouter()


def _current_hour_brt() -> str:
    brt = timezone(timedelta(hours=-3))
    now = datetime.now(brt)
    return f"{now.hour:02d}:00"


@router.get("/api/cron/report")
async def cron_report(request: Request):
    if not request.headers.get("x-vercel-cron"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    hour = _current_hour_brt()
    users = supabase.get_users_for_hour(hour)

    for user in users:
        text = reporter.generate_report(
            "Gere o relatório diário.",
            sections=user.get("sections"),
            user_name=user.get("name"),
        )
        whatsapp.send_message(user["phone"], text)

    return {"status": "ok", "hour": hour, "sent": len(users)}
```

- [ ] **Step 4: Registrar router em `main.py`**

Adicionar em `backend/api/main.py`:

```python
from backend.api import cron_report
# ...
app.include_router(cron_report.router)
```

- [ ] **Step 5: Atualizar `vercel.json`**

Substituir o conteúdo de `vercel.json`:

```json
{
  "builds": [
    {
      "src": "backend/api/main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "backend/api/main.py"
    }
  ],
  "crons": [
    {
      "path": "/api/cron/report",
      "schedule": "0 * * * *"
    }
  ]
}
```

- [ ] **Step 6: Rodar testes — confirmar aprovação**

```bash
pytest backend/tests/test_cron_report.py -v
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/api/cron_report.py backend/api/main.py backend/tests/test_cron_report.py vercel.json
git commit -m "feat: add /api/cron/report endpoint and vercel cron schedule"
```

---

## Task 6: Detecção de preferência no webhook (`main.py`)

**Files:**
- Modify: `backend/api/main.py`
- Create: `backend/tests/test_webhook_prefs.py`

- [ ] **Step 1: Escrever os testes**

Criar `backend/tests/test_webhook_prefs.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

WEBHOOK_BASE = {
    "data": {
        "key": {"fromMe": False, "remoteJid": "553499930185@lid"},
        "pushName": "Ricardim",
        "message": {"conversation": "quero só notícias e crypto"}
    }
}

AUTHORIZED = {"lid": "553499930185@lid", "phone": "5534999301855", "name": "Ricardim"}


def _make_webhook(text):
    payload = dict(WEBHOOK_BASE)
    payload["data"] = dict(WEBHOOK_BASE["data"])
    payload["data"]["message"] = {"conversation": text}
    return payload


def test_webhook_mensagem_normal_nao_salva_preferencias():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._detect_preference_intent",
               return_value={"intent": "message"}), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message"), \
         patch("backend.api.main.supabase.save_preferences") as mock_save:
        resp = client.post("/api/webhook", json=_make_webhook("qual é o dólar hoje?"))
    assert resp.status_code == 200
    mock_save.assert_not_called()


def test_webhook_preferencia_salva_e_responde():
    intent_result = {
        "intent": "preference",
        "sections": {"market": False, "crypto": True, "indicators_us": False,
                     "indicators_br": False, "news": True, "commodities_br": False,
                     "politics_br": False, "polls_br": False},
        "report_time": None,
        "reset": False,
        "reply": "Feito! Seu relatório vai incluir apenas notícias e criptomoedas."
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("quero só notícias e crypto"))
    assert resp.status_code == 200
    mock_save.assert_called_once()
    mock_send.assert_called_once_with("5534999301855",
                                      "Feito! Seu relatório vai incluir apenas notícias e criptomoedas.")


def test_webhook_reset_preferencias():
    intent_result = {
        "intent": "preference",
        "sections": None,
        "report_time": None,
        "reset": True,
        "reply": "Pronto! Você voltará a receber o relatório completo no horário padrão."
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.supabase.delete_preferences") as mock_delete, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_make_webhook("volta pro padrão"))
    assert resp.status_code == 200
    mock_delete.assert_called_once_with("5534999301855")
```

- [ ] **Step 2: Rodar testes — confirmar falha**

```bash
pytest backend/tests/test_webhook_prefs.py -v
```

Esperado: `AttributeError: module ... has no attribute '_detect_preference_intent'`

- [ ] **Step 3: Adicionar `_detect_preference_intent` em `main.py`**

Adicionar os imports necessários no topo de `backend/api/main.py`:

```python
import json
from anthropic import Anthropic
```

Adicionar a função após as demais funções auxiliares (antes do `@app.post("/api/webhook")`):

```python
_PREFERENCE_SYSTEM = """Você é um parser de intenções. Analise se a mensagem é um pedido de configuração do relatório financeiro diário.

Seções disponíveis:
- market: bolsas e câmbio
- crypto: criptomoedas
- indicators_us: indicadores econômicos dos EUA
- indicators_br: indicadores econômicos do Brasil
- news: notícias
- commodities_br: commodities brasileiras
- politics_br: política brasileira
- polls_br: pesquisas eleitorais

Se for um pedido de configuração, responda SOMENTE com JSON válido:
{
  "intent": "preference",
  "sections": {todas as 8 seções com true/false},
  "report_time": "HH:00" ou null,
  "reset": false,
  "reply": "mensagem de confirmação amigável em português"
}

Regras de seções:
- "quero só X e Y" → todas false exceto X e Y
- "remove X" → manter configuração atual, apenas X=false (retornar seções com base no contexto fornecido)
- "adiciona X" → manter configuração atual, apenas X=true

Regras de horário:
- "às 8h" → "08:00"
- "às 20h30" ou "8 e meia" → arredondar para próxima hora cheia

Reset:
- "volta pro padrão", "quero tudo de volta", "cancela preferências" → {"intent": "preference", "sections": null, "report_time": null, "reset": true, "reply": "..."}

Se NÃO for pedido de configuração, responda SOMENTE: {"intent": "message"}"""


def _detect_preference_intent(text: str, current_sections: dict | None = None) -> dict:
    context = ""
    if current_sections:
        context = f"\n\nConfiguração atual do usuário: {json.dumps(current_sections, ensure_ascii=False)}"
    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_PREFERENCE_SYSTEM,
            messages=[{"role": "user", "content": text + context}],
        )
        return json.loads(response.content[0].text)
    except Exception:
        return {"intent": "message"}
```

- [ ] **Step 4: Atualizar o handler do webhook em `main.py`**

No handler `whatsapp_webhook`, substituir o bloco após a verificação de admin command (onde busca histórico e gera resposta) para adicionar a detecção de preferência:

```python
        # Detectar intenção de preferência antes de gerar resposta
        current_prefs = supabase.get_preferences(target_phone)
        current_sections = (current_prefs or {}).get("sections")
        intent = _detect_preference_intent(text, current_sections=current_sections)

        if intent.get("intent") == "preference":
            if intent.get("reset"):
                supabase.delete_preferences(target_phone)
            else:
                new_sections = intent.get("sections")
                new_time = intent.get("report_time")
                if new_sections is not None or new_time is not None:
                    supabase.save_preferences(target_phone, sections=new_sections, report_time=new_time)
            reply = intent.get("reply", "Preferências atualizadas!")
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok", "reason": "preference_updated"}

        # Buscar histórico e gerar resposta
        history = supabase.get_history(target_phone, limit=10)
        anthropic_history = [{"role": h["role"], "content": h["content"]} for h in history]

        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"))
        supabase.save_message(target_phone, "assistant", reply)

        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
```

O bloco substitui exatamente o trecho a partir de `# Buscar histórico e gerar resposta` até o `return {"status": "ok"}` final.

- [ ] **Step 5: Rodar testes — confirmar aprovação**

```bash
pytest backend/tests/test_webhook_prefs.py -v
```

Esperado: todos PASS.

- [ ] **Step 6: Rodar suite completa**

```bash
pytest backend/tests/ -v
```

Esperado: nenhum teste regressivo.

- [ ] **Step 7: Commit**

```bash
git add backend/api/main.py backend/tests/test_webhook_prefs.py
git commit -m "feat: add preference intent detection to WhatsApp webhook"
```

---

## Task 7: Verificação final e deploy

- [ ] **Step 1: Rodar todos os testes**

```bash
pytest backend/tests/ -v
```

Esperado: todos PASS.

- [ ] **Step 2: Confirmar routers registrados em `main.py`**

Verificar que `main.py` contém:

```python
from backend.api import send_report, cron_report
# ...
app.include_router(send_report.router)
app.include_router(cron_report.router)
```

- [ ] **Step 3: Deploy para Vercel**

```bash
vercel --prod
```

- [ ] **Step 4: Atualizar n8n manualmente**

Em cada workflow no n8n dashboard, nos nós "Enviar WhatsApp", alterar o campo `url` de:
```
http://46.202.179.33:8080/message/sendText/noticiasgg
```
para:
```
https://noticiasgg.vercel.app/api/send-report
```

Workflows afetados: `Relatório 12h`, `Relatório 12h v2`, `Commodities`.

- [ ] **Step 5: Testar endpoint `/api/send-report` em produção**

```bash
curl -X POST https://noticiasgg.vercel.app/api/send-report \
  -H "Content-Type: application/json" \
  -d '{"number": "5534999945010", "textMessage": {"text": "Teste de relatório manual."}}'
```

Esperado: `{"status": "ok"}` e mensagem chegando no WhatsApp com "Bom dia, Matheus! 👋".

- [ ] **Step 6: Commit final**

```bash
git add .
git commit -m "chore: final wiring — send-report and cron-report routers registered"
```
