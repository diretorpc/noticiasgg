import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.services import health

_KEYS_OK = {"status": "ok", "faltando": []}


def test_collect_status_tudo_ok():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a", "b"],
            count_recent_broadcasts=lambda *a, **k: 9,
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["status"] == "ok"
    assert st["checks"]["dedup"]["status"] == "ok"
    assert st["checks"]["dedup"]["titulos_24h"] == 2
    assert st["checks"]["broadcasts"]["enviados_24h"] == 9
    assert st["checks"]["news_log"]["status"] == "ok"
    assert st["checks"]["evolution"]["status"] == "ok"
    assert "checked_at" in st


def test_collect_status_dedup_quebrado_vira_error():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("400 Bad Request")),
            count_recent_broadcasts=lambda *a, **k: 9,
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
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
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
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
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state",
                  side_effect=RuntimeError("timeout")):
        st = health.collect_status()
    assert st["checks"]["evolution"]["status"] == "warn"


@pytest.mark.unit
def test_collect_status_broadcast_sem_registro_no_log_vira_error():
    """A4: alerta SAIU (broadcast>0) mas o registro legível não acompanhou — sintoma
    de migration não executada ou log_sent_news falhando calado. Dia calmo (os dois
    zerados) NÃO é isto — ver o teste seguinte."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_broadcasts=lambda *a, **k: 3,
            get_news_log=lambda *a, **k: {"itens": []},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["checks"]["news_log"]["status"] == "error"
    assert st["checks"]["news_log"]["broadcasts_24h"] == 3
    assert st["status"] == "error"


@pytest.mark.unit
def test_collect_status_dia_calmo_sem_broadcast_nem_log_fica_ok():
    """Zero alertas e zero registros no mesmo dia é o caso COMUM (dia sem notícia
    relevante) — não pode acender erro."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: [],
            count_recent_broadcasts=lambda *a, **k: 0,
            get_news_log=lambda *a, **k: {"itens": []},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["checks"]["news_log"]["status"] == "ok"
    assert st["status"] == "ok"


_STATUS_OK = {
    "status": "ok",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "ok", "titulos_24h": 12},
        "broadcasts": {"status": "ok", "enviados_24h": 9},
        "news_log": {"status": "ok", "broadcasts_24h": 9, "registrado": True},
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
        "news_log": {"status": "ok", "broadcasts_24h": 9, "registrado": True},
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
    assert "Registro de notícias: OK (9 alertas/24h)" in msg


def test_format_digest_problema_lidera_e_marca():
    msg = health.format_digest(_STATUS_PROBLEMA)
    assert "⚠️ 1 problema" in msg
    assert "❌" in msg
    assert "Dedup" in msg


@pytest.mark.unit
def test_format_digest_news_log_silencioso_aparece_no_boletim():
    """A4: broadcast saiu, registro não acompanhou — precisa aparecer no boletim
    que já roda em produção, não só no JSON de /api/health."""
    status = {**_STATUS_PROBLEMA, "checks": {
        **_STATUS_PROBLEMA["checks"],
        "dedup": {"status": "ok", "titulos_24h": 12},
        "news_log": {"status": "error", "broadcasts_24h": 3, "registrado": False},
    }}
    msg = health.format_digest(status)
    assert "Registro de notícias" in msg
    assert "escrita silenciosa" in msg


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


def test_health_digest_endpoint_exige_cron_secret():
    from backend.api.main import app
    client = TestClient(app)
    with patch.dict(os.environ, {"CRON_SECRET": "s3cr3t"}):
        r = client.get("/api/health-digest")  # sem header
    assert r.status_code == 401


def test_health_digest_endpoint_dispara_digest():
    from backend.api.main import app
    client = TestClient(app)
    with patch.dict(os.environ, {"CRON_SECRET": "s3cr3t"}), \
         patch("backend.api.health_digest.health.send_daily_digest",
               return_value={"status": "sent", "overall": "ok"}) as mock_dig:
        r = client.get("/api/health-digest", headers={"Authorization": "Bearer s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"
    mock_dig.assert_called_once()


def test_health_endpoint_usa_collect_status():
    from backend.api.main import app
    client = TestClient(app)
    fake = {"status": "ok", "checks": {"dedup": {"status": "ok"}}, "checked_at": "x"}
    with patch("backend.api.main.health.collect_status", return_value=fake):
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["checks"]["dedup"]["status"] == "ok"


def test_collect_status_nao_toca_a_rede_de_noticias():
    """/api/health é público e sem senha (main.py:59). Se collect_status coletar as
    fontes, qualquer um dispara 20 buscas na internet no seu servidor a cada chamada
    — amplificação, e o endereço de saúde passa de instantâneo para ~9s."""
    with patch("backend.collectors.news.source_health") as espiao, \
         patch("backend.services.health.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.health.supabase.count_recent_broadcasts", return_value=0), \
         patch("backend.services.health.supabase.get_news_log", return_value={"itens": []}), \
         patch("backend.services.health.supabase.get_polls", return_value=[{"i": 1}]), \
         patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    espiao.assert_not_called()
    assert "news_sources" not in st["checks"]


def test_digest_diario_confere_as_fontes():
    """O boletim é o único lugar que precisa da medição — 1x/dia, não a cada visita."""
    with patch("backend.collectors.news.source_health",
               return_value={"total": 20, "vivas": 18, "mortas": ["A", "B"], "erro": None}):
        st = health.collect_status_completo()
    assert st["checks"]["news_sources"]["status"] == "warn"
    assert st["checks"]["news_sources"]["mortas"] == ["A", "B"]
    assert "18/20" in health.format_digest(st)
