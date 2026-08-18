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
