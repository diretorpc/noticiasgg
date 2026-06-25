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
