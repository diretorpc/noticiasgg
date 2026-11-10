"""`user_preferences.sections`/`report_time` são campos MORTOS: o relatório diário sai
da grade `report_schedules` (`cron_report.py`), o chat usa `sections={}`, e o único
leitor era `send_report.py` (rota do n8n, desligado). Nenhuma tela nem resposta pode
mostrá-los ou gravá-los — a caixa "Seções do chat" do /me respondia "Salvo." sem
efeito, e o bot manda gente para lá desde o PR #37 (09/11/2026).

Arquivo sem rede: tudo via monkeypatch/mock. O marcador põe o arquivo no portão do CI.
"""
import inspect
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.main import app
from backend.services import auth, schedules, selflink, supabase

pytestmark = pytest.mark.unit

client = TestClient(app)
PHONE = "5534999945010"
COM_LINK = {"phone": PHONE, "selflink_token": "tok123", "use_new_report_engine": True}

_PRIV = ec.generate_private_key(ec.SECP256R1())


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_PRIV.public_key())


def _admin_headers():
    tok = jwt.encode({"sub": "u1", "aud": "authenticated", "email": "matheusmouro@hotmail.com",
                      "exp": int(time.time()) + 3600}, _PRIV, algorithm="ES256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def me_token():
    app.dependency_overrides[selflink.selflink_phone] = lambda: PHONE
    yield
    app.dependency_overrides.clear()


# ── Gravação: nenhum caminho consegue escrever o campo morto ─────────────────

def test_save_preferences_nao_aceita_mais_secoes_nem_horario():
    params = inspect.signature(supabase.save_preferences).parameters
    assert "sections" not in params
    assert "report_time" not in params


# ── /me ──────────────────────────────────────────────────────────────────────

def test_get_me_nao_devolve_secoes(monkeypatch, me_token):
    monkeypatch.setattr(supabase, "get_authorized_by_phone", lambda p: {"phone": p, "name": "M"})
    monkeypatch.setattr(schedules, "get_for_phone", lambda p: [])
    monkeypatch.setattr(supabase, "get_preferences",
                        lambda p: {"sections": {"market": True}, "report_time": "08:00",
                                   "tts_voice": "onyx"})
    body = client.get("/api/me?token=x").json()
    assert "sections" not in body
    assert "report_time" not in body
    assert body["audio"]["tts_voice"] == "onyx"


def test_put_me_com_secoes_de_pagina_velha_grava_so_o_audio(monkeypatch, me_token):
    """Aba aberta com a versão antiga do /me ainda manda `sections`: é ignorado."""
    monkeypatch.setattr(supabase, "get_preferences", lambda p: {"report_time": "08:00"})
    captured = {}
    monkeypatch.setattr(supabase, "save_preferences",
                        lambda phone, **kw: captured.update(phone=phone, **kw))
    r = client.put("/api/me?token=x", json={"sections": {"market": True},
                                            "audio_for_text": True, "tts_voice": "nova",
                                            "tts_speed": 0.85})
    assert r.status_code == 200
    assert captured["phone"] == PHONE
    assert "sections" not in captured and "report_time" not in captured
    assert captured["audio_for_text"] is True and captured["tts_speed"] == 0.85


@pytest.mark.parametrize("campo,valor", [
    ("tts_speed", 5.0), ("tts_speed", 0.1), ("tts_voice", "darth"),
    # Coerção do Pydantic padrão: `true` virava velocidade 1.0, "yes" virava True.
    ("tts_speed", True), ("tts_speed", "1"), ("audio_for_text", "yes"), ("audio_for_text", 1),
])
def test_put_me_recusa_audio_fora_da_faixa_sem_gravar(monkeypatch, me_token, campo, valor):
    """`tts_speed` 5.0 ia direto pro TTS (item 4 da fila, 09/11/2026). Mesma regra que
    o WhatsApp já aplica ao que o Haiku manda gravar."""
    chamadas = []
    monkeypatch.setattr(supabase, "save_preferences", lambda *a, **k: chamadas.append(k))
    r = client.put("/api/me?token=x", json={campo: valor})
    assert r.status_code == 422
    assert chamadas == []


# ── Painel admin ─────────────────────────────────────────────────────────────

def test_admin_lista_usuarios_sem_secoes_nem_horario():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.list_authorized", return_value=[{"phone": "5511", "name": "A"}]), \
         patch("backend.api.admin.supabase.get_preferences",
               return_value={"sections": {"market": True}, "report_time": "08:00", "tts_voice": "echo"}):
        r = client.get("/api/admin/users", headers=_admin_headers())
    prefs = r.json()["users"][0]["preferences"]
    assert "sections" not in prefs and "report_time" not in prefs
    assert prefs["tts_voice"] == "echo"


def test_admin_salvar_ignora_secoes_e_horario():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.save_preferences") as mock_save:
        r = client.post("/api/admin/user-prefs", headers=_admin_headers(),
                        json={"phone": "5511", "sections": {"market": True},
                              "report_time": "08:00", "tts_voice": "onyx"})
    assert r.status_code == 200
    kw = mock_save.call_args.kwargs
    assert "sections" not in kw and "report_time" not in kw
    assert kw["tts_voice"] == "onyx"


def test_admin_recusa_velocidade_fora_da_faixa():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.save_preferences") as mock_save:
        r = client.post("/api/admin/user-prefs", headers=_admin_headers(),
                        json={"phone": "5511", "tts_speed": 9})
    assert r.status_code == 422
    mock_save.assert_not_called()


# ── !ajustes ─────────────────────────────────────────────────────────────────

_PREFS_MORTAS = {"sections": {"market": True, "crypto": False}, "report_time": "08:00",
                 "tts_voice": "onyx", "tts_speed": 0.9, "audio_for_text": True}


def _resumo(monkeypatch, rows, user=COM_LINK, prefs=_PREFS_MORTAS):
    monkeypatch.setattr(schedules, "get_for_phone", lambda p: rows)
    return main._build_settings_summary(prefs, user)


def test_ajustes_nao_mostra_campo_morto(monkeypatch):
    texto = _resumo(monkeypatch, [])
    assert "Horário:" not in texto
    assert "Seções ativas" not in texto
    assert "08:00" not in texto
    assert "mercado" not in texto


def test_ajustes_mostra_a_grade_real(monkeypatch):
    rows = ([{"section": "commodities", "weekday": d, "hour": 8} for d in range(5)]
            + [{"section": "bolsas", "weekday": d, "hour": h} for d in (0, 2, 4) for h in (18, 8)])
    texto = _resumo(monkeypatch, rows)
    assert "• Commodities: seg a sex, 8h" in texto
    assert "• Bolsas: seg, qua e sex, 8h e 18h" in texto
    assert texto.index("Commodities") < texto.index("Bolsas")  # ordem do motor
    assert "Seções e horário mudam na sua página pessoal: " in texto
    assert "/me?token=tok123" in texto


def test_ajustes_agrupa_dias_com_horarios_diferentes(monkeypatch):
    rows = ([{"section": "noticias", "weekday": d, "hour": 7} for d in range(7)]
            + [{"section": "analise", "weekday": 5, "hour": 10},
               {"section": "analise", "weekday": 0, "hour": 9},
               {"section": "analise", "weekday": 1, "hour": 9}])
    texto = _resumo(monkeypatch, rows)
    assert "• Notícias: todo dia, 7h" in texto
    assert "• Análise: seg e ter, 9h; sáb, 10h" in texto


def test_ajustes_envio_desligado_nao_mostra_grade_que_nao_vale(monkeypatch):
    """O cron só manda para quem tem `use_new_report_engine` (cron_report.py:27).
    Grade salva com a chave desligada não chega a ninguém."""
    rows = [{"section": "commodities", "weekday": 0, "hour": 8}]
    texto = _resumo(monkeypatch, rows, user={**COM_LINK, "use_new_report_engine": False})
    assert "Envio desligado" in texto
    assert "Commodities" not in texto
    assert "Seções e horário mudam" not in texto
    assert "/me" not in texto and "tok123" not in texto  # nada contraditório sobra


def test_ajustes_ligado_sem_grade(monkeypatch):
    texto = _resumo(monkeypatch, [])
    assert "nenhuma seção está agendada" in texto
    assert "Seções e horário mudam" in texto


def test_ajustes_falha_ao_ler_grade_nao_inventa(monkeypatch):
    def _boom(p):
        raise RuntimeError("supabase fora")
    monkeypatch.setattr(schedules, "get_for_phone", _boom)
    texto = main._build_settings_summary(_PREFS_MORTAS, COM_LINK)
    assert "Não consegui carregar seus horários agora" in texto
    assert "nenhuma seção" not in texto and "desligado" not in texto.lower()
    assert "Voz: onyx" in texto  # o resto da resposta sai mesmo assim


def test_ajustes_sem_link_manda_pedir_ao_admin(monkeypatch):
    texto = _resumo(monkeypatch, [], user={"phone": PHONE, "use_new_report_engine": True})
    assert "Seções e horário mudam na sua página pessoal (peça o link ao admin)" in texto


def test_ajustes_ignora_secao_desconhecida_na_grade(monkeypatch):
    texto = _resumo(monkeypatch, [{"section": "polls_br", "weekday": 0, "hour": 8}])
    assert "polls_br" not in texto
    assert "nenhuma seção está agendada" in texto


def test_ajustes_conhece_toda_secao_do_motor():
    """Seção nova no motor sem nome no !ajustes sumiria calada da resposta."""
    from backend.services import report_prompts
    assert tuple(main._GRADE_LABELS) == report_prompts.SECTIONS


def test_put_me_aceita_velocidade_inteira_do_slider(monkeypatch, me_token):
    """O slider manda `1` (sem decimal) em 1.0: tipo estrito não pode recusar."""
    captured = {}
    monkeypatch.setattr(supabase, "save_preferences", lambda phone, **kw: captured.update(kw))
    assert client.put("/api/me?token=x", json={"tts_speed": 1}).status_code == 200
    assert captured["tts_speed"] == 1


def test_ajustes_ultima_linha_so_promete_voz_e_audio(monkeypatch):
    texto = _resumo(monkeypatch, [])
    assert 'Voz e áudio você muda aqui mesmo: "muda a voz para onyx"' in texto
    assert "Para alterar" not in texto
