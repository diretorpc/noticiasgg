"""Lote 3 da review de 09/09: os dois caminhos que perdiam dado em silencio.

Arquivo sem nenhuma chamada de rede: MockTransport e patch do handle_request.
O marcador coloca o arquivo no portao do CI, que roda `pytest backend -m unit`.
"""
import json
import os
from unittest.mock import patch

import httpx
import pytest

import backend.services.supabase as supabase
from backend.api import main as api_main
from backend.services import summarizer

pytestmark = pytest.mark.unit

_ENV = {"SUPABASE_URL": "https://exemplo.supabase.co", "SUPABASE_KEY": "k"}
_ClientReal = httpx.Client


# -- A. A mensagem que sumia quando a reserva era repetida -------------------

def _transporte_claim(token_existente, status_post=409, linha_sumiu=False):
    """POST devolve conflito; GET devolve a linha ja gravada."""
    def handler(request):
        if request.method == "POST":
            return httpx.Response(status_post, json={})
        if linha_sumiu:
            return httpx.Response(200, json=[])
        linha = {"claim_token": token_existente}  # PostgREST devolve null, nao ausente
        return httpx.Response(200, json=[linha])
    return httpx.MockTransport(handler)


def _fixar_cliente(monkeypatch, transporte):
    monkeypatch.setattr(
        supabase, "_client",
        lambda: _ClientReal(base_url="http://fake/rest/v1", transport=transporte),
    )


@pytest.mark.unit
def test_conflito_com_o_proprio_token_significa_nossa_gravacao(monkeypatch):
    """O transporte repete o MESMO POST apos um timeout. O conflito que volta e
    contra a nossa propria linha: tratar como reenvio deixava a pergunta do
    usuario sem resposta para sempre."""
    capturado = {}

    def handler(request):
        if request.method == "POST":
            capturado["token"] = json.loads(request.content)["claim_token"]
            return httpx.Response(409, json={})
        return httpx.Response(200, json=[{"claim_token": capturado["token"]}])

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    assert supabase.claim_message("3EB0DB360B218B04C777E3") is True


@pytest.mark.unit
def test_conflito_com_token_de_outra_execucao_e_reenvio(monkeypatch):
    _fixar_cliente(monkeypatch, _transporte_claim("token-de-outra-execucao"))
    assert supabase.claim_message("3EB0DB360B218B04C777E3") is False


@pytest.mark.unit
def test_conflito_com_linha_antiga_sem_token_e_reenvio(monkeypatch):
    """Linhas gravadas antes da migration 011 nao tem token: sao reservas
    legitimas anteriores e continuam valendo como reenvio."""
    _fixar_cliente(monkeypatch, _transporte_claim(None))
    assert supabase.claim_message("3EB0DB360B218B04C777E3") is False


@pytest.mark.unit
def test_reserva_nova_continua_devolvendo_true(monkeypatch):
    _fixar_cliente(monkeypatch, _transporte_claim(None, status_post=201))
    assert supabase.claim_message("3EB0DB360B218B04C777E3") is True


@pytest.mark.unit
def test_conflito_com_linha_que_sumiu_processa_em_vez_de_calar(monkeypatch):
    """Depois de um 409 a linha existe, entao GET vazio e quase inalcancavel.
    Se acontecer, responder e o lado barato do erro."""
    _fixar_cliente(monkeypatch, _transporte_claim(None, linha_sumiu=True))
    assert supabase.claim_message("3EB0DB360B218B04C777E3") is True


@pytest.mark.unit
def test_cada_execucao_gera_um_token_novo(monkeypatch):
    """A trava inteira depende disto. Token de escopo de modulo faria o reenvio
    da Evolution, caindo no mesmo container quente, ver o proprio token e ser
    processado como mensagem nova - exatamente o bug que este lote mata."""
    tokens = []

    def handler(request):
        if request.method == "POST":
            tokens.append(json.loads(request.content)["claim_token"])
            return httpx.Response(201, json=[{}])
        return httpx.Response(200, json=[])

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    supabase.claim_message("MSG-A")
    supabase.claim_message("MSG-A")
    assert len(set(tokens)) == 2


@pytest.mark.unit
def test_sem_a_coluna_do_token_volta_ao_comportamento_antigo(monkeypatch):
    """Se o backend subir antes da migration 011, o INSERT com claim_token
    volta 400. Estourar ali faria o webhook processar TODO reenvio da Evolution
    como mensagem nova - o bug das tres respostas diferentes de 19/07. Com o
    recuo, a ordem entre migration e deploy deixa de importar."""
    corpos = []

    def handler(request):
        corpos.append(json.loads(request.content))
        if "claim_token" in corpos[-1]:
            return httpx.Response(400, json={
                "code": "PGRST204",
                "message": "Could not find the 'claim_token' column"})
        return httpx.Response(201, json=[{}])

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    assert supabase.claim_message("MSG-A") is True
    assert len(corpos) == 2


@pytest.mark.unit
def test_sem_a_coluna_do_token_duplicata_continua_sendo_descartada(monkeypatch):
    def handler(request):
        corpo = json.loads(request.content)
        if "claim_token" in corpo:
            return httpx.Response(400, json={"code": "PGRST204", "message": "x"})
        return httpx.Response(409, json={})

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    assert supabase.claim_message("MSG-A") is False


@pytest.mark.unit
def test_o_corte_do_delete_inclui_a_ultima_mensagem_resumida(monkeypatch):
    """lte, nao lt: sem o 'igual', a ultima resumida fica para tras e volta a
    ser resumida em toda rodada."""
    capturado = {}

    def handler(request):
        capturado["url"] = str(request.url)
        return httpx.Response(204)

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    supabase.delete_history_until("555", "2026-09-10T10:00:00+00:00")
    assert "created_at=lte." in capturado["url"]


@pytest.mark.unit
def test_timeout_seguido_de_conflito_nao_descarta_a_mensagem():
    """Cenario real ponta a ponta, exercitando o _RetryTransport de verdade:
    o INSERT grava, a resposta se perde, o transporte repete e recebe o
    conflito causado pela primeira tentativa."""
    estado = {"posts": 0, "token": None}

    def fake_handle(self, request):
        if request.method == "POST":
            estado["posts"] += 1
            estado["token"] = json.loads(request.content)["claim_token"]
            if estado["posts"] == 1:
                raise httpx.ReadTimeout("resposta perdida", request=request)
            return httpx.Response(409, request=request, json={})
        return httpx.Response(200, request=request,
                              json=[{"claim_token": estado["token"]}])

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        assert supabase.claim_message("3EB0DB360B218B04C777E3") is True
    assert estado["posts"] == 2


# -- B. O historico que evaporava quando o resumo falhava --------------------

@pytest.mark.unit
def test_resumo_que_falhou_devolve_none_e_nao_o_resumo_antigo():
    """Devolver o resumo anterior fazia a falha parecer sucesso, e quem chama
    apagava as mensagens antigas em seguida."""
    with patch.object(summarizer, "Anthropic") as fake:
        fake.return_value.messages.create.side_effect = RuntimeError("Haiku fora")
        assert summarizer.summarize([{"role": "user", "content": "oi"}], "resumo velho") is None


@pytest.mark.unit
def test_resumo_vazio_tambem_devolve_none():
    bloco = type("B", (), {"text": "   "})()
    with patch.object(summarizer, "Anthropic") as fake:
        fake.return_value.messages.create.return_value = type("R", (), {"content": [bloco]})()
        assert summarizer.summarize([{"role": "user", "content": "oi"}], None) is None


def _historico(n: int) -> list[dict]:
    return [{"role": "user", "content": f"m{i}",
             "created_at": f"2026-09-10T10:{i:02d}:00+00:00"} for i in range(n)]


@pytest.mark.unit
def test_falha_no_resumo_preserva_o_historico_inteiro(monkeypatch):
    chamadas = []
    monkeypatch.setattr(api_main.supabase, "count_history", lambda p: 22)
    monkeypatch.setattr(api_main.supabase, "get_history_for_summary",
                        lambda p, keep_recent, limit, total: _historico(16))
    monkeypatch.setattr(api_main.supabase, "get_summary", lambda p: "resumo velho")
    monkeypatch.setattr(summarizer, "summarize", lambda msgs, existing: None)
    monkeypatch.setattr(api_main.supabase, "save_summary",
                        lambda p, s: chamadas.append("save"))
    monkeypatch.setattr(api_main.supabase, "delete_history_until",
                        lambda p, c: chamadas.append("delete"))
    api_main._maybe_summarize("555")
    assert chamadas == []


@pytest.mark.unit
def test_apaga_exatamente_o_que_foi_resumido(monkeypatch):
    """Antes o corte era 'tudo menos as 6 mais recentes', o que levava junto
    mensagens mais velhas que o lote e que nunca foram lidas."""
    capturado = {}
    velhas = _historico(3)
    monkeypatch.setattr(api_main.supabase, "count_history", lambda p: 30)
    monkeypatch.setattr(api_main.supabase, "get_history_for_summary",
                        lambda p, keep_recent, limit, total: velhas)
    monkeypatch.setattr(api_main.supabase, "get_summary", lambda p: None)
    monkeypatch.setattr(summarizer, "summarize", lambda msgs, existing: "resumo novo")
    monkeypatch.setattr(api_main.supabase, "save_summary",
                        lambda p, s: capturado.update(resumo=s))
    monkeypatch.setattr(api_main.supabase, "delete_history_until",
                        lambda p, c: capturado.update(corte=c))
    api_main._maybe_summarize("555")
    assert capturado["resumo"] == "resumo novo"
    assert capturado["corte"] == velhas[-1]["created_at"]


@pytest.mark.unit
def test_o_resumidor_nao_recebe_o_created_at(monkeypatch):
    """created_at serve para o corte do delete, nao para o prompt."""
    vistas = {}
    monkeypatch.setattr(api_main.supabase, "count_history", lambda p: 30)
    monkeypatch.setattr(api_main.supabase, "get_history_for_summary",
                        lambda p, keep_recent, limit, total: _historico(2))
    monkeypatch.setattr(api_main.supabase, "get_summary", lambda p: None)
    monkeypatch.setattr(summarizer, "summarize",
                        lambda msgs, existing: vistas.update(msgs=msgs) or "ok")
    monkeypatch.setattr(api_main.supabase, "save_summary", lambda p, s: None)
    monkeypatch.setattr(api_main.supabase, "delete_history_until", lambda p, c: None)
    api_main._maybe_summarize("555")
    assert all("created_at" not in m for m in vistas["msgs"])


@pytest.mark.unit
def test_busca_as_mensagens_mais_antigas_e_nao_as_recentes(monkeypatch):
    capturado = {}

    def handler(request):
        capturado.setdefault("urls", []).append(str(request.url))
        if "select=id" in str(request.url):
            return httpx.Response(200, json=[], headers={"content-range": "0-0/30"})
        return httpx.Response(200, json=_historico(3))

    _fixar_cliente(monkeypatch, httpx.MockTransport(handler))
    supabase.get_history_for_summary("555", keep_recent=6, limit=50)
    url = [u for u in capturado["urls"] if "created_at" in u][-1]
    assert "order=created_at.asc" in url
    assert "select=role,content,created_at" in url
    # 30 no total menos as 6 recentes: o limite protege as recentes de virarem
    # cutoff do delete. Sem esta asserção, ignorar keep_recent passa no portão.
    assert "limit=24" in url


# O encoding do cutoff no DELETE mora em test_supabase.py, junto com os irmãos
# (`test_delete_history_until_encoda_cutoff_timestamp`) — não duplicar aqui.
