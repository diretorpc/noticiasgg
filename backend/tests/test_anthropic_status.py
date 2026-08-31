"""O incidente de 31/08/2026: o saldo da conta Anthropic zerou e NADA avisou.

`/api/health` respondia `keys: ok` porque so conferia se a variavel EXISTE, e o
cron de alertas caia num `except Exception: continue`, logando um aviso por
noticia a cada 15 minutos, para sempre. O agente ficou mudo e o painel ficou
verde. Estes testes sao o que impede isso de voltar calado.
"""
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from backend.services import anthropic_status, health

pytestmark = pytest.mark.unit


def _erro(classe, texto):
    """Erro do SDK Anthropic como ele chega de verdade."""
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(400, request=req, json={"error": {"message": texto}})
    return classe(texto, response=resp, body=None)


# ── separar o que adianta repetir do que nao adianta ──────────────────────────

def test_saldo_esgotado_e_permanente_e_diz_o_que_fazer():
    e = _erro(anthropic.BadRequestError,
              "Your credit balance is too low to access the Anthropic API.")
    motivo = anthropic_status.erro_permanente(e)
    assert motivo is not None
    assert "saldo" in motivo.lower()
    assert "console.anthropic.com" in motivo, "o aviso tem que dizer ONDE resolver"


def test_chave_invalida_e_permanente():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    e = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx.Response(401, request=req, json={}), body=None)
    assert anthropic_status.erro_permanente(e) is not None


def test_400_comum_NAO_e_alarme():
    """`BadRequestError` normalmente e erro de programacao (payload torto). Tratar
    todo 400 como 'chame o dono' treina a pessoa a ignorar o aviso."""
    e = _erro(anthropic.BadRequestError, "messages: at least one message is required")
    assert anthropic_status.erro_permanente(e) is None


def test_falha_passageira_NAO_e_permanente():
    for e in (TimeoutError("estourou"), ConnectionError("caiu"), RuntimeError("529")):
        assert anthropic_status.erro_permanente(e) is None


# ── a sonda ───────────────────────────────────────────────────────────────────

def test_sonda_gasta_o_minimo_possivel():
    criado = {}

    def fake_create(**kw):
        criado.update(kw)
        return MagicMock()

    cliente = MagicMock()
    cliente.messages.create = fake_create
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        assert anthropic_status.sondar() == {"status": "ok"}
    assert criado["max_tokens"] == 1, "a sonda nao pode gerar texto"
    assert "haiku" in criado["model"], "sonda em Sonnet custaria 3x sem motivo"


def test_sonda_com_saldo_zerado_vira_ERROR_com_o_motivo():
    cliente = MagicMock()
    cliente.messages.create = MagicMock(side_effect=_erro(
        anthropic.BadRequestError, "Your credit balance is too low"))
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        r = anthropic_status.sondar()
    assert r["status"] == "error"
    assert "saldo" in r["message"].lower()


def test_sonda_com_falha_passageira_vira_WARN_e_nao_error():
    cliente = MagicMock()
    cliente.messages.create = MagicMock(side_effect=TimeoutError("estourou"))
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        r = anthropic_status.sondar()
    assert r["status"] == "warn", "529 momentaneo nao e problema do dono"


# ── o health nao pode mais mentir ─────────────────────────────────────────────

def _completo(sonda):
    with patch.object(health.anthropic_status, "sondar", return_value=sonda), \
         patch.object(health, "collect_status",
                      return_value={"status": "ok", "checks": {"keys": {"status": "ok", "faltando": []}},
                                    "checked_at": "t"}), \
         patch("backend.collectors.news.source_health",
               return_value={"vivas": 20, "total": 20, "mortas": []}):
        return health.collect_status_completo()


def test_o_cenario_EXATO_de_31_08_saldo_zerado_com_painel_verde():
    """`keys: ok` continua verdade — a variavel esta la. E exatamente por isso
    que ela nao avisava nada."""
    r = _completo({"status": "error", "message": "saldo da Anthropic esgotado"})
    assert r["checks"]["keys"]["status"] == "ok", "a chave EXISTE, isso nao mudou"
    assert r["checks"]["anthropic"]["status"] == "error"
    assert r["status"] == "error", "o cabecalho continuou dizendo ok"


def test_tudo_bem_continua_dizendo_ok():
    r = _completo({"status": "ok"})
    assert r["status"] == "ok"


def test_o_boletim_do_whatsapp_MOSTRA_a_linha():
    """De nada adianta o check existir se a mensagem que chega no celular nao o
    cita — foi assim que o dono descobriu o incidente sozinho, sem o boletim."""
    r = _completo({"status": "error", "message": "saldo da Anthropic esgotado"})
    texto = health.format_digest(r)
    assert "Anthropic" in texto
    assert "saldo" in texto.lower()
    assert "❌" in texto


def test_o_endpoint_publico_NAO_sonda():
    """`GET /api/health` e publico e sem senha. Uma chamada PAGA ali e convite
    para esvaziarem o saldo por voce — mesma razao pela qual a medicao das
    fontes ja morava no `completo`."""
    with patch.object(health.anthropic_status, "sondar") as sonda, \
         patch.object(health, "_check_keys", return_value={"status": "ok", "faltando": []}), \
         patch.multiple("backend.services.health.supabase",
                        get_recent_sent_titles=lambda *a, **k: [],
                        count_recent_broadcasts=lambda *a, **k: 0,
                        count_recent_alert_messages=lambda *a, **k: 0,
                        get_news_log=lambda *a, **k: {"itens": [], "truncado": False},
                        get_polls=lambda *a, **k: []), \
         patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        health.collect_status()
    sonda.assert_not_called()


# ── o cron para de engolir ────────────────────────────────────────────────────

def _rodar_check_news(erro, artigos):
    """`_check_news` pelo caminho real, com o classificador estourando `erro`."""
    from backend.services import alert_checker

    cliente = MagicMock()
    cliente.messages.create = MagicMock(side_effect=erro)
    errors: list[str] = []
    alvo = "backend.services.alert_checker"
    with patch(f"{alvo}._cooldown_ok", return_value=True), \
         patch(f"{alvo}.Anthropic", return_value=cliente), \
         patch(f"{alvo}.supabase.set_alert_triggered"), \
         patch(f"{alvo}.supabase.is_news_sent", return_value=False), \
         patch(f"{alvo}.supabase.get_recent_sent_titles", return_value=[]), \
         patch(f"{alvo}._market_snapshot", return_value=""), \
         patch("backend.collectors.news.collect", return_value=artigos):
        alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}],
                                  errors=errors)
    return errors, cliente.messages.create.call_count


_ARTIGOS = [
    {"titulo": f"Noticia {i}", "fonte": "Reuters", "url": f"https://ex.com/{i}",
     "publicado_em": "2026-08-31T10:00:00+00:00"}
    for i in range(5)
]


def test_o_cron_de_alertas_avisa_o_dono_em_vez_de_seguir_calado():
    """Antes: `except Exception: logger.warning(); continue` — um aviso por
    noticia, a cada 15 minutos, para sempre, e ninguem sabia. O motivo tem que
    chegar em `errors`, que e o que vira mensagem no WhatsApp do dono."""
    erro = _erro(anthropic.BadRequestError, "Your credit balance is too low")
    errors, chamadas = _rodar_check_news(erro, _ARTIGOS)
    assert any("anthropic" in e for e in errors), f"nao avisou ninguem: {errors}"
    assert any("saldo" in e.lower() for e in errors)


def test_saldo_zerado_para_o_laco_em_vez_de_insistir_em_todas():
    """Nao adianta classificar as outras quatro: todas vao falhar igual, e cada
    tentativa e uma chamada a mais numa conta que ja esta sem saldo."""
    erro = _erro(anthropic.BadRequestError, "Your credit balance is too low")
    _, chamadas = _rodar_check_news(erro, _ARTIGOS)
    assert chamadas == 1, f"insistiu {chamadas}x com o saldo zerado"


def test_falha_passageira_numa_noticia_NAO_derruba_as_outras():
    """O contrario tambem tem que valer: um timeout numa noticia nao pode parar
    o cron inteiro nem acordar o dono."""
    errors, chamadas = _rodar_check_news(TimeoutError("estourou"), _ARTIGOS)
    assert errors == [], f"acordou o dono por um timeout: {errors}"
    assert chamadas > 1, "parou o laco por uma falha passageira"
