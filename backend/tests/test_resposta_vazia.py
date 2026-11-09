"""O chat nunca devolve resposta vazia.

Medido em 09/11/2026 com o Sonnet real: 1 em 3 chamadas de "quero saber só do mercado
hoje" voltou `""` — e o webhook mandaria mensagem em branco. Dois caminhos davam isso:
o código pegava o PRIMEIRO bloco de texto mesmo vazio, e devolvia `""` calado quando a
resposta final não tinha texto nenhum. Ninguém registrava, então não dava para medir.

O cliente simulado RECUSA o que a API real recusa (provado pelo Apolo com chamada real,
1ª revisão): turno de assistente com texto vazio/só espaços, e `tool_use` sem o
`tool_result` correspondente. A 1ª versão passava no mock e falhava na API exatamente aí.
"""
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.services import reporter

pytestmark = pytest.mark.unit


def _texto(t):
    return SimpleNamespace(type="text", text=t)


def _ferramenta():
    return SimpleNamespace(type="tool_use", id="toolu_1", name="get_stock_data", input={})


def _resposta(*blocos, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=list(blocos))


class _RecusaDaApi(Exception):
    pass


class _Cliente:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.messages = self

    def create(self, **kw):
        self.chamadas.append(kw)
        for m in kw["messages"]:
            if m["role"] != "assistant" or not isinstance(m["content"], list):
                continue
            for b in m["content"]:
                if getattr(b, "type", None) == "text" and not (b.text or "").strip():
                    raise _RecusaDaApi("400 text content blocks must contain non-whitespace text")
                if getattr(b, "type", None) == "tool_use":
                    raise _RecusaDaApi("400 tool_use ids were found without tool_result blocks")
        return self.respostas.pop(0)


def _gera(respostas, agora=(0.0,)):
    cliente = _Cliente(respostas)
    relogio = iter(list(agora) + [agora[-1]] * 20)
    with patch.object(reporter, "Anthropic", return_value=cliente), \
         patch.object(reporter, "_validate_and_fix", lambda texto, *a, **k: texto), \
         patch.object(reporter.time, "monotonic", lambda: next(relogio)), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
        saida = reporter.generate_report("como tá o mercado?", sections={})
    return saida, cliente


def test_bloco_de_texto_vazio_antes_do_bom_nao_vira_resposta_vazia():
    saida, cliente = _gera([_resposta(_texto(""), _texto("Ibovespa +1,4%."))])
    assert saida == "Ibovespa +1,4%."
    assert len(cliente.chamadas) == 1


def test_sem_texto_faz_uma_chamada_extra_curta_sem_ferramentas(caplog):
    with caplog.at_level(logging.WARNING, logger="noticiasgg"):
        saida, cliente = _gera([_resposta(), _resposta(_texto("Dólar em R$ 5,51."))])
    assert saida == "Dólar em R$ 5,51."
    assert len(cliente.chamadas) == 2
    assert "tools" not in cliente.chamadas[1]
    assert cliente.chamadas[1]["max_tokens"] == reporter._MAX_TOKENS_CHAMADA_EXTRA
    assert any("sem texto" in r.getMessage() for r in caplog.records), "tem que ficar no log"


@pytest.mark.parametrize("bloco_inutil", [_texto(""), _texto("   "), _ferramenta()])
def test_extra_funciona_com_bloco_que_a_api_recusaria(bloco_inutil):
    """`[TextBlock("")]` e `[tool_use]` cortado por max_tokens: devolver isso como turno
    do assistente dava 400 e a extra NUNCA funcionava nesse formato."""
    saida, cliente = _gera([_resposta(bloco_inutil, stop="max_tokens"), _resposta(_texto("ok, fechei"))])
    assert saida == "ok, fechei"
    assert cliente.chamadas[1]["messages"][-1]["role"] == "user"


def test_extra_tambem_vazia_manda_mensagem_honesta():
    saida, _ = _gera([_resposta(_texto("   ")), _resposta()])
    assert saida == reporter._RESPOSTA_VAZIA
    assert saida.strip()


def test_sem_tempo_de_sobra_nao_faz_chamada_extra():
    """Perto do teto de 300 s da Vercel, a chamada extra estouraria e a pessoa ficaria
    sem nada. Vai direto a mensagem honesta."""
    saida, cliente = _gera([_resposta()], agora=(0.0, reporter._PRAZO_CHAMADA_EXTRA_S + 1))
    assert saida == reporter._RESPOSTA_VAZIA
    assert len(cliente.chamadas) == 1


def test_resposta_normal_nao_muda():
    saida, cliente = _gera([_resposta(_texto("Selic em 14%."))])
    assert saida == "Selic em 14%."
    assert len(cliente.chamadas) == 1


@pytest.mark.parametrize("gerado", ["", reporter._RESPOSTA_VAZIA])
def test_send_report_nao_manda_frase_de_chat_como_relatorio(gerado, monkeypatch):
    """"Pode mandar de novo?" não faz sentido num relatório que a pessoa não pediu
    (achado 4 do Apolo). Cai no texto do n8n, como já acontecia quando dava erro."""
    from backend.api.main import app
    monkeypatch.setenv("CRON_SECRET", "s")
    n8n = "Bom dia | 09/11/2026\n\nRelatório do n8n."
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"sections": {"market": True}, "report_time": None}), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.reporter.generate_report", return_value=gerado), \
         patch("backend.api.send_report.supabase.save_message"), \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        TestClient(app, headers={"x-cron-secret": "s"}).post(
            "/api/send-report", json={"number": "5534999945010", "textMessage": {"text": n8n}})
    enviado = mock_send.call_args.args[1]
    assert "Relatório do n8n" in enviado
    assert reporter._RESPOSTA_VAZIA not in enviado
