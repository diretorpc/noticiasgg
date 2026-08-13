import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from backend.services import alert_checker

# Coração do pipeline de alertas: 47 testes que rodavam FORA do portão do CI.
# Três deles chamavam o Supabase de produção por esquecerem de simular
# get_recent_sent_titles — o resultado dependia dos dados do dia. Corrigido, o
# arquivo é determinístico (medido: zero conexões) e entra no portão.
pytestmark = pytest.mark.unit

_ADMIN = "5534999945010"
_RECIPIENTS = [{"phone": "5534999000001", "name": "A"}]


def test_notify_admin_envia_mensagem_de_erro():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set, \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["news: API limit reached"])
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == _ADMIN
    assert "news: API limit reached" in mock_send.call_args[0][1]
    mock_set.assert_called_once_with("system_error_alert")


def test_notify_admin_respeita_cooldown():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=False), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["news: API limit reached"])
    mock_send.assert_not_called()


def test_notify_admin_sem_admin_configurado_nao_quebra():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": "", "AUTHORIZED_NUMBER": ""}), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["erro qualquer"])
    mock_send.assert_not_called()


def test_notify_admin_lista_vazia_nao_envia():
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin([])
    mock_send.assert_not_called()


def test_run_checks_notifica_admin_quando_news_falha():
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.collectors.news.collect", side_effect=RuntimeError("NewsAPI 429")), \
         patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.notify_admin") as mock_notify:
        result = alert_checker.run_checks(test_mode=True)
    assert result["status"] == "ok"
    assert result["errors"] == ["news: NewsAPI 429"]
    mock_notify.assert_called_once_with(["news: NewsAPI 429"])


def test_run_checks_sem_recipients_notifica_admin():
    with patch("backend.services.alert_checker._get_recipients", return_value=[]), \
         patch("backend.services.alert_checker.notify_admin") as mock_notify:
        result = alert_checker.run_checks(test_mode=True)
    assert result["recipients"] == 0
    mock_notify.assert_called_once()
    assert "recipients" in mock_notify.call_args[0][0][0]


def test_check_news_respeita_cooldown_do_newsapi():
    def cooldown(rule_id, hours):
        return rule_id == "news_alert_global"  # global liberado, fetch NewsAPI em cooldown

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=cooldown), \
         patch("backend.collectors.news.collect", return_value=[]) as mock_collect, \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set:
        alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert mock_collect.call_args.kwargs["include_newsapi"] is False
    assert mock_collect.call_args.kwargs["include_ai"] is False
    mock_set.assert_not_called()


def test_check_news_marca_fetch_do_newsapi():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[]) as mock_collect, \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set:
        alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert mock_collect.call_args.kwargs["include_newsapi"] is True
    mock_set.assert_called_once_with("newsapi_fetch")


_LIVE_BLOG_V1 = {"titulo": "AO VIVO guerra: EUA atacam", "fonte": "Le Monde", "url": "https://lemonde.fr/live/guerra"}
_LIVE_BLOG_V2 = {"titulo": "AO VIVO guerra: Irã responde", "fonte": "Le Monde", "url": "https://lemonde.fr/live/guerra"}


def test_check_news_dedup_por_url_bloqueia_live_blog():
    """Título novo + mesma URL (live blog) = já enviada, não classifica de novo."""
    import hashlib
    url_id = hashlib.md5(_LIVE_BLOG_V2["url"].encode()).hexdigest()

    def is_sent(news_id):
        return news_id == url_id  # URL marcada na primeira atualização

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_LIVE_BLOG_V2]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", side_effect=is_sent), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 0
    mock_anthropic.return_value.messages.create.assert_not_called()


def _fake_classifier_resp(score: int):
    payload = f'{{"score": {score}, "categoria": "GEOPOLÍTICA", "titulo_pt": "t", "resumo": "r"}}'
    return type("R", (), {"content": [type("C", (), {"text": payload})()]})()


def _vistas_e_nova():
    """5 notícias já enviadas na frente da lista + 1 nova atrás."""
    import hashlib
    vistas = [{"titulo": f"velha {i}", "fonte": f"Fonte{i}", "url": f"https://ex.com/{i}"} for i in range(5)]
    nova = {"titulo": "nova relevante", "fonte": "FonteNova", "url": "https://ex.com/nova"}
    ja_vistos = set()
    for a in vistas:
        ja_vistos.add(hashlib.md5(a["titulo"].encode()).hexdigest())
        ja_vistos.add(hashlib.md5(a["url"].encode()).hexdigest())
    return vistas + [nova], ja_vistos


def test_check_news_varre_alem_das_ja_vistas():
    """Regressão do caso real de 21/07/2026: o corte `articles[:limit]` acontecia
    ANTES do dedup, então 5 notícias já vistas consumiam a cota e a notícia nova
    da posição 6 nunca era classificada — em silêncio, sem log nenhum."""
    artigos, ja_vistos = _vistas_e_nova()

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=artigos), \
         patch("backend.services.alert_checker.supabase.is_news_sent", side_effect=lambda i: i in ja_vistos), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_classifier_resp(1)
        alert_checker._check_news(_RECIPIENTS, test_mode=False)

    create = mock_anthropic.return_value.messages.create
    assert create.call_count == 1, "a notícia nova (posição 6) tinha que ser classificada"
    enviado = create.call_args.kwargs["messages"][0]["content"]
    assert "nova relevante" in enviado


def test_check_news_respeita_teto_de_classificacoes():
    """Guarda de custo: mesmo com muita notícia nova, classifica no máximo `limit` (5)."""
    artigos = [{"titulo": f"nova {i}", "fonte": f"F{i}", "url": f"https://ex.com/n{i}"} for i in range(12)]

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=artigos), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_classifier_resp(1)
        alert_checker._check_news(_RECIPIENTS, test_mode=False)

    assert mock_anthropic.return_value.messages.create.call_count == 5


def test_check_news_cooldown_por_fonte():
    """Fonte em cooldown de 3h → artigo pulado antes de classificar."""
    def cooldown(rule_id, hours):
        if rule_id == "news_source_le_monde":
            return False  # Le Monde em cooldown
        return True

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=cooldown), \
         patch("backend.collectors.news.collect", return_value=[_LIVE_BLOG_V1]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 0
    mock_anthropic.return_value.messages.create.assert_not_called()


def test_check_news_envio_marca_cooldown_da_fonte():
    """Alerta enviado → set_alert_triggered da fonte é chamado."""
    fake_resp = type("R", (), {"content": [type("C", (), {"text": '{"score": 9, "categoria": "GEOPOLÍTICA", "titulo_pt": "t", "resumo": "r"}'})()]})()

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_LIVE_BLOG_V1]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set, \
         patch("backend.services.alert_checker.whatsapp.send_message"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = fake_resp
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 1
    rule_ids = [c.args[0] for c in mock_set.call_args_list]
    assert "news_source_le_monde" in rule_ids
    assert "news_alert_global" in rule_ids


def test_run_checks_timeout_em_news_nao_aborta_execucao():
    """Timeout não tratado dentro de _check_news vira erro reportado, não fatal."""
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": {}}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom", return_value=0), \
         patch("backend.services.alert_checker._check_eia", return_value=0), \
         patch("backend.services.alert_checker._check_news",
               side_effect=httpx.ReadTimeout("The read operation timed out")), \
         patch("backend.services.alert_checker.notify_admin") as mock_notify:
        result = alert_checker.run_checks(test_mode=False)
    assert result["status"] == "ok"
    assert any("news" in e and "timed out" in e for e in result["errors"])
    mock_notify.assert_called_once()


def test_run_checks_timeout_em_eia_nao_impede_news():
    """Timeout do Supabase dentro de _check_eia não derruba os checks seguintes."""
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": {}}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom", return_value=0), \
         patch("backend.services.alert_checker._check_eia",
               side_effect=httpx.ReadTimeout("The read operation timed out")), \
         patch("backend.services.alert_checker._check_news", return_value=2) as mock_news, \
         patch("backend.services.alert_checker.notify_admin"):
        result = alert_checker.run_checks(test_mode=False)
    assert result["status"] == "ok"
    assert result["alerts_sent"] == 2
    mock_news.assert_called_once()
    assert any("eia" in e for e in result["errors"])


def test_run_checks_timeout_em_copom_nao_impede_demais():
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": {}}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom",
               side_effect=httpx.ReadTimeout("The read operation timed out")), \
         patch("backend.services.alert_checker._check_eia", return_value=0) as mock_eia, \
         patch("backend.services.alert_checker._check_news", return_value=0), \
         patch("backend.services.alert_checker.notify_admin"):
        result = alert_checker.run_checks(test_mode=False)
    assert result["status"] == "ok"
    mock_eia.assert_called_once()
    assert any("copom" in e for e in result["errors"])


def test_run_checks_eia_config_error_continua_reportado():
    """ValueError (EIA_API_KEY ausente) segue sendo reportado como erro de config."""
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": {}}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom", return_value=0), \
         patch("backend.services.alert_checker._check_eia",
               side_effect=ValueError("EIA_API_KEY não configurada")), \
         patch("backend.services.alert_checker._check_news", return_value=0), \
         patch("backend.services.alert_checker.notify_admin"):
        result = alert_checker.run_checks(test_mode=False)
    assert result["status"] == "ok"
    assert any("eia" in e and "EIA_API_KEY" in e for e in result["errors"])


def test_notify_admin_envia_mesmo_com_cooldown_indisponivel():
    """Se o Supabase cair, o canal de último recurso falha aberto: envia mesmo assim."""
    with patch.dict(os.environ, {"REPLY_TO_NUMBER": _ADMIN}), \
         patch("backend.services.alert_checker._cooldown_ok",
               side_effect=httpx.ReadTimeout("The read operation timed out")), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send:
        alert_checker.notify_admin(["supabase: fora do ar"])
    mock_send.assert_called_once()


_MARKET = {
    "cambio": {
        "USD/BRL": {"preco": 5.42, "variacao_pct": 1.85},
        "DXY (Índice Dólar)": {"preco": 104.2, "variacao_pct": -0.3},
    },
    "bolsas": {
        "IBOVESPA": {"preco": 132000.0, "variacao_pct": None},  # sem variação → fora
    },
}


def test_market_snapshot_formata_variacoes():
    snap = alert_checker._market_snapshot(_MARKET)
    assert "USD/BRL: +1.85% hoje" in snap
    assert "DXY (Índice Dólar): -0.30% hoje" in snap
    assert "IBOVESPA" not in snap  # variacao_pct None não entra


def test_market_snapshot_vazio_para_none():
    assert alert_checker._market_snapshot(None) == ""
    assert alert_checker._market_snapshot({}) == ""


def test_build_classifier_input_completo():
    article = {"titulo": "OPEC+ cuts output", "resumo": "Production cut of 1M bpd announced"}
    out = alert_checker._build_classifier_input(
        article, "USD/BRL: +1.85% hoje", ["Fed mantém juros"]
    )
    assert "<titulo>OPEC+ cuts output</titulo>" in out
    assert "<resumo>Production cut of 1M bpd announced</resumo>" in out
    assert "<contexto_mercado>" in out and "USD/BRL: +1.85% hoje" in out
    assert "<ja_enviadas>" in out and "- Fed mantém juros" in out


def test_build_classifier_input_minimo():
    article = {"titulo": "OPEC+ cuts output", "resumo": None}
    out = alert_checker._build_classifier_input(article, "", [])
    hoje = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")
    assert out == f"<hoje>{hoje}</hoje>\n<titulo>OPEC+ cuts output</titulo>"


def test_build_classifier_input_injeta_data_de_hoje():
    """Sem a data de hoje o classificador chuta o ano de memória (escreveu '2024' em ago/2026)."""
    hoje = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")
    out = alert_checker._build_classifier_input({"titulo": "Hottest July on record"}, "", [])
    assert f"<hoje>{hoje}</hoje>" in out


def test_build_classifier_input_injeta_publicado_em():
    """publicado_em é coletado pelo news.py e era descartado aqui. Sai convertido para BRT."""
    article = {"titulo": "Hottest July on record", "publicado_em": "2026-08-10T14:23:00+00:00"}
    out = alert_checker._build_classifier_input(article, "", [])
    assert "<publicado_em>2026-08-10 11:23</publicado_em>" in out


def test_build_classifier_input_publicado_em_no_mesmo_fuso_de_hoje():
    """UTC cru fazia o modelo ler 'notícia publicada amanhã' entre 21h e meia-noite BRT."""
    article = {"titulo": "X", "publicado_em": "2026-08-11T01:30:00Z"}
    out = alert_checker._build_classifier_input(article, "", [])
    assert "<publicado_em>2026-08-10 22:30</publicado_em>" in out


def test_to_brt_meia_noite_mostra_so_a_data():
    """Fonte que carimba 00:00 GMT quer dizer 'só sei o dia'. Converter para BRT
    jogava para 21h do dia ANTERIOR — notícia do dia 18 aparecia como dia 17."""
    assert alert_checker._to_brt("2026-06-18T00:00:00+00:00") == "2026-06-18"


def test_to_brt_hora_real_continua_convertendo():
    """Guarda de regressão: 00:00 é o único caso especial."""
    assert alert_checker._to_brt("2026-06-18T00:01:00+00:00") == "2026-06-17 21:01"
    assert alert_checker._to_brt("2026-06-18T14:23:00+00:00") == "2026-06-18 11:23"


def test_to_brt_data_absurda_nao_estoura():
    """dt.astimezone estourava OverflowError fora do try com data de ano 1.
    À meia-noite o atalho da data resolve; fora dela, o try tem que segurar."""
    assert alert_checker._to_brt("0001-01-01T00:00:00+00:00") == "0001-01-01"
    assert alert_checker._to_brt("0001-01-01T01:00:00+00:00") == "0001-01-01T01:00:00+00:00"


def test_build_classifier_input_publicado_em_ilegivel_nao_quebra():
    """Feed com data em formato inesperado: passa cru, truncado, sem estourar."""
    article = {"titulo": "X", "publicado_em": "ontem de manha"}
    out = alert_checker._build_classifier_input(article, "", [])
    assert "<publicado_em>ontem de manha</publicado_em>" in out


def test_build_classifier_input_sem_publicado_em_mantem_hoje():
    """Feed RSS sem data legível: a tag some, mas <hoje> continua ancorando o ano."""
    hoje = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")
    for article in ({"titulo": "X"}, {"titulo": "X", "publicado_em": None}):
        out = alert_checker._build_classifier_input(article, "", [])
        assert "<publicado_em>" not in out
        assert f"<hoje>{hoje}</hoje>" in out


def test_classifier_prompt_tem_contrato_v2():
    """Smoke: prompt define cadeias causais, anti-injection nas novas tags e os campos novos."""
    p = alert_checker._NEWS_CLASSIFIER_SYSTEM
    assert "CADEIAS DE TRANSMISSÃO" in p
    assert "<resumo>" in p and "<ja_enviadas>" in p and "<contexto_mercado>" in p
    # as tags de data também precisam estar declaradas: o "dentro dessas tags" da
    # defesa anti-injection só cobre o que a frase de apresentação lista.
    assert "<hoje>" in p and "<publicado_em>" in p
    assert '"ativos"' in p and '"direcao"' in p and '"duplicada"' in p


def _fake_resp(payload: str):
    return type("R", (), {"content": [type("C", (), {"text": payload})()]})()


_RESP_V2 = '{"score": 9, "categoria": "OFERTA/CLIMA", "titulo_pt": "OPEC+ corta produção", "resumo": "r", "ativos": ["petróleo", "diesel"], "direcao": "alta", "duplicada": false}'
_RESP_DUP = '{"score": 9, "categoria": "OFERTA/CLIMA", "titulo_pt": "OPEC+ corta produção", "resumo": "r", "ativos": ["petróleo"], "direcao": "alta", "duplicada": true}'
_ARTIGO = {"titulo": "OPEC+ cuts output", "fonte": "Reuters", "url": "https://r.com/1", "resumo": "Cut of 1M bpd"}


def test_check_news_duplicada_marca_e_nao_envia():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=["OPEC+ corta produção de petróleo"]), \
         patch("backend.services.alert_checker.supabase.mark_news_sent") as mock_mark, \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send, \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_resp(_RESP_DUP)
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 0
    mock_send.assert_not_called()
    assert mock_mark.called  # marcada para não reclassificar


def test_check_news_mensagem_inclui_impacto():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send, \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_resp(_RESP_V2)
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 1
    msg = mock_send.call_args[0][1]
    assert "📈 Impacto provável: alta" in msg
    assert "petróleo" in msg


def test_check_news_persiste_titulo_traduzido():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.mark_news_sent") as mock_mark, \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_resp(_RESP_V2)
        alert_checker._check_news(_RECIPIENTS, test_mode=False)
    titles = [c.kwargs.get("title") for c in mock_mark.call_args_list]
    assert "OPEC+ corta produção" in titles


def test_check_news_user_message_usa_builder():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=["Fed mantém juros"]), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_resp(_RESP_V2)
        alert_checker._check_news(_RECIPIENTS, test_mode=False, market_data=_MARKET)
    user_content = mock_anthropic.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "<resumo>Cut of 1M bpd</resumo>" in user_content
    assert "<contexto_mercado>" in user_content
    assert "- Fed mantém juros" in user_content


def test_check_news_falha_em_recent_titles_nao_quebra():
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles",
               side_effect=httpx.ReadTimeout("The read operation timed out")), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.whatsapp.send_message") as mock_send, \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = _fake_resp(_RESP_V2)
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 1  # dedup degrada, alerta não morre
    mock_send.assert_called_once()


def test_run_checks_passa_market_para_news():
    market = {"cambio": {"USD/BRL": {"preco": 5.4, "variacao_pct": 1.2}}}
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": market}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom", return_value=0), \
         patch("backend.services.alert_checker._check_eia", return_value=0), \
         patch("backend.services.alert_checker._check_news", return_value=0) as mock_news, \
         patch("backend.services.alert_checker.notify_admin"):
        alert_checker.run_checks(test_mode=False)
    assert mock_news.call_args.kwargs["market_data"] == market


def test_broadcast_zero_entregas_reporta_erro():
    errors: list[str] = []
    with patch("backend.services.alert_checker.whatsapp.send_message", side_effect=RuntimeError("down")):
        sent = alert_checker._broadcast("msg", _RECIPIENTS, errors)
    assert sent == 0
    assert errors == ["whatsapp: broadcast entregou 0/1"]


def test_broadcast_com_sucesso_nao_reporta_erro():
    errors: list[str] = []
    with patch("backend.services.alert_checker.whatsapp.send_message"):
        sent = alert_checker._broadcast("msg", _RECIPIENTS, errors)
    assert sent == 1
    assert errors == []


def test_corte_de_nota_e_trava_calibrados_para_o_volume():
    """Com 20 fontes vivas (antes era 1), o volume saltou de ~5,4 para 64 alertas/dia
    — medido em 12/08/2026, contra a média de 06-10/08. Amostra de 20 classificações
    de 126 notícias reais mostrou nota quase BIMODAL — o classificador decide "isto é
    4" ou "isto é 7", quase nada no meio (1 caso de nota 5 em 126). O corte no 5 cai
    nesse vazio e por isso é estável. Estes dois números são o freio; medir antes:
      python -m backend.tools.medir_volume_alertas"""
    assert alert_checker._NEWS_MIN_SCORE == 5
    assert alert_checker._NEWS_GLOBAL_COOLDOWN_HOURS == 1.0


def test_nota_abaixo_do_corte_nao_envia():
    resp = '{"score": 4, "categoria": "BRASIL", "titulo_pt": "t", "resumo": "r", "ativos": ["soja"], "direcao": "alta", "duplicada": false}'
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._broadcast", return_value=1) as mock_bc:
        mock_cli.return_value.messages.create.return_value = _fake_resp(resp)
        enviados = alert_checker._check_news(_RECIPIENTS)
    assert enviados == 0
    mock_bc.assert_not_called()


def _resp_nota(score: int, titulo_pt: str):
    p = (f'{{"score": {score}, "categoria": "MACRO", "titulo_pt": "{titulo_pt}", '
         f'"resumo": "r", "ativos": ["soja"], "direcao": "alta", "duplicada": false}}')
    return type("R", (), {"content": [type("C", (), {"text": p})()]})()


_TRES_CANDIDATAS = [
    {"titulo": "media", "fonte": "F1", "url": "https://e.com/1"},
    {"titulo": "a mais forte", "fonte": "F2", "url": "https://e.com/2"},
    {"titulo": "fraca", "fonte": "F3", "url": "https://e.com/3"},
]


def _rodar_com_notas(notas: list[int]):
    """Roda _check_news com uma nota por artigo, na ordem. Devolve (enviados, whatsapp, mark_sent)."""
    from unittest.mock import MagicMock
    respostas = [_resp_nota(n, f"pt {n}") for n in notas]
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent") as mock_mark, \
         patch("backend.collectors.news.collect", return_value=list(_TRES_CANDIDATAS)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.side_effect = respostas
        mock_wa.send_message.return_value = True
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
    return enviados, mock_wa, mock_mark


def test_manda_apenas_a_de_maior_nota_da_rodada():
    """A trava global é conferida uma vez por rodada, não por mensagem, então o laço
    despejava até 5 de uma vez (medido 13/08/2026: 64 alertas/dia em rajadas).
    Agora classifica as candidatas, compara e manda só a mais forte."""
    enviados, wa, _ = _rodar_com_notas([6, 8, 5])
    assert wa.send_message.call_count == 1, "só UMA mensagem por rodada"
    assert "pt 8" in wa.send_message.call_args[0][1], "tem que ser a de maior nota"
    assert enviados == 1


def test_candidatas_perdedoras_nao_sao_queimadas():
    """Marcar a perdedora como enviada a mataria para sempre (is_news_sent não tem
    prazo). Ela tem que poder competir na próxima rodada."""
    _, _, mark = _rodar_com_notas([6, 8, 5])
    marcados = [c.args[0] for c in mark.call_args_list]
    import hashlib
    vencedora = hashlib.md5("a mais forte".encode()).hexdigest()
    perdedora = hashlib.md5("media".encode()).hexdigest()
    assert vencedora in marcados
    assert perdedora not in marcados, "a perdedora de nota 6 não pode morrer"


def test_abaixo_do_corte_continua_sendo_queimada():
    """Comportamento antigo preservado: nota baixa é marcada para não voltar."""
    import hashlib
    _, wa, mark = _rodar_com_notas([2, 7, 1])
    marcados = [c.args[0] for c in mark.call_args_list]
    assert hashlib.md5("media".encode()).hexdigest() in marcados
    assert hashlib.md5("fraca".encode()).hexdigest() in marcados
    assert wa.send_message.call_count == 1


def test_nenhuma_candidata_nao_envia_nada():
    enviados, wa, _ = _rodar_com_notas([2, 1, 2])
    assert enviados == 0
    wa.send_message.assert_not_called()


def test_empate_de_nota_ganha_a_mais_recente():
    """35-45% das rodadas empatam no topo (medido em 126 notícias reais: 49 tiraram 7).
    O desempate decide quase metade dos envios, então tem que estar preso por teste:
    a lista chega ordenada por recência e o max() devolve o primeiro."""
    _, wa, _ = _rodar_com_notas([7, 7, 5])
    assert "pt 7" in wa.send_message.call_args[0][1]
    assert wa.send_message.call_count == 1


def test_nao_queima_a_noticia_quando_a_entrega_falha():
    """Evolution fora do ar: _broadcast devolve 0. Marcar como enviada mataria a
    notícia para sempre (is_news_sent não tem prazo) e ainda entraria no
    get_recent_sent_titles, fazendo as próximas sobre o mesmo fato virarem
    'duplicada' de algo que o dono nunca viu."""
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent") as mock_mark, \
         patch("backend.collectors.news.collect", return_value=[dict(_TRES_CANDIDATAS[0])]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._broadcast", return_value=0):
        mock_cli.return_value.messages.create.return_value = _resp_nota(8, "forte")
        enviados = alert_checker._check_news(_RECIPIENTS)
    assert enviados == 0
    mock_mark.assert_not_called(), "sem entrega, a notícia continua disponível"
