import httpx
import pytest

from backend.services.secrets_mask import sanitize_error

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    """Simula o formato real de httpx.HTTPStatusError: `raise_for_status()`
    monta a mensagem incluindo a URL completa da requisição — e a chave de
    API vai no query string dela."""
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://exemplo.com"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_sanitize_error_mascara_api_key():
    saida = sanitize_error(_erro_com_chave_na_url())
    assert _CHAVE_FALSA not in saida
    assert "api_key=***" in saida


def test_sanitize_error_preserva_mensagem_sem_segredo():
    """Não deve mexer em erro que não carrega a chave — só o parâmetro
    api_key= é mascarado, o resto da mensagem passa intacto."""
    saida = sanitize_error(ValueError("timeout ao conectar em host.example.com"))
    assert saida == "timeout ao conectar em host.example.com"


@pytest.mark.parametrize("grafia", ["apiKey", "API_KEY", "apikey", "api-key", "Api_Key"])
def test_sanitize_error_mascara_qualquer_grafia_de_api_key(grafia):
    """Achado 2, revisão 18/08/2026 (4ª rodada): o regex só pegava `api_key=`
    minúsculo com underscore. A NewsAPI usa `apiKey=` (camelCase, 3 pontos de
    uso em news.py/politics_br.py) — não batia. Cobre as grafias plausíveis."""
    erro = ValueError(f"HTTP 500 para https://newsapi.org/v2/everything?{grafia}={_CHAVE_FALSA}&q=soja")
    saida = sanitize_error(erro)
    assert _CHAVE_FALSA not in saida
    assert f"{grafia}=***" in saida


def test_sanitize_error_preserva_grafia_original_no_grupo_capturado():
    """A substituição não normaliza a grafia do parâmetro — só apaga o valor.
    `apiKey=***`, não `api_key=***`, senão o log fica ilegível (o parâmetro
    real na URL era `apiKey`)."""
    saida = sanitize_error(ValueError(f"erro em ...?apiKey={_CHAVE_FALSA}&x=1"))
    assert "apiKey=***" in saida
    assert "api_key=***" not in saida


def test_sanitize_error_nao_come_aspa_de_fechamento():
    """Achado 7: quando api_key é o ÚLTIMO parâmetro e a URL está entre aspas
    (repr de exceção, JSON, etc.), `[^&\\s]*` comia a aspa de fechamento junto
    com o resto do valor. Não vaza nada, mas quebra a formatação do log."""
    saida = sanitize_error(ValueError(f'erro na url "https://x.com/?a=1&api_key={_CHAVE_FALSA}"'))
    assert _CHAVE_FALSA not in saida
    assert saida.endswith('api_key=***"')


def test_sanitize_error_duas_chaves_grafias_diferentes():
    """Duas ocorrências, grafias diferentes na mesma mensagem — ambas mascaradas."""
    erro = ValueError(f"api_key={_CHAVE_FALSA}&outro=1 e depois apiKey={_CHAVE_FALSA}")
    saida = sanitize_error(erro)
    assert _CHAVE_FALSA not in saida
    assert "api_key=***" in saida
    assert "apiKey=***" in saida
