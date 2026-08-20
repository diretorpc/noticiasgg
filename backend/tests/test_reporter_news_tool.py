from unittest.mock import MagicMock, patch

import pytest

from backend.services import reporter

# Arquivo sem nenhuma chamada de rede: o Supabase e o Anthropic entram por patch.
pytestmark = pytest.mark.unit


def _linha(**extra) -> dict:
    base = {
        "news_id": "abc123",
        "titulo_pt": "Milho dos EUA perde qualidade",
        "titulo_original": "Corn Rated 61% Good to Excellent",
        "fonte": "Reuters",
        "feed": "google_news",
        "url": "https://news.google.com/rss/articles/CBMiXYZ",
        "url_publisher": "https://energynow.ca",
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


class _Bloco:
    """Bloco de resposta do SDK Anthropic. Classe de verdade, nao MagicMock:
    o laco de despacho testa `hasattr(block, "text")`, e MagicMock responde
    `True` para qualquer atributo, mascarando exatamente o que se quer medir."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _resposta(blocos, stop_reason="end_turn"):
    r = MagicMock()
    r.content = blocos
    r.stop_reason = stop_reason
    return r


# ── a ferramenta existe e devolve o registro ──────────────────────────────────

def test_ferramenta_get_sent_news_esta_declarada():
    nomes = [t["name"] for t in reporter.describe_config()["tools"]]
    assert "get_sent_news" in nomes


def test_get_sent_news_devolve_o_log():
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [_linha()]}
    ) as m:
        resultado = reporter._get_sent_news(horas=48)
    m.assert_called_once_with(hours=48, limit=20, phone=None)
    assert resultado["janela_horas"] == 48
    assert resultado["consulta_ok"] is True
    assert "aviso" not in resultado
    assert "truncado" not in resultado
    noticia = resultado["noticias"][0]
    assert noticia["titulo"] == "Milho dos EUA perde qualidade"
    assert noticia["fonte"] == "Reuters"
    assert noticia["publicado_em"] == "2026-08-18T10:00:00+00:00"
    assert noticia["sent_at"] == "2026-08-18T13:05:00+00:00"
    assert noticia["resumo"] == "Condicao boa/excelente cai para 61%."


# ── qual link vai para o modelo ───────────────────────────────────────────────

def test_entrega_o_link_do_jornal_e_nao_o_do_google():
    """Defeito 1 de 19/08/2026: o link do Google Noticias devolve 403 no clique
    e o agente repassava ele. E esta url que vai para o `read_article`."""
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": [_linha()]}
    ):
        resultado = reporter._get_sent_news()
    assert resultado["noticias"][0]["url"] == "https://reuters.com/markets/corn-usda-2026"
    assert "news.google.com" not in str(resultado)


def test_url_publisher_e_dominio_pelado_e_nunca_vira_link_da_materia():
    """Achado 2 do Apolo (20/08/2026): `url_publisher` do RSS e o dominio
    (`https://energynow.ca`), nao a matéria — `web_search._url_canonica` ja
    dizia isso. Entregá-lo faz o `read_article` ler o MENU da capa e devolver
    aquilo como se fosse o artigo: sem erro, sem log, conteúdo de outra coisa."""
    linha = _linha(url_final=None)  # sobra url do Google + url_publisher dominio
    assert reporter._link_da_materia(linha) == ""
    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": [linha]}):
        resultado = reporter._get_sent_news()
    # AUSENTE, nao `""` (achado 14): todo o resto do payload ensina ao modelo que
    # campo que falta e "nao tenho", e uma chave vazia no meio contradiz a licao.
    assert "url" not in resultado["noticias"][0]
    assert "energynow" not in str(resultado)


def test_url_bruta_de_feed_normal_continua_valendo():
    """So o link do Google sai fora. Os outros feeds trazem a matéria no `url`
    e perder isso seria pior que o defeito que estamos consertando."""
    linha = _linha(url_final=None, url="https://reuters.com/markets/corn-usda")
    assert reporter._link_da_materia(linha) == "https://reuters.com/markets/corn-usda"


def test_lista_cheia_sem_o_sinal_do_supabase_nao_inventa_o_corte():
    """O reporter REPASSA o sinal, nao deduz por `len(itens)` — quem sabe que
    cortou e quem aplicou o teto (achado 11 do Apolo)."""
    itens = [_linha(news_id=f"n{i}") for i in range(reporter._LIMITE_NOTICIAS)]
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": itens, "truncado": False}
    ):
        resultado = reporter._get_sent_news()
    assert "truncado" not in resultado


def test_os_dois_caminhos_de_link_concordam():
    """A mensagem do commit anterior afirmava paridade entre `_resumir_noticia`
    e `_format_anchored_news` — e era falso: o caminho ancorado ainda caía no
    link do Google (achado 5 do Apolo). Este teste e o que torna a afirmacao
    verificavel em vez de decorativa."""
    for linha in (_linha(), _linha(url_final=None), _linha(url_final=None, url="")):
        link = reporter._link_da_materia(linha)
        bloco = reporter._format_anchored_news(linha)
        assert f"url: {link}\n" in bloco


# ── os tres desfechos: achou, dia calmo, consulta falhou ──────────────────────

def test_sem_registro_avisa_em_vez_de_devolver_vazio():
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
    assert "nenhum alerta" not in resultado["aviso"].lower()

    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": []}):
        calmo = reporter._get_sent_news(horas=72)
    assert calmo["aviso"] != resultado["aviso"], "os dois casos precisam falar diferente"


def test_lista_cheia_declara_o_corte_e_ate_onde_enxergou():
    """Achado 1 do Apolo (medido em producao, 20/08/2026): com 25 alertas em 72h
    e `limit=20`, 5 ficam de fora e nada avisava. O modelo lia 'consulta_ok +
    nao esta na lista' e negava ter enviado — o A5 voltando pela porta do
    truncamento, agora com carimbo de consulta bem-sucedida."""
    itens = [_linha(news_id=f"n{i}", sent_at=f"2026-08-20T{23 - i:02d}:00:00+00:00")
             for i in range(reporter._LIMITE_NOTICIAS)]
    with patch.object(
        reporter.supabase, "get_news_log", return_value={"itens": itens, "truncado": True}
    ):
        resultado = reporter._get_sent_news(horas=720)
    assert resultado["truncado"] is True
    assert resultado["cobertura_desde"] == itens[-1]["sent_at"]
    assert "cobertura_desde" in resultado["aviso"]


def test_lista_incompleta_nao_se_declara_truncada():
    itens = [_linha(news_id=f"n{i}") for i in range(reporter._LIMITE_NOTICIAS - 1)]
    with patch.object(reporter.supabase, "get_news_log", return_value={"itens": itens}):
        resultado = reporter._get_sent_news()
    assert "truncado" not in resultado
    assert "cobertura_desde" not in resultado


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


# ── fiacao: o laco de tool_use realmente chama a funcao ───────────────────────

def test_o_laco_despacha_a_ferramenta_de_verdade():
    """Achado 8 do Apolo: o nome da ferramenta vive em DOIS literais separados
    (a declaracao e a string do `elif`). Se um derivar do outro, `describe_config`
    segue verde, os testes de unidade seguem verdes, e a producao passa a
    devolver `{"erro": "ferramenta desconhecida"}` calada. Nenhum teste do
    repositorio exercia este laco."""
    pedido = _Bloco(type="tool_use", name="get_sent_news", id="tu_1", input={"horas": 24})
    final = _Bloco(type="text", text="segundo o registro, mandei isso ontem.")
    cliente = MagicMock()
    cliente.messages.create.side_effect = [
        _resposta([pedido], stop_reason="tool_use"),
        _resposta([final]),
    ]
    with patch("backend.services.reporter.Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}), \
         patch.object(reporter, "_validate_and_fix", lambda texto, *a, **k: texto), \
         patch.object(
             reporter.supabase, "get_news_log", return_value={"itens": [_linha()]}
         ) as consulta:
        saida = reporter.generate_report("me fala dessa noticia que voce mandou", sections={},
                                        user_phone="5534999945010")

    consulta.assert_called_once_with(hours=24, limit=20, phone="5534999945010")
    assert saida == "segundo o registro, mandei isso ontem."
    devolvido = cliente.messages.create.call_args_list[1].kwargs["messages"][-1]["content"][0]
    assert devolvido["tool_use_id"] == "tu_1"
    assert "ferramenta desconhecida" not in devolvido["content"]
    assert "Milho dos EUA perde qualidade" in devolvido["content"]


def test_relatorio_diario_nao_recebe_a_ferramenta():
    """Achado 7 do Apolo: no cron de relatorio nao existe 'usuario perguntando
    sobre uma noticia'. Oferecer a ferramenta ali so convida o modelo a reciclar
    alerta velho como noticia do dia."""
    cliente = MagicMock()
    cliente.messages.create.return_value = _resposta([_Bloco(type="text", text="ok")])
    with patch("backend.services.reporter.Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}), \
         patch.object(reporter, "_validate_and_fix", lambda texto, *a, **k: texto), \
         patch.object(reporter, "_collect_all", return_value={"market": {"ok": True}}):
        reporter.generate_report("relatorio", sections=None)
    nomes = [t["name"] for t in cliente.messages.create.call_args.kwargs["tools"]]
    assert "get_sent_news" not in nomes

    cliente.messages.create.reset_mock()
    with patch("backend.services.reporter.Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}), \
         patch.object(reporter, "_validate_and_fix", lambda texto, *a, **k: texto):
        reporter.generate_report("oi", sections={})
    nomes = [t["name"] for t in cliente.messages.create.call_args.kwargs["tools"]]
    assert "get_sent_news" in nomes


# ── as regras de prompt ───────────────────────────────────────────────────────

def test_prompts_mandam_consultar_o_log_antes_de_buscar():
    cfg = reporter.describe_config()
    for chave in ("system_chat", "system_market"):
        prompt = cfg[chave]
        assert "get_sent_news" in prompt, f"{chave} nao cita a ferramenta"
        assert "essa notícia" in prompt.lower(), f"{chave} nao cobre o gatilho"


def test_prompts_cobrem_os_limites_do_registro():
    """As tres bordas onde o agente afirmaria o que nao conferiu: consulta que
    falhou, lista cortada, e a noticia que veio pelo relatorio diario (que nao
    entra nesta tabela — `log_sent_news` so e chamada pelo alert_checker)."""
    prompt = reporter.describe_config()["system_chat"]
    assert "consulta_ok" in prompt
    assert "truncado" in prompt and "cobertura_desde" in prompt
    assert "RELATÓRIO DIÁRIO" in prompt
    assert "<noticia_citada>" in prompt, "falta a excecao do caminho ancorado"
