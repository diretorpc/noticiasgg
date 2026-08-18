from unittest.mock import patch

import httpx
import pytest

from backend.services import alert_checker

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET", f"http://api.scraperapi.com/?api_key={_CHAVE_FALSA}&premium=true&url=https://query1.finance.yahoo.com"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_collect_all_mascara_chave_de_market_que_vaza():
    """Ponta solta apontada na revisão 18/08/2026 (4ª rodada): market.collect()
    hoje NUNCA propaga uma exceção com a chave crua (cada fetch interno já se
    protege com sanitize_error), então não há vazamento vivo. Mas
    `_collect_all` catch com `str(e)` cru era o mesmo desenho frágil do achado
    3 — se um `market.collect()` futuro deixar escapar uma exceção sem
    mascarar, este catch é o próximo a herdar o furo. `errors.append` deste
    caminho vai pro WhatsApp do admin via notify_admin (run_checks:614+638),
    então o raio de exposição é maior que um log."""
    with patch("backend.services.alert_checker.market.collect",
               side_effect=_erro_com_chave_na_url()):
        data = alert_checker._collect_all()
    assert _CHAVE_FALSA not in data["market"]["erro"]
    assert "api_key=***" in data["market"]["erro"]


def test_check_eia_mascara_chave_de_erro_nao_config(monkeypatch):
    """eia.collect() hoje também nunca deixa a chave escapar (mascara por
    série internamente) — o ValueError de config é a única exceção que sobe
    crua, e não carrega a chave. Defesa em profundidade igual ao achado 3."""
    monkeypatch.setattr(alert_checker.eia, "collect",
                        lambda: (_ for _ in ()).throw(_erro_com_chave_na_url()))
    errors: list[str] = []
    alert_checker._check_eia([{"phone": "553400000000", "name": "A"}], errors)
    assert errors
    assert _CHAVE_FALSA not in errors[0]
    assert "api_key=***" in errors[0]


def test_check_news_mascara_chave_de_erro_de_coleta():
    """news.collect() hoje não deixa a chave escapar (NewsAPI usa `continue`
    em vez de raise_for_status — achado 2), mas se isso mudar, este catch
    precisa estar pronto."""
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", side_effect=_erro_com_chave_na_url()):
        errors: list[str] = []
        alert_checker._check_news([{"phone": "553400000000", "name": "A"}], errors=errors)
    assert errors
    assert _CHAVE_FALSA not in errors[0]
    assert "api_key=***" in errors[0]
