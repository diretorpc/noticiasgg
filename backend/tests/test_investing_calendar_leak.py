from unittest.mock import patch

import httpx
import pytest

from backend.collectors import investing_calendar

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_http_com_chave() -> Exception:
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://br.investing.com/economic-calendar/"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_fetch_http_error_nao_vaza_chave_e_nao_retenta(monkeypatch):
    """Achado extra (não estava na lista original): raise_for_status() não era
    pego pelo except (TimeoutException, ConnectError) de fetch() — subia cru
    até investing_digest.run(), que loga com logger.exception (vaza pro log),
    manda pro admin via notify_admin (vaza pro WhatsApp) e devolve em
    {"detail": str(e)} no corpo de /api/cron/investing (vaza na resposta HTTP)."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.investing_calendar.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_http_com_chave()
        with pytest.raises(RuntimeError) as exc_info:
            investing_calendar.fetch()

    # Erro HTTP (403/500) não melhora repetindo e gasta crédito do ScraperAPI
    # à toa — precisa continuar levantando na primeira tentativa.
    assert mock_client_cls.call_count == 1
    assert _CHAVE_FALSA not in str(exc_info.value)
    assert "api_key=***" in str(exc_info.value)
