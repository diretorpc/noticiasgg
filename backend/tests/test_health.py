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
