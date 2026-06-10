import os
from unittest.mock import patch

import httpx

from backend.services import alert_checker

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
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.Anthropic") as mock_anthropic:
        total = alert_checker._check_news(_RECIPIENTS, test_mode=False)
    assert total == 0
    mock_anthropic.return_value.messages.create.assert_not_called()


def test_check_news_cooldown_por_fonte():
    """Fonte em cooldown de 3h → artigo pulado antes de classificar."""
    def cooldown(rule_id, hours):
        if rule_id == "news_source_le_monde":
            return False  # Le Monde em cooldown
        return True

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=cooldown), \
         patch("backend.collectors.news.collect", return_value=[_LIVE_BLOG_V1]), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
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
    assert out == "<titulo>OPEC+ cuts output</titulo>"


def test_classifier_prompt_tem_contrato_v2():
    """Smoke: prompt define cadeias causais, anti-injection nas novas tags e os campos novos."""
    p = alert_checker._NEWS_CLASSIFIER_SYSTEM
    assert "CADEIAS DE TRANSMISSÃO" in p
    assert "<resumo>" in p and "<ja_enviadas>" in p and "<contexto_mercado>" in p
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
