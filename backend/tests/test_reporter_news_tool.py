from unittest.mock import patch

import pytest

from backend.services import reporter

# Arquivo sem nenhuma chamada de rede: o Supabase entra por `patch.object`.
pytestmark = pytest.mark.unit


def _linha(**extra) -> dict:
    base = {
        "news_id": "abc123",
        "titulo_pt": "Milho dos EUA perde qualidade",
        "titulo_original": "Corn Rated 61% Good to Excellent",
        "fonte": "Reuters",
        "feed": "google_news",
        "url": "https://news.google.com/rss/articles/CBMiXYZ",
        "url_publisher": "https://reuters.com/markets/corn-usda",
        "url_final": "https://reuters.com/markets/corn-usda-2026",
        "categoria": "OFERTA/CLIMA",
        "resumo": "Condicao boa/excelente cai para 61%.",
        "resumo_fonte": "Corn conditions slipped.",
        "direcao": "alta",
        "score": 7,
        "ativos": ["milho"],
        "publicado_em": "2026-08-18T10:00:00+00:00",
        "sent_at": "2026-08-18T13:05:00+00:00",
    }
    base.update(extra)
    return base


def test_ferramenta_get_sent_news_esta_declarada():
    nomes = [t["name"] for t in reporter.describe_config()["tools"]]
    assert "get_sent_news" in nomes


def test_get_sent_news_devolve_o_log():
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [_linha()]}
    ) as m:
        resultado = reporter._get_sent_news(horas=48)
    m.assert_called_once_with(hours=48, limit=20)
    assert resultado["janela_horas"] == 48
    assert resultado["consulta_ok"] is True
    assert "aviso" not in resultado
    noticia = resultado["noticias"][0]
    assert noticia["titulo"] == "Milho dos EUA perde qualidade"
    assert noticia["fonte"] == "Reuters"
    assert noticia["publicado_em"] == "2026-08-18T10:00:00+00:00"
    assert noticia["sent_at"] == "2026-08-18T13:05:00+00:00"
    assert noticia["resumo"] == "Condicao boa/excelente cai para 61%."


def test_get_sent_news_entrega_o_link_do_jornal_e_nao_o_do_google():
    """Defeito 1 de 19/08/2026: o link do Google Noticias devolve 403 no clique
    e o agente repassava ele. `read_article` recebe esta url."""
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [_linha()]}
    ):
        resultado = reporter._get_sent_news()
    noticia = resultado["noticias"][0]
    assert noticia["url"] == "https://reuters.com/markets/corn-usda-2026"
    assert "news.google.com" not in str(resultado)


def test_get_sent_news_cai_para_o_publisher_e_depois_para_a_url_bruta():
    sem_final = _linha(url_final=None)
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [sem_final]}
    ):
        r1 = reporter._get_sent_news()
    assert r1["noticias"][0]["url"] == "https://reuters.com/markets/corn-usda"

    so_bruta = _linha(url_final=None, url_publisher=None, url="https://exemplo.com/x")
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [so_bruta]}
    ):
        r2 = reporter._get_sent_news()
    assert r2["noticias"][0]["url"] == "https://exemplo.com/x"


def test_get_sent_news_sem_registro_avisa_em_vez_de_devolver_vazio():
    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": []}):
        resultado = reporter._get_sent_news(horas=72)
    assert resultado["noticias"] == []
    assert resultado["consulta_ok"] is True
    assert "aviso" in resultado


def test_leitura_indisponivel_nao_pode_virar_negativa_autoritaria():
    """Achado A5 (revisao 18/08/2026): `get_news_log` devolve lista vazia tanto
    para 'dia calmo' quanto para 'a consulta falhou'. Achatar os dois faz o
    agente dizer 'conferi, nao te mandei nada' sem ter conferido nada."""
    with patch.object(
        reporter.supabase,
        "get_news_log",
        return_value={"itens": [], "aviso": "registro indisponivel"},
    ):
        resultado = reporter._get_sent_news(horas=72)
    assert resultado["noticias"] == []
    assert resultado["consulta_ok"] is False
    aviso = resultado["aviso"].lower()
    assert "nenhum alerta" not in aviso, "aviso afirma ausencia sem ter conferido"

    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": []}):
        calmo = reporter._get_sent_news(horas=72)
    assert calmo["aviso"] != resultado["aviso"], "os dois casos precisam falar diferente"


def test_janela_absurda_nao_e_ecoada_de_volta_para_o_modelo():
    """O `horas` vem de texto de WhatsApp interpretado pelo modelo. O Supabase
    trava o valor na consulta; se o eco nao travar junto, o agente anuncia uma
    janela que nunca foi consultada."""
    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": []}):
        resultado = reporter._get_sent_news(horas=999999)
    assert resultado["janela_horas"] == 24 * 90

    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": []}):
        texto = reporter._get_sent_news(horas="nao sou numero")
    assert texto["janela_horas"] == 72


def test_prompts_mandam_consultar_o_log_antes_de_buscar():
    cfg = reporter.describe_config()
    for chave in ("system_chat", "system_market"):
        prompt = cfg[chave]
        assert "get_sent_news" in prompt, f"{chave} nao cita a ferramenta"
        assert "essa notícia" in prompt.lower(), f"{chave} nao cobre o gatilho"
