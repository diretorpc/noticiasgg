import pytest

from backend.collectors import crypto
from backend.tests.conftest import coleta_unica


# --- Simulação do CoinGecko: cobre o que a API real não deixa provocar sob demanda ---

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return _FakeResp(self._payload)


def _moeda(coin_id, nome, simbolo, preco, variacao):
    return {
        "id": coin_id,
        "name": nome,
        "symbol": simbolo,
        "current_price": preco,
        "price_change_percentage_24h": variacao,
        "total_volume": 1_000,
    }


@pytest.fixture
def coingecko_responde(monkeypatch):
    """Faz o coletor enxergar a resposta que o teste mandar, sem sair para a rede."""
    def _instalar(payload):
        monkeypatch.setattr(crypto.httpx, "Client", lambda *a, **k: _FakeClient(payload))
    return _instalar


@pytest.mark.unit
def test_variacao_ausente_nao_vira_zero(coingecko_responde):
    """Sem variação, o coletor não pode AFIRMAR que a moeda ficou estável.
    'Não sei' publicado como '0,00%' é dado errado, não dado ausente."""
    coingecko_responde([_moeda("bitcoin", "Bitcoin", "btc", 60_000.0, None)])
    btc = crypto.collect()[0]
    assert btc["variacao_24h_pct"] is None


@pytest.mark.unit
def test_variacao_zero_real_e_preservada(coingecko_responde):
    """O contrapeso do teste acima: zero MEDIDO continua sendo zero."""
    coingecko_responde([_moeda("bitcoin", "Bitcoin", "btc", 60_000.0, 0.0)])
    btc = crypto.collect()[0]
    assert btc["variacao_24h_pct"] == 0.0


@pytest.mark.unit
def test_variacao_presente_e_arredondada(coingecko_responde):
    coingecko_responde([_moeda("ethereum", "Ethereum", "eth", 3_000.0, -1.23456)])
    eth = crypto.collect()[0]
    assert eth["variacao_24h_pct"] == -1.23


def conferir_moeda(moeda: dict) -> None:
    """Contrato de uma moeda. Usado tanto contra o CoinGecko real quanto
    contra respostas simuladas — a mesma regra vale nos dois casos."""
    assert "nome" in moeda
    assert "simbolo" in moeda
    # Stablecoins (ex: USDT) não têm preco_usd, só volume
    if moeda["simbolo"] == "USDT":
        volume = moeda["volume_24h_usd"]
        assert isinstance(volume, (int, float)) and not isinstance(volume, bool), \
            f"volume_24h_usd deveria ser número, veio {volume!r}"
        assert volume > 0, f"volume_24h_usd deveria ser positivo, veio {volume!r}"
    else:
        preco = moeda["preco_usd"]
        assert isinstance(preco, (int, float)) and not isinstance(preco, bool), \
            f"preco_usd deveria ser número, veio {preco!r}"
        assert preco > 0, f"preco_usd deveria ser positivo, veio {preco!r}"
        # None é legítimo: significa "não sei". O que não pode é vir texto/ausente.
        variacao = moeda["variacao_24h_pct"]
        assert variacao is None or (
            isinstance(variacao, (int, float)) and not isinstance(variacao, bool)
        ), f"variacao_24h_pct deveria ser número ou None, veio {variacao!r}"


@pytest.mark.unit
def test_conferencia_rejeita_preco_nulo():
    """A conferência tem que olhar o VALOR, não só a existência da chave:
    preço nulo chega ao WhatsApp como preço em branco."""
    with pytest.raises(AssertionError):
        conferir_moeda({"nome": "Bitcoin", "simbolo": "BTC",
                        "preco_usd": None, "variacao_24h_pct": 1.0})


@pytest.mark.unit
def test_conferencia_rejeita_volume_nulo_do_usdt():
    """O USDT tem UM campo só — o volume — e ele sai no WhatsApp como
    'USDT – Volume 24h: US$ XX bilhões'. Era justamente o campo que a
    conferência não olhava."""
    with pytest.raises(AssertionError):
        conferir_moeda({"nome": "Tether", "simbolo": "USDT", "volume_24h_usd": None})


@pytest.mark.unit
def test_conferencia_aceita_moeda_integra():
    """Contrapeso: dado bom não pode ser reprovado."""
    conferir_moeda({"nome": "Bitcoin", "simbolo": "BTC",
                    "preco_usd": 60_000.0, "variacao_24h_pct": -1.2})
    conferir_moeda({"nome": "Bitcoin", "simbolo": "BTC",
                    "preco_usd": 60_000.0, "variacao_24h_pct": None})
    conferir_moeda({"nome": "Tether", "simbolo": "USDT", "volume_24h_usd": 10})


# --- Contrato contra o CoinGecko REAL: uma chamada por rodada, reaproveitada ---

resposta_crypto = coleta_unica("/api/collectors/crypto")


def test_crypto_status_200(resposta_crypto):
    assert resposta_crypto.status_code == 200


def test_crypto_schema(resposta_crypto):
    body = resposta_crypto.json()
    assert "data" in body
    assert "collected_at" in body


def test_crypto_retorna_lista(resposta_crypto):
    data = resposta_crypto.json()["data"]
    assert isinstance(data, list)
    assert len(data) > 0


def test_crypto_campos_obrigatorios(resposta_crypto):
    for moeda in resposta_crypto.json()["data"]:
        conferir_moeda(moeda)


def test_crypto_traz_as_tres_moedas(resposta_crypto):
    """A conferência acima olha o que VEIO; esta olha o que FALTOU. O coletor
    omite a moeda ausente em silêncio (`if usdt:` em crypto.py), então sem isto
    a linha 'USDT – Volume 24h' sumiria do WhatsApp sem ninguém reclamar."""
    simbolos = {m["simbolo"] for m in resposta_crypto.json()["data"]}
    assert simbolos >= {"BTC", "ETH", "USDT"}, f"faltou moeda: {simbolos}"
