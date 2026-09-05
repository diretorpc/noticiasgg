import pytest

from backend.services import alert_checker, soja_digest, soja_msg, supabase, whatsapp
from backend.services.date_brt import date_brt

# Arquivo sem nenhuma chamada de rede: `soja_msg.gerar` é sempre mockada,
# nunca chamada de verdade (ela é quem tocaria coletor/rede). Coloca este
# arquivo no portão do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def _res(indisponiveis=None, avisos=None, texto="Soja Disponível\n\nPorto = 159,44"):
    return {
        "texto": texto,
        "porto_data_ref": "03/09",
        "cbot_simbolo": "ZSU6",
        "cbot_atualizado_em": "2026-09-04T12:00:00Z",
        "dolar_atualizado_em": "2026-09-04T12:00:00Z",
        "avisos": avisos or [],
        "indisponiveis": indisponiveis or [],
    }


# ---------------------------------------------------------------------------
# mensagem segurada (indisponiveis não vazio)
# ---------------------------------------------------------------------------

def test_held_warns_admin_and_never_broadcasts(monkeypatch):
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    monkeypatch.setattr(soja_msg, "gerar",
                        lambda: _res(indisponiveis=["Porto", "Praças (fretes)"],
                                    avisos=["coleta: timeout"]))
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    sent = []
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: sent.append((number, text)) or {"key": {"id": "1"}})

    broadcast_calls = []
    monkeypatch.setattr(alert_checker, "_broadcast",
                        lambda *a, **k: broadcast_calls.append(a) or 0)

    triggered = []
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rid: triggered.append(rid))

    result = soja_digest.run()

    assert result["status"] == "held"
    assert result["indisponiveis"] == ["Porto", "Praças (fretes)"]
    assert result["sent"] == 0
    assert broadcast_calls == []          # nunca chega perto da lista de alertas
    assert triggered == []                # trava não é armada — pode sair se a fonte voltar
    assert len(sent) == 1
    admin_number, texto = sent[0]
    assert admin_number == "5534999945010"
    assert "segurada" in texto
    assert "Porto" in texto
    assert "coleta: timeout" in texto


def test_held_without_admin_does_not_raise(monkeypatch):
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    monkeypatch.setattr(soja_msg, "gerar", lambda: _res(indisponiveis=["Dólar"]))
    monkeypatch.delenv("REPLY_TO_NUMBER", raising=False)
    monkeypatch.delenv("AUTHORIZED_NUMBER", raising=False)

    called = []
    monkeypatch.setattr(whatsapp, "send_message", lambda *a, **k: called.append(a))

    result = soja_digest.run()

    assert result["status"] == "held"
    assert called == []


def test_held_send_message_failure_does_not_propagate(monkeypatch):
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    monkeypatch.setattr(soja_msg, "gerar", lambda: _res(indisponiveis=["CBOT"]))
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    def boom(number, text):
        raise RuntimeError("evolution fora do ar")
    monkeypatch.setattr(whatsapp, "send_message", boom)

    result = soja_digest.run()  # não pode levantar

    assert result["status"] == "held"


# ---------------------------------------------------------------------------
# caminho normal (indisponiveis vazio)
# ---------------------------------------------------------------------------

def _wire_ok(monkeypatch, sent_store, already=None, set_calls=None):
    monkeypatch.setattr(soja_msg, "gerar", lambda: _res())
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])

    def fake_broadcast(msg, recipients, errors=None):
        sent_store.append((msg, recipients))
        return len(recipients)
    monkeypatch.setattr(alert_checker, "_broadcast", fake_broadcast)

    triggered = set(already or set())

    def fake_get(rid):
        return object() if rid in triggered else None

    def fake_set(rid):
        triggered.add(rid)
        if set_calls is not None:
            set_calls.append(rid)

    monkeypatch.setattr(supabase, "get_alert_last_triggered", fake_get)
    monkeypatch.setattr(supabase, "set_alert_triggered", fake_set)
    return triggered


def test_ok_broadcasts_exact_text_and_marks_triggered(monkeypatch):
    sent = []
    set_calls = []
    _wire_ok(monkeypatch, sent, set_calls=set_calls)

    result = soja_digest.run()

    assert result["status"] == "ok"
    assert result["sent"] == 1
    assert len(sent) == 1
    msg, recipients = sent[0]
    assert msg == _res()["texto"]
    assert recipients == [{"phone": "553400000000", "name": "Chefe"}]
    assert set_calls == [f"{soja_digest.RULE_PREFIX}{date_brt()}"]


def test_already_sent_today_is_skipped(monkeypatch):
    rule_id = f"{soja_digest.RULE_PREFIX}{date_brt()}"
    sent = []
    _wire_ok(monkeypatch, sent, already={rule_id})

    result = soja_digest.run()

    assert result["status"] == "skipped"
    assert result["sent"] == 0
    assert sent == []


def test_test_mode_targets_admin_only_and_ignores_trava(monkeypatch):
    rule_id = f"{soja_digest.RULE_PREFIX}{date_brt()}"
    sent = []
    set_calls = []
    _wire_ok(monkeypatch, sent, already={rule_id}, set_calls=set_calls)
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    result = soja_digest.run(test_mode=True)

    assert result["status"] == "ok"
    assert len(sent) == 1
    msg, recipients = sent[0]
    assert recipients == [{"phone": "5534999945010", "name": "admin"}]
    assert set_calls == []  # test_mode nunca arma a trava


def test_test_mode_without_admin_does_not_broadcast_to_real_list(monkeypatch):
    """Achado da revisão 05/09/2026 (Apolo): sem REPLY_TO_NUMBER/AUTHORIZED_NUMBER,
    test_mode mandava a mensagem REAL para a lista inteira, sem marca de teste e
    sem armar a trava. Tem que abortar antes de qualquer broadcast."""
    sent = []
    _wire_ok(monkeypatch, sent)
    monkeypatch.delenv("REPLY_TO_NUMBER", raising=False)
    monkeypatch.delenv("AUTHORIZED_NUMBER", raising=False)

    broadcast_calls = []
    monkeypatch.setattr(alert_checker, "_broadcast",
                        lambda *a, **k: broadcast_calls.append(a) or 0)

    result = soja_digest.run(test_mode=True)

    assert result["status"] == "error"
    assert result["detail"] == "test_mode sem admin configurado"
    assert result["sent"] == 0
    assert broadcast_calls == []


def test_zero_recipients_is_error_and_warns_admin_directly(monkeypatch):
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    monkeypatch.setattr(soja_msg, "gerar", lambda: _res())
    monkeypatch.setattr(alert_checker, "_get_recipients", lambda: [])
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    sent = []
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: sent.append((number, text)))
    notified = []
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))

    result = soja_digest.run()

    assert result["status"] == "error"
    assert notified == []  # NÃO passa pelo notify_admin (cooldown compartilhado)
    assert len(sent) == 1
    admin_number, texto = sent[0]
    assert admin_number == "5534999945010"
    assert "cron soja com falha" in texto
    assert "0 destinatários" in texto


def test_broadcast_errors_warn_admin_directly(monkeypatch):
    monkeypatch.setattr(soja_msg, "gerar", lambda: _res())
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])
    monkeypatch.setenv("REPLY_TO_NUMBER", "5534999945010")

    def fake_broadcast(msg, recipients, errors=None):
        if errors is not None:
            errors.append("whatsapp: broadcast entregou 0/1")
        return 0
    monkeypatch.setattr(alert_checker, "_broadcast", fake_broadcast)
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rid: None)
    set_calls = []
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rid: set_calls.append(rid))

    sent = []
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: sent.append((number, text)))
    notified = []
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))

    result = soja_digest.run()

    assert result["sent"] == 0
    assert result["status"] == "error"  # 0 entregues com destinatários não é ok
    assert result["test_mode"] is False
    assert set_calls == []  # sem envio, sem trava
    assert notified == []  # NÃO passa pelo notify_admin (cooldown compartilhado)
    assert len(sent) == 1
    admin_number, texto = sent[0]
    assert admin_number == "5534999945010"
    assert "cron soja com falha" in texto
    assert "broadcast entregou 0/1" in texto


def test_set_alert_triggered_failure_does_not_propagate(monkeypatch):
    """Entregou e não conseguiu gravar a trava: a mensagem já saiu, não pode
    levantar (senão o cron reenviaria por engano no mesmo minuto)."""
    sent = []
    _wire_ok(monkeypatch, sent)

    def boom(rid):
        raise RuntimeError("supabase fora do ar")
    monkeypatch.setattr(supabase, "set_alert_triggered", boom)

    result = soja_digest.run()  # não pode levantar

    assert result["status"] == "ok"
    assert result["sent"] == 1


def test_already_sent_today_skips_before_collecting(monkeypatch):
    """A trava é conferida ANTES de `soja_msg.gerar()` — já enviado hoje não
    pode disparar a coleta de porto/praças/CBOT/dólar à toa."""
    rule_id = f"{soja_digest.RULE_PREFIX}{date_brt()}"
    monkeypatch.setattr(supabase, "get_alert_last_triggered",
                        lambda rid: object() if rid == rule_id else None)

    gerar_calls = []
    monkeypatch.setattr(soja_msg, "gerar", lambda: gerar_calls.append(1) or _res())

    result = soja_digest.run()

    assert result["status"] == "skipped"
    assert gerar_calls == []
