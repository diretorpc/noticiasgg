from pathlib import Path

from backend.collectors import investing_calendar
from backend.services import investing_digest, alert_checker, supabase

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
