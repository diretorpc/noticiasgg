import httpx
import pytest

from backend.collectors import indicators_br

pytestmark = pytest.mark.unit

_ClientReal = httpx.Client  # guardado antes do monkeypatch, senão a fábrica chama a si mesma


def _bcb_falso(_url, **_kw):
    def handler(request):
        if "sgs.432" in str(request.url):
            return httpx.Response(200, json=[{"data": "08/09/2026", "valor": "14.00"},
                                             {"data": "09/09/2026", "valor": "14.00"}])
        if "sgs.11/" in str(request.url):
            return httpx.Response(200, json=[{"data": "08/09/2026", "valor": "0.051660"},
                                             {"data": "09/09/2026", "valor": "0.051660"}])
        return httpx.Response(200, json=[{"data": "01/08/2026", "valor": "0.26"}])
    return _ClientReal(transport=httpx.MockTransport(handler))


@pytest.mark.unit
def test_selic_anual_vem_da_serie_432(monkeypatch):
    """A série 11 é a Selic DIÁRIA (~0,05). Rotulá-la '% a.a.' entregava
    0,05% ao relatório como dado válido. Meta Selic anual é a 432."""
    monkeypatch.setattr(indicators_br.httpx, "Client", lambda **kw: _bcb_falso(None, **kw))
    data = indicators_br.collect()
    selic = next(v for k, v in data.items() if "SELIC" in k and "a.a." in k)
    assert selic["valor"] == 14.0


@pytest.mark.unit
def test_toda_serie_rotulada_ao_ano_tem_valor_plausivel(monkeypatch):
    monkeypatch.setattr(indicators_br.httpx, "Client", lambda **kw: _bcb_falso(None, **kw))
    for nome, ind in indicators_br.collect().items():
        if "a.a." in nome:
            assert 1 <= ind["valor"] <= 30, f"{nome}={ind['valor']} não parece taxa anual"
