import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)
_SECRET = "test-cron-secret"


@pytest.mark.unit
def test_check_alerts_accepts_bearer():
    with patch("backend.services.alert_checker.run_checks", return_value={"status": "ok"}), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts", headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 200


@pytest.mark.unit
def test_check_alerts_accepts_x_cron_secret():
    with patch("backend.services.alert_checker.run_checks", return_value={"status": "ok"}), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200


@pytest.mark.unit
def test_check_alerts_rejects_missing_secret():
    with patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts")
    assert r.status_code == 401
