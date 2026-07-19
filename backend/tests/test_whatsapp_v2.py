"""Formato de payload da Evolution v1 vs v2 (migração controlada por EVOLUTION_API_V2)."""
from unittest.mock import MagicMock, patch

import backend.services.whatsapp as whatsapp


def _mock_client(captured: dict) -> MagicMock:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}

    def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        return mock_resp

    mock_client.__enter__.return_value.post.side_effect = fake_post
    return mock_client


def _base_env(monkeypatch, v2):
    monkeypatch.setenv("EVOLUTION_API_KEY", "k")
    monkeypatch.setenv("EVOLUTION_API_URL", "http://evo")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "inst")
    if v2 is None:
        monkeypatch.delenv("EVOLUTION_API_V2", raising=False)
    else:
        monkeypatch.setenv("EVOLUTION_API_V2", v2)


def test_is_v2_toggle(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_V2", "true")
    assert whatsapp._is_v2()
    monkeypatch.setenv("EVOLUTION_API_V2", "false")
    assert not whatsapp._is_v2()
    monkeypatch.delenv("EVOLUTION_API_V2", raising=False)
    assert not whatsapp._is_v2()  # default = v1


def _no_lid():
    """Fixa a busca de LID: sem LID → usa o número. Necessário porque o mock do
    httpx vaza para o supabase (mesmo módulo), sujando a resolução."""
    return patch("backend.services.whatsapp.supabase.get_authorized_by_phone", return_value=None)


def test_send_message_v1_payload(monkeypatch):
    _base_env(monkeypatch, None)  # sem flag = legado v1
    captured = {}
    with _no_lid(), patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5511999999999", "oi")
    assert captured["json"]["number"] == "5511999999999"
    assert captured["json"]["textMessage"]["text"] == "oi"
    assert "text" not in captured["json"]  # v1 não achata


def test_send_message_v2_payload(monkeypatch):
    _base_env(monkeypatch, "true")
    captured = {}
    with _no_lid(), patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5511999999999", "oi")
    assert captured["json"] == {"number": "5511999999999", "text": "oi"}
    assert "textMessage" not in captured["json"]


def test_send_audio_v2_payload(monkeypatch):
    _base_env(monkeypatch, "1")
    captured = {}
    with _no_lid(), patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_audio("5511999999999", b"\x00\x01\x02")
    assert captured["json"]["number"] == "5511999999999"
    assert "audio" in captured["json"]
    assert "audioMessage" not in captured["json"]


def test_send_audio_v1_payload(monkeypatch):
    _base_env(monkeypatch, None)
    captured = {}
    with _no_lid(), patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_audio("5511999999999", b"\x00\x01\x02")
    assert captured["json"]["audioMessage"]["encoding"] is True
    assert "audio" not in captured["json"]  # v1 aninha em audioMessage


# ── Resolução telefone → LID ────────────────────────────────────────────────
# O WhatsApp só entrega para o LID; enviar para o JID de telefone é aceito mas
# nunca chega (verificado em produção 16/07/2026).

def test_send_message_traduz_telefone_para_lid(monkeypatch):
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "lid": "139247134720249@lid"}), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5534999945010", "oi")
    assert captured["json"]["number"] == "139247134720249@lid"  # LID, não o telefone


def test_send_message_lid_passa_direto(monkeypatch):
    """Quem já vem como LID é roteável — não traduz de novo."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_phone") as mock_lookup, \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("139247134720249@lid", "oi")
    assert captured["json"]["number"] == "139247134720249@lid"
    mock_lookup.assert_not_called()


def test_send_message_traduz_jid_de_telefone_para_lid(monkeypatch):
    """O `remoteJid` da v2 vem como `<numero>@s.whatsapp.net`, que a Evolution
    aceita e nunca entrega. Passá-lo direto emudece o bot — foi o que matou o
    aviso de erro do webhook em 16/07/2026."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_jid",
               return_value={"phone": "5516991016898", "lid": "139247134720249@lid"}), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5516991016898@s.whatsapp.net", "oi")
    assert captured["json"]["number"] == "139247134720249@lid"


def test_send_message_jid_de_telefone_sem_lid_cai_no_numero(monkeypatch):
    """Sem LID cadastrado, envia para o número puro — a Evolution ainda pode
    resolver. Repassar o JID cru é o único caminho comprovadamente morto."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_jid", return_value=None), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5516991016898@s.whatsapp.net", "oi")
    assert captured["json"]["number"] == "5516991016898"


def test_send_message_jid_de_telefone_lookup_falha_nao_quebra(monkeypatch):
    """Supabase fora do ar não pode explodir o envio."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_jid",
               side_effect=Exception("supabase timeout")), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5516991016898@s.whatsapp.net", "oi")
    assert captured["json"]["number"] == "5516991016898"


def test_send_message_sem_lid_cai_no_telefone(monkeypatch):
    """Usuário sem LID cadastrado → fallback para o número (não pior que antes)."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "lid": None}), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5534999945010", "oi")
    assert captured["json"]["number"] == "5534999945010"


def test_send_message_lookup_falha_nao_quebra(monkeypatch):
    """Se o Supabase cair, o envio não pode explodir — usa o número."""
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_phone",
               side_effect=Exception("supabase timeout")), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_message("5534999945010", "oi")
    assert captured["json"]["number"] == "5534999945010"


def test_send_audio_tambem_traduz_para_lid(monkeypatch):
    _base_env(monkeypatch, "true")
    captured = {}
    with patch("backend.services.whatsapp.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "lid": "139247134720249@lid"}), \
         patch("backend.services.whatsapp.httpx.Client", return_value=_mock_client(captured)):
        whatsapp.send_audio("5534999945010", b"\x00\x01")
    assert captured["json"]["number"] == "139247134720249@lid"
