from fastapi.testclient import TestClient

from backend.api import main
from backend.services import investing_digest


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
