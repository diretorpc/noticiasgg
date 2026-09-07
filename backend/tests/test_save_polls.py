import httpx
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.services import supabase

# Arquivo sem nenhuma chamada de rede: o cliente Supabase é substituído por um
# transporte falso do httpx. Marcador coloca o arquivo no portão do CI.
pytestmark = pytest.mark.unit

client = TestClient(app)

_POLL = {"instituto": "Quaest", "turno": 1, "data_pesquisa": "2026-09-01",
         "candidatos": [{"nome": "A", "pct": 40}], "fonte_url": "https://x"}


def _fake_client(status_code: int) -> httpx.Client:
    def handler(request):
        return httpx.Response(status_code, json=[])
    return httpx.Client(base_url="http://fake/rest/v1", transport=httpx.MockTransport(handler))


@pytest.mark.unit
def test_rota_save_polls_nao_existe_mais():
    """Rota era resto da era n8n e ficava aberta na internet sem token."""
    r = client.post("/api/save-polls", json={"data": [_POLL]})
    assert r.status_code == 404


@pytest.mark.unit
def test_save_polls_levanta_erro_quando_banco_rejeita(monkeypatch):
    monkeypatch.setattr(supabase, "_client", lambda: _fake_client(400))
    with pytest.raises(httpx.HTTPStatusError):
        supabase.save_polls([_POLL])


@pytest.mark.unit
def test_save_polls_nao_levanta_quando_banco_aceita(monkeypatch):
    monkeypatch.setattr(supabase, "_client", lambda: _fake_client(201))
    supabase.save_polls([_POLL])


@pytest.mark.unit
def test_save_polls_grava_as_demais_quando_uma_falha_e_levanta_no_fim(monkeypatch):
    """Uma pesquisa rejeitada não pode descartar as seguintes: o cache é o
    fallback do relatório quando o scraping falha."""
    tentativas = []

    def handler(request):
        tentativas.append(request)
        return httpx.Response(400 if len(tentativas) == 1 else 201, json=[])

    monkeypatch.setattr(supabase, "_client", lambda: httpx.Client(
        base_url="http://fake/rest/v1", transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        supabase.save_polls([_POLL, _POLL, _POLL])
    assert len(tentativas) == 3
