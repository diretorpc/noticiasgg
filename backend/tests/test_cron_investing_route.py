from fastapi.testclient import TestClient

from backend.api import main
from backend.services import investing_digest, alert_checker
import pytest

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def _client():
    return TestClient(main.app)


def test_cron_investing_requires_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    r = _client().get("/api/cron/investing")
    assert r.status_code == 401


def test_cron_investing_runs_with_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(investing_digest, "run",
                        lambda test_mode=False: {"status": "ok", "events": 0, "sent": 0})
    r = _client().get("/api/cron/investing", headers={"x-cron-secret": "s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cron_investing_exception_detail_masks_api_key(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(alert_checker, "notify_admin", lambda *a, **k: None)

    def boom(test_mode=False):
        raise RuntimeError("erro ao chamar https://api.scraperapi.com/?api_key=SEGREDO123&url=x")

    monkeypatch.setattr(investing_digest, "run", boom)

    r = _client().get("/api/cron/investing", headers={"x-cron-secret": "s3cr3t"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "SEGREDO123" not in body["detail"]
    assert "api_key=***" in body["detail"]
