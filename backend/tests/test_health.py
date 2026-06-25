import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.services import health

_KEYS_OK = {"status": "ok", "faltando": []}


def test_collect_status_tudo_ok():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a", "b"],
            count_recent_broadcasts=lambda *a, **k: 9,
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["status"] == "ok"
    assert st["checks"]["dedup"]["status"] == "ok"
    assert st["checks"]["dedup"]["titulos_24h"] == 2
    assert st["checks"]["broadcasts"]["enviados_24h"] == 9
    assert st["checks"]["evolution"]["status"] == "ok"
    assert "checked_at" in st


def test_collect_status_dedup_quebrado_vira_error():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("400 Bad Request")),
            count_recent_broadcasts=lambda *a, **k: 9,
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["status"] == "error"
    assert st["checks"]["dedup"]["status"] == "error"


def test_collect_status_evolution_desconectada_vira_warn():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_broadcasts=lambda *a, **k: 1,
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="close"):
        st = health.collect_status()
    assert st["status"] == "warn"
    assert st["checks"]["evolution"]["status"] == "warn"
    assert st["checks"]["evolution"]["estado"] == "close"


def test_collect_status_evolution_excecao_degrada_para_warn():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_broadcasts=lambda *a, **k: 1,
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state",
                  side_effect=RuntimeError("timeout")):
        st = health.collect_status()
    assert st["checks"]["evolution"]["status"] == "warn"


_STATUS_OK = {
    "status": "ok",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "ok", "titulos_24h": 12},
        "broadcasts": {"status": "ok", "enviados_24h": 9},
        "evolution": {"status": "ok", "estado": "open"},
        "polls": {"status": "ok", "institutos": 3},
    },
    "checked_at": "2026-06-25T11:00:00+00:00",
}

_STATUS_PROBLEMA = {
    "status": "error",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "error", "message": "400 Bad Request"},
        "broadcasts": {"status": "ok", "enviados_24h": 9},
        "evolution": {"status": "ok", "estado": "open"},
        "polls": {"status": "ok", "institutos": 3},
    },
    "checked_at": "2026-06-25T11:00:00+00:00",
}


def test_format_digest_verde():
    msg = health.format_digest(_STATUS_OK)
    assert "saúde diária" in msg
    assert "✅ Tudo OK" in msg
    assert "Dedup: ativo (12 títulos/24h)" in msg
    assert "Alertas enviados (24h): 9" in msg


def test_format_digest_problema_lidera_e_marca():
    msg = health.format_digest(_STATUS_PROBLEMA)
    assert "⚠️ 1 problema" in msg
    assert "❌" in msg
    assert "Dedup" in msg


_ADMIN_ENV = {"REPLY_TO_NUMBER": "5534999945010"}


def test_send_daily_digest_envia_para_admin():
    with patch.dict(os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered", return_value=None), \
         patch("backend.services.health.collect_status", return_value=_STATUS_OK), \
         patch("backend.services.health.supabase.set_alert_triggered"), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "sent"
    assert mock_send.call_args[0][0] == "5534999945010"
    assert "saúde diária" in mock_send.call_args[0][1]


def test_send_daily_digest_respeita_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    with patch.dict(os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered", return_value=recent), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "skipped"
    mock_send.assert_not_called()


def test_send_daily_digest_cooldown_falha_aberta():
    """Supabase fora não pode silenciar o boletim — se a trava não puder ser lida, envia mesmo assim."""
    with patch.dict(os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered",
               side_effect=RuntimeError("supabase down")), \
         patch("backend.services.health.collect_status", return_value=_STATUS_PROBLEMA), \
         patch("backend.services.health.supabase.set_alert_triggered"), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "sent"
    mock_send.assert_called_once()
