import os
from unittest.mock import patch

from backend.services import alert_checker

_ADMIN = "5534999945010"
_RECIPIENTS = [{"phone": "5534999000001", "name": "A"}]


def test_notify_admin_envia_mensagem_de_erro():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set, \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["news: API limit reached"])
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == _ADMIN
    assert "news: API limit reached" in mock_send.call_args[0][1]
    mock_set.assert_called_once_with("system_error_alert")


def test_notify_admin_respeita_cooldown():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=False), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["news: API limit reached"])
    mock_send.assert_not_called()


def test_notify_admin_sem_admin_configurado_nao_quebra():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": "", "AUTHORIZED_NUMBER": ""}), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["erro qualquer"])
    mock_send.assert_not_called()


def test_notify_admin_lista_vazia_nao_envia():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin([])
    mock_send.assert_not_called()


def test_run_checks_notifica_admin_quando_news_falha():
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.collectors.news.collect", side_effect=RuntimeError("NewsAPI 429")), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.notify_admin") as mock_notify:
        result = alert_checker.run_checks(test_mode=True)
    assert result["status"] == "ok"
    assert result["errors"] == ["news: NewsAPI 429"]
    mock_notify.assert_called_once_with(["news: NewsAPI 429"])


def test_run_checks_sem_recipients_notifica_admin():
    with patch("backend.services.alert_checker._get_recipients", return_value=[]), \
         patch("backend.services.alert_checker.notify_admin") as mock_notify:
        result = alert_checker.run_checks(test_mode=True)
    assert result["recipients"] == 0
    mock_notify.assert_called_once()
    assert "recipients" in mock_notify.call_args[0][0][0]


def test_broadcast_zero_entregas_reporta_erro():
    errors: list[str] = []
    with patch("backend.services.alert_checker.whatsapp.send_message", side_effect=RuntimeError("down")):
        sent = alert_checker._broadcast("msg", _RECIPIENTS, errors)
    assert sent == 0
    assert errors == ["whatsapp: broadcast entregou 0/1"]


def test_broadcast_com_sucesso_nao_reporta_erro():
    errors: list[str] = []
    with patch("backend.services.alert_checker.whatsapp.send_message"):
        sent = alert_checker._broadcast("msg", _RECIPIENTS, errors)
    assert sent == 1
    assert errors == []
