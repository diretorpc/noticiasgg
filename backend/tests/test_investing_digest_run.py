from pathlib import Path

from backend.collectors import investing_calendar
from backend.services import investing_digest, alert_checker, supabase
import pytest

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures"


def _page():
    return (FIXTURES / "investing_next_data.html").read_text(encoding="utf-8")


def _wire(monkeypatch, sent_store, already=None):
    already = already or set()
    monkeypatch.setattr(investing_calendar, "fetch", lambda: _page())
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])

    def fake_broadcast(msg, recipients, errors=None):
        sent_store.append(msg)
        return len(recipients)
    monkeypatch.setattr(alert_checker, "_broadcast", fake_broadcast)

    triggered = set(already)
    monkeypatch.setattr(supabase, "get_alert_last_triggered",
                        lambda rid: object() if rid in triggered else None)
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rid: triggered.add(rid))
    return triggered


def test_run_sends_grouped_message_for_new_events(monkeypatch):
    sent = []
    _wire(monkeypatch, sent)
    result = investing_digest.run()
    assert result["status"] == "ok"
    assert result["events"] == 2  # FDI + PIB Espanha
    assert result["sent"] == 1
    assert len(sent) == 1
    assert "🇧🇷 Investimento Estrangeiro Direto" in sent[0]
    assert "PIB da Espanha (trimestral) (Q1)" in sent[0]


def test_run_dedups_on_second_call(monkeypatch):
    sent = []
    _wire(monkeypatch, sent)
    investing_digest.run()           # primeira vez: envia e marca
    sent.clear()
    result = investing_digest.run()  # segunda vez: tudo já enviado
    assert result["events"] == 0
    assert result["sent"] == 0
    assert sent == []


def test_run_reports_error_on_unrecognized_body(monkeypatch):
    notified = []
    monkeypatch.setattr(investing_calendar, "fetch", lambda: "<html>cloudflare block</html>")
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))
    result = investing_digest.run()
    assert result["status"] == "error"
    assert notified  # admin avisado da quebra
    assert notified[0][1] == "cron investing com falha"


def test_run_no_recipients_returns_error(monkeypatch):
    notified = []
    monkeypatch.setattr(alert_checker, "_get_recipients", lambda: [])
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))
    result = investing_digest.run()
    assert result["status"] == "error"
    assert notified  # admin avisado de 0 destinatários


def test_test_mode_without_admin_does_not_broadcast_to_real_list(monkeypatch):
    """Achado da revisão 05/09/2026 (Apolo): sem REPLY_TO_NUMBER/AUTHORIZED_NUMBER,
    test_mode mandava a mensagem REAL para a lista inteira, sem marca de teste e
    sem armar a trava. Tem que abortar antes de qualquer broadcast."""
    sent = []
    _wire(monkeypatch, sent)
    monkeypatch.delenv("REPLY_TO_NUMBER", raising=False)
    monkeypatch.delenv("AUTHORIZED_NUMBER", raising=False)

    broadcast_calls = []
    monkeypatch.setattr(alert_checker, "_broadcast",
                        lambda *a, **k: broadcast_calls.append(a) or 0)

    result = investing_digest.run(test_mode=True)

    assert result["status"] == "error"
    assert result["detail"] == "test_mode sem admin configurado"
    assert result["sent"] == 0
    assert broadcast_calls == []


@pytest.mark.unit
def test_set_alert_triggered_falhando_num_evento_nao_derruba_o_lote(monkeypatch):
    """Trava gravada por evento em try/except: 503 intermitente no 2º evento não
    pode estourar run() (e reenviar o lote inteiro na próxima hora)."""
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])
    monkeypatch.setattr(investing_calendar, "fetch", lambda: "<html/>")
    monkeypatch.setattr(investing_calendar, "parse", lambda html: [
        {"event_id": "e1", "flag_emoji": "🇺🇸", "name": "CPI", "time": "09:30",
         "actual": "1.0", "forecast": "1.0", "previous": "1.0"},
        {"event_id": "e2", "flag_emoji": "🇺🇸", "name": "PPI", "time": "09:30",
         "actual": "1.0", "forecast": "1.0", "previous": "1.0"},
    ])
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    gravadas = []

    def set_trigger(rid):
        if rid.startswith("investing_e2_"):
            raise RuntimeError("supabase 503")
        gravadas.append(rid)
    monkeypatch.setattr(supabase, "set_alert_triggered", set_trigger)
    monkeypatch.setattr(alert_checker, "_broadcast", lambda msg, targets, errors: 1)
    monkeypatch.setattr(alert_checker, "notify_admin", lambda errors, title="x": None)

    out = investing_digest.run()

    assert out["status"] == "ok"
    assert len(gravadas) == 1 and gravadas[0].startswith("investing_e1_")
