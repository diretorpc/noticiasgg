from backend.services import alert_checker, supabase, whatsapp
import pytest

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def test_notify_admin_uses_custom_title(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_NUMBER", "553400000000")
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rule_id: None)
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rule_id: None)
    captured = {}
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: captured.update(number=number, text=text) or {})

    alert_checker.notify_admin(["algo quebrou"], title="cron investing com falha")

    assert "cron investing com falha" in captured["text"]
    assert "algo quebrou" in captured["text"]
