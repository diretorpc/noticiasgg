"""Resolução do remoteJid → usuário nos dois formatos de Evolution.

v1 manda `<lid>@lid`; v2 manda `<numero>@s.whatsapp.net` (e, no Brasil,
normalmente sem o 9 extra). A lista de autorizados é indexada por lid.
"""
from unittest.mock import patch

from backend.services import supabase

_USER = {"lid": "139247134720249@lid", "phone": "5534999945010", "name": "Matheus (admin)"}


def test_jid_lid_busca_por_lid():
    with patch("backend.services.supabase.get_authorized", return_value=_USER) as by_lid, \
         patch("backend.services.supabase.get_authorized_by_phone") as by_phone:
        assert supabase.get_authorized_by_jid("139247134720249@lid") == _USER
    by_lid.assert_called_once_with("139247134720249@lid")
    by_phone.assert_not_called()


def test_jid_whatsapp_net_busca_por_telefone():
    with patch("backend.services.supabase.get_authorized_by_phone", return_value=_USER):
        assert supabase.get_authorized_by_jid("5534999945010@s.whatsapp.net") == _USER


def test_jid_sem_o_9_extra_encontra_usuario_com_9():
    """v2 manda 553499945010 (12 dígitos); o banco tem 5534999945010 (13)."""
    def fake(phone):
        return _USER if phone == "5534999945010" else None

    with patch("backend.services.supabase.get_authorized_by_phone", side_effect=fake):
        assert supabase.get_authorized_by_jid("553499945010@s.whatsapp.net") == _USER


def test_jid_com_o_9_extra_encontra_usuario_sem_9():
    outro = {"lid": "x@lid", "phone": "553499945010", "name": "Fulano"}

    def fake(phone):
        return outro if phone == "553499945010" else None

    with patch("backend.services.supabase.get_authorized_by_phone", side_effect=fake):
        assert supabase.get_authorized_by_jid("5534999945010@s.whatsapp.net") == outro


def test_jid_desconhecido_retorna_none():
    with patch("backend.services.supabase.get_authorized_by_phone", return_value=None):
        assert supabase.get_authorized_by_jid("5511888887777@s.whatsapp.net") is None


def test_jid_vazio_retorna_none():
    assert supabase.get_authorized_by_jid("") is None
