import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.api import main
from backend.services import soja_digest, alert_checker, whatsapp

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def _client():
    return TestClient(main.app)


def test_cron_soja_requires_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    r = _client().get("/api/cron/soja")
    assert r.status_code == 401


def test_cron_soja_runs_with_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(soja_digest, "run",
                        lambda test_mode=False: {"status": "ok", "sent": 0})
    r = _client().get("/api/cron/soja", headers={"x-cron-secret": "s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cron_soja_test_query_param_sets_test_mode(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    captured = {}

    def fake_run(test_mode=False):
        captured["test_mode"] = test_mode
        return {"status": "ok", "sent": 0}

    monkeypatch.setattr(soja_digest, "run", fake_run)
    r = _client().get("/api/cron/soja?test=true", headers={"x-cron-secret": "s3cr3t"})
    assert r.status_code == 200
    assert captured["test_mode"] is True


def test_cron_soja_exception_returns_error_and_warns_admin_directly(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    def boom(test_mode=False):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(soja_digest, "run", boom)
    sent = []
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: sent.append((number, text)))
    notified = []
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))

    r = _client().get("/api/cron/soja", headers={"x-cron-secret": "s3cr3t"})

    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert notified == []  # cron_soja não usa notify_admin (cooldown compartilhado)
    assert len(sent) == 1
    admin_number, texto = sent[0]
    assert admin_number == "5534999945010"
    assert "cron soja com falha" in texto
    assert "kaboom" in texto


def test_cron_soja_exception_detail_masks_api_key(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.delenv("REPLY_TO_NUMBER", raising=False)
    monkeypatch.delenv("AUTHORIZED_NUMBER", raising=False)

    def boom(test_mode=False):
        raise RuntimeError("erro ao chamar https://api.scraperapi.com/?api_key=SEGREDO123&url=x")

    monkeypatch.setattr(soja_digest, "run", boom)

    r = _client().get("/api/cron/soja", headers={"x-cron-secret": "s3cr3t"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "SEGREDO123" not in body["detail"]
    assert "api_key=***" in body["detail"]


# ---------------------------------------------------------------------------
# vercel.json declara o cron
# ---------------------------------------------------------------------------

VERCEL_JSON = Path(__file__).resolve().parent.parent.parent / "vercel.json"


def test_vercel_json_has_soja_cron():
    data = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))
    paths = [c["path"] for c in data["crons"]]
    assert "/api/cron/soja" in paths
