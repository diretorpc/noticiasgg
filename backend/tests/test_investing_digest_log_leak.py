import logging
from unittest.mock import patch

import httpx
import pytest

from backend.services import investing_digest, alert_checker

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


def test_logger_exception_nao_vaza_chave_na_cadeia_de_causa(monkeypatch, caplog):
    """Achado 1, revisão 18/08/2026 (4ª rodada): `raise RuntimeError(...) from e`
    em investing_calendar.fetch() mascarava o RuntimeError, mas preservava
    __cause__ apontando pra HTTPStatusError original. `logger.exception` (chamado
    em investing_digest.run()) formata a cadeia INTEIRA — "The above exception was
    the direct cause..." — reimprimindo a URL crua com a chave. Este teste captura
    a saída de logger.exception via caplog, não só o str() do RuntimeError."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])
    monkeypatch.setattr(alert_checker, "notify_admin", lambda *a, **k: None)

    with patch("backend.collectors.investing_calendar.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_http_com_chave()
        with caplog.at_level(logging.ERROR, logger="noticiasgg.investing"):
            investing_digest.run()

    assert _CHAVE_FALSA not in caplog.text, (
        "a chave apareceu no traceback completo do logger.exception "
        "(cadeia __cause__ não foi cortada)"
    )
    assert "api_key=***" in caplog.text
