import copy
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services import health

_KEYS_OK = {"status": "ok", "faltando": []}


def test_collect_status_tudo_ok():
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a", "b"],
            count_recent_alert_messages=lambda *a, **k: 5,
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
            count_recent_alert_messages=lambda *a, **k: 5,
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
            count_recent_alert_messages=lambda *a, **k: 5,
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
            count_recent_alert_messages=lambda *a, **k: 5,
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
            count_recent_alert_messages=lambda *a, **k: 5,
            count_recent_broadcasts=lambda *a, **k: 3,
            get_news_log=lambda *a, **k: {"itens": []},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["checks"]["news_log"]["status"] == "error"
    assert st["checks"]["news_log"]["broadcasts_24h"] == 3
    assert st["status"] == "error"


@pytest.mark.unit
def test_collect_status_registro_indisponivel_vira_warn_nao_escrita_silenciosa():
    """A3: get_news_log devolve {'itens': [], 'aviso': ...} quando a LEITURA falha —
    isso não prova nada sobre a ESCRITA. Antes o check só olhava `.get('itens')` e
    descartava o aviso, então uma leitura soluçada com 3 broadcasts na janela virava
    'escrita silenciosa' (error) — bug que não existe, o dono caçaria à toa."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_alert_messages=lambda *a, **k: 5,
            count_recent_broadcasts=lambda *a, **k: 3,
            get_news_log=lambda *a, **k: {"itens": [], "aviso": "registro indisponível"},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["checks"]["news_log"]["status"] == "warn"
    assert "registro indisponível" in st["checks"]["news_log"]["message"]
    assert st["status"] == "warn"  # não pode virar error global por uma leitura soluçada


@pytest.mark.unit
def test_collect_status_news_log_nao_chama_count_recent_broadcasts_duas_vezes():
    """O check `broadcasts` já calcula `enviados_24h` — reaproveitar evita uma
    consulta extra por visita a /api/health, que é público e sem senha."""
    chamadas = {"n": 0}

    def _contar(*a, **k):
        chamadas["n"] += 1
        return 5

    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_alert_messages=lambda *a, **k: 5,
            count_recent_broadcasts=_contar,
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        health.collect_status()
    assert chamadas["n"] == 1


@pytest.mark.unit
def test_collect_status_news_log_excecao_vira_warn_nao_error():
    """Um check que não conseguiu LER o registro não prova que a escrita falhou —
    escalar para 'error' global por uma exceção de leitura era severidade errada."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_alert_messages=lambda *a, **k: 5,
            count_recent_broadcasts=lambda *a, **k: 1,
            get_news_log=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")),
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["checks"]["news_log"]["status"] == "warn"


@pytest.mark.unit
def test_collect_status_dia_calmo_sem_broadcast_nem_log_fica_ok():
    """Zero alertas e zero registros no mesmo dia é o caso COMUM (dia sem notícia
    relevante) — não pode acender erro."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: [],
            count_recent_alert_messages=lambda *a, **k: 5,
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


@pytest.mark.unit
def test_format_digest_news_log_registro_indisponivel_mostra_warn_nao_escrita_silenciosa():
    """A3: a linha do boletim tinha o ícone de erro cravado ('❌') para QUALQUER
    status com 'message', mesmo quando o status real era 'warn' (leitura falhou).
    O texto 'escrita silenciosa' é reservado para o caso confirmado (achado A4)."""
    status = {**_STATUS_OK, "checks": {
        **_STATUS_OK["checks"],
        "news_log": {"status": "warn", "message": "registro indisponível"},
    }}
    msg = health.format_digest(status)
    assert "⚠️" in msg
    assert "registro indisponível" in msg
    assert "escrita silenciosa" not in msg


_ADMIN_ENV = {"REPLY_TO_NUMBER": "5534999945010"}


def test_send_daily_digest_envia_para_admin():
    # deepcopy virou redundante em 04/09: collect_status_completo passou a copiar
    # os dois níveis antes de acrescentar checks (health.py). Fica como rede caso
    # alguém reintroduza escrita no dict recebido — foi isso que envenenava os
    # testes seguintes conforme a ordem (3ª revisão do Apolo).
    with patch.dict(os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered", return_value=None), \
         patch("backend.services.health.collect_status",
               side_effect=lambda: copy.deepcopy(_STATUS_OK)), \
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


def _completo_soja(describe_return, sonda=None, fontes=None):
    """Molde de `_completo` em test_anthropic_status.py: `collect_status` fixo em
    ok e só a peça sob teste (soja_fretes.describe) varia."""
    with patch.object(health.anthropic_status, "sondar",
                      return_value=sonda or {"status": "ok"}), \
         patch.object(health, "collect_status",
                      return_value={"status": "ok", "checks": {"keys": {"status": "ok", "faltando": []}},
                                    "checked_at": "t"}), \
         patch("backend.collectors.news.source_health",
               return_value=fontes or {"vivas": 20, "total": 20, "mortas": []}), \
         patch.object(health.soja_fretes, "describe", return_value=describe_return):
        return health.collect_status_completo()


_SOJA_NUNCA_SALVO = {
    "fretes": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
    "pracas": [], "is_custom": False, "updated_at": None, "updated_by": None,
    "idade_dias": None, "envelhecido": True,
}

_SOJA_10_DIAS = {
    "fretes": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
    "pracas": [], "is_custom": True, "updated_at": "2026-08-25T00:00:00+00:00",
    "updated_by": "matheusmouro@hotmail.com", "idade_dias": 10, "envelhecido": False,
}

_SOJA_61_DIAS = {
    **_SOJA_10_DIAS, "idade_dias": 61, "envelhecido": True,
}

# Achado 1: valor salvo inválido/parcial (describe() completa com default e
# marca "aviso"), mas com updated_at RECENTE (envelhecido=False) — o check
# ignorava o aviso e dizia "ok".
_SOJA_AVISO_RECENTE = {
    **_SOJA_10_DIAS,
    "aviso": "valor salvo incompleto ou inválido — usando padrão para o(s) frete(s) faltante(s)",
}

# Achado 2: updated_at nulo/ilegível -> idade_dias=None, com is_custom True
# (linha existe, mas a data não presta). A mensagem não pode virar "há None dias".
_SOJA_ILEGIVEL = {
    "fretes": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
    "pracas": [], "is_custom": True, "updated_at": "não é uma data",
    "updated_by": "x", "idade_dias": None, "envelhecido": True,
}


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_warn_quando_nunca_salvo():
    r = _completo_soja(_SOJA_NUNCA_SALVO)
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    assert "9/12/27" in r["checks"]["soja_fretes"]["message"] or \
           "padrão" in r["checks"]["soja_fretes"]["message"].lower()


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_ok_quando_10_dias():
    r = _completo_soja(_SOJA_10_DIAS)
    assert r["checks"]["soja_fretes"]["status"] == "ok"
    assert r["checks"]["soja_fretes"]["idade_dias"] == 10
    assert r["checks"]["soja_fretes"]["updated_at"] == "2026-08-25T00:00:00+00:00"


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_warn_quando_61_dias():
    r = _completo_soja(_SOJA_61_DIAS)
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    assert "61" in r["checks"]["soja_fretes"]["message"]
    assert "primo" in r["checks"]["soja_fretes"]["message"].lower()


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_warn_quando_aviso_mesmo_nao_envelhecido():
    """Achado 1 do Apolo: valor salvo inválido/parcial some atrás do default
    silenciosamente — o check tem que avisar mesmo com updated_at recente."""
    r = _completo_soja(_SOJA_AVISO_RECENTE)
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    assert "inválido" in r["checks"]["soja_fretes"]["message"] or \
           "incompleto" in r["checks"]["soja_fretes"]["message"]


@pytest.mark.unit
def test_line_soja_fretes_aviso_mostra_alerta():
    linha = health._line_soja_fretes({"status": "warn", "message": "valor salvo incompleto"})
    assert "⚠️" in linha


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_warn_data_ilegivel_sem_none_na_mensagem():
    """Achado 2 do Apolo: 'editados há None dias' não pode ir pro WhatsApp."""
    r = _completo_soja(_SOJA_ILEGIVEL)
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    msg = r["checks"]["soja_fretes"]["message"]
    assert "None" not in msg
    assert "ilegível" in msg.lower() or "ilegivel" in msg.lower()


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_warn_quando_describe_traz_erro():
    r = _completo_soja({**_SOJA_NUNCA_SALVO, "erro": "500 supabase indisponível"})
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    assert "supabase" in r["checks"]["soja_fretes"]["message"].lower()


@pytest.mark.unit
def test_collect_status_completo_soja_fretes_excecao_nao_derruba_outros_checks():
    """Vizinhos (news_sources, anthropic) protegem com try/except; soja_fretes
    tem que seguir o mesmo padrão, sem soja_fretes.describe() ele nunca levanta,
    mas o check em si (chamada + montagem da linha) não pode derrubar o boletim."""
    with patch.object(health.anthropic_status, "sondar", return_value={"status": "ok"}), \
         patch.object(health, "collect_status",
                      return_value={"status": "ok", "checks": {"keys": {"status": "ok", "faltando": []}},
                                    "checked_at": "t"}), \
         patch("backend.collectors.news.source_health",
               return_value={"vivas": 20, "total": 20, "mortas": []}), \
         patch.object(health.soja_fretes, "describe", side_effect=RuntimeError("estourou")):
        r = health.collect_status_completo()
    assert r["checks"]["soja_fretes"]["status"] == "warn"
    assert "news_sources" in r["checks"]
    assert "anthropic" in r["checks"]


@pytest.mark.unit
def test_format_digest_soja_fretes_aparece_quando_envelhecido():
    status = {**_STATUS_OK, "checks": {**_STATUS_OK["checks"],
              "soja_fretes": {"status": "warn", "message": "nunca salvos no painel — usando padrão 9/12/27"}}}
    msg = health.format_digest(status)
    assert "soja" in msg.lower() or "Soja" in msg
    assert "⚠️" in msg


@pytest.mark.unit
def test_format_digest_soja_fretes_nao_aparece_se_ausente():
    """Igual a news_sources: só entra no boletim quando a chave existe (é
    exclusiva do collect_status_completo)."""
    msg = health.format_digest(_STATUS_OK)
    assert "Soja" not in msg and "soja" not in msg


def test_entrega_por_destinatario_secando_vira_error_com_a_mensagem_certa():
    """Achado 12 da 2a revisao: `news_log_messages` virou fonte da verdade do
    `get_sent_news` e nada a vigiava. Achados 1 e 3 da 3a revisao: o conserto nao
    tinha teste, e o boletim usava o texto do OUTRO alarme — cravava "0 registrados"
    quando os alertas ESTAVAM registrados, mandando o dono cacar bug que nao existe."""
    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_broadcasts=lambda *a, **k: 7,
            count_recent_alert_messages=lambda *a, **k: 0,
            get_news_log=lambda *a, **k: {"itens": [{"news_id": "x"}]},
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    nl = st["checks"]["news_log"]
    assert nl["status"] == "error"
    assert nl["registrado"] is True
    assert nl["entregas_registradas"] == 0

    linha = health._line_news_log(nl)
    assert "escrita silenciosa" not in linha, "texto do alarme errado"
    assert "entregas por destinatário" in linha


def test_falha_na_contagem_de_entregas_nao_apaga_o_alarme_de_escrita_silenciosa():
    """Achado 2 da 3a revisao: a consulta nova ficava dentro do `try` compartilhado,
    entao um 500 nela pulava para o `except` e transformava o `error` do A4 (ja
    calculado) num `warn`. Alarme novo nao pode apagar alarme velho."""
    def _explode(*a, **k):
        raise RuntimeError("500 Supabase")

    with patch("backend.services.health._check_keys", return_value=_KEYS_OK), \
         patch.multiple(
            "backend.services.health.supabase",
            get_recent_sent_titles=lambda *a, **k: ["a"],
            count_recent_broadcasts=lambda *a, **k: 7,
            count_recent_alert_messages=_explode,
            get_news_log=lambda *a, **k: {"itens": []},   # A4 de verdade
            get_polls=lambda *a, **k: [{"instituto": "X"}],
         ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    nl = st["checks"]["news_log"]
    assert nl["status"] == "error", "o A4 foi rebaixado para warn pela consulta nova"
    assert nl["registrado"] is False
    assert "escrita silenciosa" in health._line_news_log(nl)


def test_contagem_de_entregas_le_o_content_range():
    """Mesma cobertura que a gemea `count_recent_broadcasts` ja tinha."""
    from backend.services import supabase as sb

    def _cliente(headers):
        r = MagicMock(status_code=200)
        r.raise_for_status = MagicMock()
        r.headers = headers
        c = MagicMock()
        c.__enter__ = MagicMock(return_value=c)
        c.__exit__ = MagicMock(return_value=False)
        c.get = MagicMock(return_value=r)
        return c

    with patch.object(sb, "_client", return_value=_cliente({"content-range": "0-0/41"})):
        assert sb.count_recent_alert_messages(hours=24) == 41
    with patch.object(sb, "_client", return_value=_cliente({})):
        assert sb.count_recent_alert_messages(hours=24) == 0
