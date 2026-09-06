import os
import re
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from backend.services import alert_checker

# Coração do pipeline de alertas: os testes deste arquivo rodavam FORA do portão do CI.
# Três deles chamavam o Supabase de produção por esquecerem de simular
# get_recent_sent_titles — o resultado dependia dos dados do dia. Corrigido, o
# arquivo é determinístico (medido: zero conexões) e entra no portão.
pytestmark = pytest.mark.unit

# Referência ao `_capture_conteudo` de VERDADE, capturada no IMPORT do módulo —
# antes de qualquer `patch()` de teste rodar. `_sem_news_log` (fixture autouse
# abaixo) troca `alert_checker._capture_conteudo` por um stub em TODO teste
# deste arquivo; os testes de reaproveitamento da camada 1 precisam da função
# real (para provar que `web_search.read_article` é chamado uma única vez) e
# sobrescrevem o stub de volta com esta referência.
_capture_conteudo_real = alert_checker._capture_conteudo


@pytest.fixture(autouse=True)
def _sem_news_log():
    """`log_sent_news` entrou no caminho de entrega de _check_news em 18/08/2026.
    Nenhum teste DESTE arquivo é sobre o registro legível — o comportamento dele
    mora em test_news_log.py, inclusive a garantia de que ele é chamado. Sem este
    stub, todo teste que chega a entregar tentaria o Supabase de produção: é
    exatamente a falha que o comentário do topo descreve.

    `_capture_conteudo` e `log_alert_messages` entraram no mesmo caminho em
    18/08/2026 (sessão 'noticias-ancoradas', Partes A e B): sem stub, todo
    teste que chega a entregar tentaria o ScraperAPI (real, até 75s de
    timeout) e o Supabase de novo — o comportamento deles mora em
    test_news_log.py.

    `update_news_log_conteudo` entrou no mesmo caminho no Conserto 1
    (19/08/2026, captura movida para depois do dedup): como `log_sent_news`
    aqui devolve um MagicMock (truthy, mas não um id real), o guard `if
    news_log_id:` deixaria passar a chamada — sem este stub ela tentaria o
    Supabase de produção assim que algum teste capturasse conteúdo não-None."""
    with patch("backend.services.alert_checker.supabase.log_sent_news"), \
         patch("backend.services.alert_checker._capture_conteudo",
               return_value=alert_checker._CAPTURA_VAZIA), \
         patch("backend.services.alert_checker.supabase.log_alert_messages"), \
         patch("backend.services.alert_checker.supabase.update_news_log_conteudo"):
        yield


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


def test_run_checks_devolve_duracao_s():
    """Item 2 (3ª revisão do Apolo, 05/09/2026): orçamento de tempo tem que
    ser MEDIDO, não estimado — número em comentário apodrece, medição não."""
    with patch("backend.services.alert_checker._get_recipients", return_value=_RECIPIENTS), \
         patch("backend.services.alert_checker._collect_all", return_value={"market": {}}), \
         patch("backend.services.alert_checker._check_price_rules", return_value=0), \
         patch("backend.services.alert_checker._check_copom", return_value=0), \
         patch("backend.services.alert_checker._check_eia", return_value=0), \
         patch("backend.services.alert_checker._check_news", return_value=0):
        result = alert_checker.run_checks(test_mode=False)
    assert "duracao_s" in result
    assert result["duracao_s"] >= 0


def test_run_checks_sem_recipients_tambem_devolve_duracao_s():
    """A saída antecipada (sem destinatário) é um `return` separado — sem
    teste próprio, ela ficaria sem a chave calada."""
    with patch("backend.services.alert_checker._get_recipients", return_value=[]), \
         patch("backend.services.alert_checker.notify_admin"):
        result = alert_checker.run_checks(test_mode=True)
    assert "duracao_s" in result
    assert result["duracao_s"] >= 0


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


def test_source_rule_id_normaliza_caracteres_especiais():
    """A4: fonte publicadora real (conjunto ABERTO desde o conserto do A6) pode
    trazer '&', '.', '(' — normaliza para caracteres seguros de URL/rule_id, senão
    corta a query string do PostgREST em get_alert_last_triggered."""
    rid = alert_checker._source_rule_id("S&P Global")
    assert re.fullmatch(r"news_source_[a-z0-9_]+", rid), rid
    assert "&" not in rid


def test_source_rule_id_wicker_gov():
    """Medido pelo Apolo contra uma coleta real: 'U.S. Senator Roger Wicker (.gov)'
    é um publicador de verdade que aparece no <source> do Google Notícias."""
    rid = alert_checker._source_rule_id("U.S. Senator Roger Wicker (.gov)")
    assert re.fullmatch(r"news_source_[a-z0-9_]+", rid), rid


def test_source_rule_id_mantem_compatibilidade_com_fontes_simples():
    """Guarda de regressão: fonte sem caractere especial continua igual a antes."""
    assert alert_checker._source_rule_id("Le Monde") == "news_source_le_monde"


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
    # `resumo` NÃO aparece mais na mensagem, mas continua no contrato de propósito:
    # é escrito antes de `ativos`/`direcao` e serve de rascunho para eles. Sem esta
    # linha a suíte fica verde ao apagá-lo do prompt — e apagá-lo muda a lista de
    # ativos em ~metade das notícias sem economizar token (medido em 14/08/2026).
    assert '"resumo"' in p


def _fake_resp(payload: str):
    return type("R", (), {"content": [type("C", (), {"text": payload})()]})()


_RESP_V2 = '{"score": 9, "categoria": "OFERTA/CLIMA", "titulo_pt": "OPEC+ corta produção", "resumo": "PARAGRAFO_DE_ANALISE", "ativos": ["petróleo", "diesel"], "direcao": "alta", "duplicada": false}'
_RESP_DUP = '{"score": 9, "categoria": "OFERTA/CLIMA", "titulo_pt": "OPEC+ corta produção", "resumo": "PARAGRAFO_DE_ANALISE", "ativos": ["petróleo"], "direcao": "alta", "duplicada": true}'
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
    # prende o caminho REAL de produção: nem o formatador nem o _check_news podem
    # colar o parágrafo de análise de volta na mensagem
    assert "PARAGRAFO_DE_ANALISE" not in msg


def test_format_news_alert_omite_resumo():
    result = {"categoria": "MACRO", "resumo": "ANALISE QUE NAO DEVE APARECER",
              "ativos": ["soja"], "direcao": "alta"}
    msg = alert_checker._format_news_alert(result, "Reuters", "Vendas caem 0,6%", 7, False)
    assert "ANALISE QUE NAO DEVE APARECER" not in msg
    assert "Vendas caem 0,6%" in msg
    assert "📈 Impacto provável: alta — soja" in msg


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
    resp = '{"score": 4, "categoria": "BRASIL", "titulo_pt": "t", "resumo": "PARAGRAFO_DE_ANALISE", "ativos": ["soja"], "direcao": "alta", "duplicada": false}'
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=[_ARTIGO]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._broadcast_com_ids", return_value=[("x", "y")]) as mock_bc:
        mock_cli.return_value.messages.create.return_value = _fake_resp(resp)
        enviados = alert_checker._check_news(_RECIPIENTS)
    assert enviados == 0
    mock_bc.assert_not_called()


def _resp_nota(score: int, titulo_pt: str):
    p = (f'{{"score": {score}, "categoria": "MACRO", "titulo_pt": "{titulo_pt}", '
         f'"resumo": "PARAGRAFO_DE_ANALISE", "ativos": ["soja"], "direcao": "alta", "duplicada": false}}')
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
    """Evolution fora do ar: _broadcast_com_ids devolve lista vazia. Marcar
    como enviada mataria a notícia para sempre (is_news_sent não tem prazo) e
    ainda entraria no get_recent_sent_titles, fazendo as próximas sobre o
    mesmo fato virarem 'duplicada' de algo que o dono nunca viu."""
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent") as mock_mark, \
         patch("backend.collectors.news.collect", return_value=[dict(_TRES_CANDIDATAS[0])]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._broadcast_com_ids", return_value=[]):
        mock_cli.return_value.messages.create.return_value = _resp_nota(8, "forte")
        enviados = alert_checker._check_news(_RECIPIENTS)
    assert enviados == 0
    mock_mark.assert_not_called(), "sem entrega, a notícia continua disponível"


# ── _broadcast_com_ids executada de verdade (achado 4, revisão do Apolo, 18/08/2026) ──
#
# As 6 referências anteriores a `_broadcast_com_ids` no arquivo de testes eram
# todas patch/monkeypatch — a função real nunca rodava sob `-k broadcast_com_ids`.
# É a peça que sustenta a Parte B (ancoragem por message_id) inteira, e o modo de
# falha é silencioso por construção: `send_message` mudando de forma (a v2 já
# mudou o payload uma vez) faz `log_alert_messages` gravar zero linhas sem que
# o alerta pare de chegar. Os dois testes abaixo chamam a função real.

def test_broadcast_com_ids_extrai_message_id_do_retorno_da_evolution():
    """Formato real medido: `send_message` devolve o corpo da resposta da
    Evolution, que carrega o id da mensagem em `key.id`."""
    with patch("backend.services.alert_checker.whatsapp.send_message",
               return_value={"key": {"id": "3EB0C767D26A1D712E"}}) as mock_send:
        entregues = alert_checker._broadcast_com_ids("msg", _RECIPIENTS)
    mock_send.assert_called_once_with("5534999000001", "msg")
    assert entregues == [("5534999000001", "3EB0C767D26A1D712E")]


def test_broadcast_com_ids_sem_message_id_no_retorno_avisa_e_devolve_none():
    """Se a Evolution mudar de forma e `key.id` sumir, a entrega não pode
    quebrar (a mensagem JÁ FOI enviada) — mas o id vem None e um warning é
    logado, para o silêncio não ser total."""
    with patch("backend.services.alert_checker.whatsapp.send_message", return_value={}), \
         patch("backend.services.alert_checker.logger") as mock_logger:
        entregues = alert_checker._broadcast_com_ids("msg", _RECIPIENTS)
    assert entregues == [("5534999000001", None)]
    assert mock_logger.warning.called


def test_classifier_prompt_manda_traduzir_sigla_de_organizacao():
    """Defeito 2 da validação em produção (18/08/2026): `titulo_pt` saiu como
    "Produção de Petróleo dos EAU Aproxima-se do Recorde Após Saída da OPEC" —
    frase em português com a sigla em inglês. O bot respondeu "OPEP" e ficou
    parecendo que ele tinha trocado o fato; quem errou foi o classificador.

    O prompt precisa mandar traduzir sigla COM forma consagrada em português e
    citar exemplo, e precisa dizer explicitamente para NÃO inventar tradução
    das que não têm (Fed, USDA) — senão a regra vira "traduza tudo" e aparece
    "DAEU" no lugar de "USDA"."""
    p = alert_checker._NEWS_CLASSIFIER_SYSTEM
    assert "OPEC" in p and "OPEP" in p
    assert "USDA" in p and "Fed" in p


# ── Camada 1 (05/09/2026): data REAL da matéria antes de enviar ────────────
#
# Incidente medido: o check-alerts mandou "May WASDE report to reveal first
# look at new crop outlook" (farmprogress.com) em SETEMBRO — o Google carimbou
# a REINDEXAÇÃO, não a publicação, e o classificador recebeu a data errada.

# 10 dias: bem acima de `_IDADE_MAXIMA_REAL` (7 dias). Antes do conserto do
# achado 1 (05/09/2026) este valor era `timedelta(hours=100)` (~4,2 dias) —
# "velho" pelo teto antigo (`news._MAX_AGE`, 48h), mas hoje FRESCO pelo teto
# novo. Usar 100h aqui de novo faria estes testes pararem de provar o que
# dizem provar, calados.
_DATA_VELHA = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()


def _rodar_com_notas_e_capturas(notas: list[int], capturas_por_url: dict,
                                candidatas: list[dict], test_mode: bool = False):
    """Como `_rodar_com_notas`, mas com controle por URL do que
    `_capture_conteudo` devolve — usado pelos testes de `_confirmar_frescor`.
    `capturas_por_url` fora do dicionário devolve `_CAPTURA_VAZIA` (não achou
    nada, comportamento honesto de falha). Devolve também o mock de
    `set_alert_triggered` (item 1b, 3ª revisão do Apolo, 05/09/2026): é onde o
    veredito "confirmada velha" é gravado agora, no lugar do `_mark_sent`
    antigo."""
    respostas = [_resp_nota(n, f"pt {n}") for n in notas]

    def fake_capture(url, url_publisher="", timeout=None):
        return capturas_por_url.get(url, alert_checker._CAPTURA_VAZIA)

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set, \
         patch("backend.services.alert_checker._mark_sent") as mock_mark, \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=fake_capture), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.side_effect = respostas
        mock_wa.send_message.return_value = True
        enviados = alert_checker._check_news(
            [{"phone": "5534999000001", "name": "A"}], test_mode=test_mode)
    return enviados, mock_wa, mock_mark, mock_set


def test_confirma_frescor_descarta_vencedora_velha_sem_marcar_para_sempre():
    """A candidata de MAIOR nota tem data real velha (a matéria de maio,
    republicada em setembro) — é descartada e a rodada termina sem envio
    (item 2, 3ª revisão do Apolo, 05/09/2026: com `_MAX_PRE_LEITURAS=1`, a
    2ª colocada não chega a ser lida NESTA rodada — ver o teste-irmão
    `test_confirma_frescor_velha_libera_a_segunda_na_rodada_seguinte` para o
    que acontece na rodada seguinte).

    Item 1b: a candidata velha NÃO leva mais `_mark_sent` (permanente, sem
    TTL — condenava matéria FRESCA para sempre quando a leitura errava). O
    veredito agora é gravado como cooldown de 7 dias em
    `preleitura_velha_<url_id>` — e NÃO no cooldown de 6h de "já li, segue"
    (`preleitura_<url_id>`), que é só para o caminho que SEGUE."""
    import hashlib
    candidatas = [
        {"titulo": "WASDE de maio republicado", "fonte": "Farm Progress", "url": "https://e.com/velha"},
        {"titulo": "notícia fresca", "fonte": "Reuters", "url": "https://e.com/fresca"},
    ]
    capturas = {
        "https://e.com/velha": alert_checker.Captura(
            "May 11, 2026 The USDA's May WASDE report...", "read_article:trafilatura", None, _DATA_VELHA),
    }
    enviados, wa, mark, set_triggered = _rodar_com_notas_e_capturas([9, 6], capturas, candidatas)

    assert enviados == 0
    wa.send_message.assert_not_called()
    news_id_velha = hashlib.md5("WASDE de maio republicado".encode()).hexdigest()
    url_id_velha = hashlib.md5("https://e.com/velha".encode()).hexdigest()
    marcados = [c.args[0] for c in mark.call_args_list]
    assert news_id_velha not in marcados
    assert url_id_velha not in marcados
    rule_ids = [c.args[0] for c in set_triggered.call_args_list]
    assert f"preleitura_velha_{url_id_velha}" in rule_ids
    assert f"preleitura_{url_id_velha}" not in rule_ids


def test_confirma_frescor_velha_libera_a_segunda_na_rodada_seguinte():
    """Item 1b + 2 combinados (3ª revisão do Apolo, 05/09/2026): com
    orçamento de 1 leitura por rodada, a candidata confirmada velha consome
    o único read desta rodada e a 2ª colocada não chega a ser tentada — mas
    na RODADA SEGUINTE (15 min depois, cron; mesmas candidatas re-fetchadas),
    o gate de 7 dias pula a velha SEM ler (não consome orçamento nenhum),
    sobrando a leitura para a 2ª colocada, que sai fresca e é enviada.
    A velha NUNCA é relida (`leituras` só tem uma entrada dela)."""
    import hashlib
    candidatas = [
        {"titulo": "WASDE de maio republicado", "fonte": "Farm Progress", "url": "https://e.com/velha"},
        {"titulo": "notícia fresca", "fonte": "Reuters", "url": "https://e.com/fresca"},
    ]
    capturas = {
        "https://e.com/velha": alert_checker.Captura(
            "May 11, 2026 The USDA's May WASDE report...", "read_article:trafilatura", None, _DATA_VELHA),
        # Conteúdo REAL (não `_CAPTURA_VAZIA`) para a fresca: sem isto, a
        # captura pós-envio (que roda quando a pré-leitura não trouxe
        # conteúdo de verdade) chamaria `_capture_conteudo` DE NOVO só para
        # o registro — um 2º "https://e.com/fresca" em `leituras` que não é
        # o que este teste quer provar (a REGRA de orçamento/cooldown, não a
        # reaproveitamento de captura, que já tem teste próprio).
        "https://e.com/fresca": alert_checker.Captura(
            "Texto da matéria fresca, com conteúdo suficiente para não ser vazio.",
            "read_article:trafilatura", None, None),
    }
    leituras: list[str] = []
    ultimo_disparo: dict[str, datetime] = {}

    def fake_cooldown_ok(rule_id, hours):
        gatilho = ultimo_disparo.get(rule_id)
        if gatilho is None:
            return True
        return gatilho < datetime.now(timezone.utc) - timedelta(hours=hours)

    def fake_set_triggered(rule_id):
        ultimo_disparo[rule_id] = datetime.now(timezone.utc)

    def fake_capture(url, url_publisher="", timeout=None):
        leituras.append(url)
        return capturas.get(url, alert_checker._CAPTURA_VAZIA)

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=fake_cooldown_ok), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered", side_effect=fake_set_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker._mark_sent") as mock_mark, \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=fake_capture), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.side_effect = [
            _resp_nota(9, "pt 9"), _resp_nota(6, "pt 6"),   # rodada 1: classifica as 2
            _resp_nota(9, "pt 9"), _resp_nota(6, "pt 6"),   # rodada 2: classifica as 2 de novo
        ]
        mock_wa.send_message.return_value = True

        enviados_1 = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
        enviados_2 = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados_1 == 0
    assert enviados_2 == 1
    assert "pt 6" in mock_wa.send_message.call_args[0][1]
    assert leituras == ["https://e.com/velha", "https://e.com/fresca"]
    mock_mark.assert_called_once()  # só a fresca enviada, na 2ª rodada


def test_confirma_frescor_sem_data_envia():
    """Leitura sem data nenhuma (metadado ausente, texto sem data reconhecível)
    é falha ABERTA: segue como se fosse fresca."""
    candidatas = [{"titulo": "materia sem data", "fonte": "F1", "url": "https://e.com/semdata"}]
    capturas = {
        "https://e.com/semdata": alert_checker.Captura("texto qualquer da matéria", "read_article:trafilatura", None, None),
    }
    enviados, wa, _, _ = _rodar_com_notas_e_capturas([9], capturas, candidatas)
    assert enviados == 1
    assert wa.send_message.call_count == 1


def test_confirma_frescor_estoura_prazo_e_segue_falha_aberta(monkeypatch):
    """Leitura que estoura o prazo (40s por padrão) é falha ABERTA: o alerta
    sai mesmo assim. O teste injeta um prazo curto para não gastar 40s reais —
    a thread É daemon (item 7, 05/09/2026: `threading.Thread(daemon=True)` no
    lugar do `ThreadPoolExecutor`) e morre junto com o processo, então o
    teste termina em segundos mesmo com a leitura simulada 'pendurada'."""
    monkeypatch.setattr(alert_checker, "_PRE_LEITURA_TIMEOUT_S", 0.2)
    candidatas = [{"titulo": "materia lenta", "fonte": "F1", "url": "https://e.com/lenta"}]

    def capture_lenta(url, url_publisher="", timeout=None):
        time.sleep(1.0)
        return alert_checker._CAPTURA_VAZIA

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=capture_lenta), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        t0 = time.monotonic()
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
        gasto = time.monotonic() - t0

    assert enviados == 1
    assert gasto < 3.0


def test_confirma_frescor_test_mode_com_velha_nao_envia_nem_marca():
    """`test_mode` segue a mesma lógica de descarte, mas sem `_mark_sent` nem
    escrita de cooldown — é só uma conferência visual, não pode sujar o
    estado de produção (nem o dedup nem o veredito de 7 dias, item 1b/2, 3ª
    revisão do Apolo, 05/09/2026)."""
    candidatas = [{"titulo": "materia velha unica", "fonte": "F1", "url": "https://e.com/velha-tm"}]
    capturas = {
        "https://e.com/velha-tm": alert_checker.Captura("t", "read_article:trafilatura", None, _DATA_VELHA),
    }
    enviados, wa, mark, set_triggered = _rodar_com_notas_e_capturas(
        [9], capturas, candidatas, test_mode=True)
    assert enviados == 0
    wa.send_message.assert_not_called()
    mark.assert_not_called()
    set_triggered.assert_not_called()


def test_confirma_frescor_captura_reaproveitada_le_a_materia_uma_vez():
    """A captura da pré-leitura (bem-sucedida) é REAPROVEITADA na captura
    pós-envio — `web_search.read_article` roda exatamente 1 vez na rodada, não
    2, mesmo a matéria sendo lida duas vezes na lógica (pré-envio + registro)."""
    candidatas = [{"titulo": "materia unica", "fonte": "Farm Progress",
                  "url": "https://www.farmprogress.com/x",
                  "url_publisher": "https://www.farmprogress.com"}]
    leituras: list[str] = []

    def fake_read_article(url, timeout=30.0, url_publisher=""):
        leituras.append(url)
        return {"url": url, "conteudo": "Texto suficientemente longo da matéria de teste " * 5,
                "extrator": "trafilatura", "data_publicacao": None}

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker.supabase.log_sent_news", return_value=999), \
         patch("backend.services.alert_checker.supabase.log_alert_messages"), \
         patch("backend.services.alert_checker.supabase.update_news_log_conteudo"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=_capture_conteudo_real), \
         patch("backend.services.alert_checker.web_search.read_article", side_effect=fake_read_article), \
         patch("backend.services.alert_checker.web_search.resolve_google_news", return_value=""), \
         patch("backend.services.alert_checker.whatsapp.send_message",
               return_value={"key": {"id": "MSG1"}}):
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados == 1
    assert leituras == ["https://www.farmprogress.com/x"]


def test_confirma_frescor_prazo_e_teto_de_pre_leituras_sao_constantes_medidas():
    """Números com motivo documentado no código — não travam sem comentário."""
    assert alert_checker._PRE_LEITURA_TIMEOUT_S == 40.0
    # Item 2 (3ª revisão do Apolo, 05/09/2026): baixado de 2 para 1 — a 2ª
    # leitura só entrava quando a 1ª saía confirmada velha, e hoje quem barra
    # a releitura de uma candidata confirmada velha é o cooldown de 7 dias
    # (`_PRELEITURA_VELHA_COOLDOWN_HOURS`), sem gastar orçamento de leitura.
    assert alert_checker._MAX_PRE_LEITURAS == 1
    assert alert_checker._IDADE_MAXIMA_REAL == timedelta(days=7)
    assert alert_checker._PRELEITURA_COOLDOWN_HOURS == 6.0
    assert alert_checker._PRELEITURA_VELHA_COOLDOWN_HOURS == 24 * 7


# ── Achado 1 (05/09/2026): `_MAX_AGE` (48h, do agregador) condenava notícia
# FRESCA por causa da precisão de DIA (não hora) de `_data_publicacao` ────────

@pytest.mark.parametrize("horas_atras,espera_velha", [
    (34.5, False),
    (38.0, False),
    (46.0, False),
    (24 * 9, True),     # 9 dias
    (24 * 117, True),   # o próprio incidente: WASDE de maio "confirmado" em setembro
])
def test_confirmar_frescor_usa_7_dias_nao_48h(horas_atras, espera_velha):
    """`_data_publicacao` só devolve o DIA (meia-noite) — comparado a "agora"
    isso soma até +24h de idade artificial. O `_MAX_AGE` do agregador (48h)
    condenaria as três primeiras (34,5h / 38h / 46h, todas notícias de fato
    FRESCAS) e `_mark_sent` sem TTL as mataria PARA SEMPRE. `_IDADE_MAXIMA_REAL`
    (7 dias) só pega o claramente velho: 9 dias e o próprio incidente (117
    dias) continuam sendo descartados."""
    data = (datetime.now(timezone.utc) - timedelta(hours=horas_atras)).date().isoformat()
    candidata = {"titulo": "x", "url": "https://e.com/x", "url_publisher": ""}
    captura = alert_checker.Captura("texto", "read_article:trafilatura", None, data)
    with patch("backend.services.alert_checker._capture_conteudo", return_value=captura):
        velha, _ = alert_checker._confirmar_frescor(candidata, "https://e.com/x")
    assert velha is espera_velha


# ── Achado 2 (05/09/2026): Evolution fora do ar relia a MESMA matéria a cada
# rodada do cron (15 min) — até 96 leituras/dia, até 35 créditos cada ────────

def test_check_news_evolution_fora_nao_rele_a_mesma_materia_a_cada_rodada():
    """3 rodadas seguidas com a entrega falhando sempre (Evolution fora do ar,
    `send_message` sempre estoura): sem `_mark_sent` (nada TTL), a mesma
    candidata volta a ser a nº 1 em toda rodada — e sem o cooldown por
    `url_id`, a pré-leitura (via `web_search.read_article`, até 35 créditos de
    ScraperAPI no caminho de render) rodava de novo em CADA uma delas. Com o
    cooldown, só a 1ª rodada lê de verdade."""
    import hashlib
    leituras: list[str] = []
    ultimo_disparo: dict[str, datetime] = {}

    def fake_cooldown_ok(rule_id, hours):
        gatilho = ultimo_disparo.get(rule_id)
        if gatilho is None:
            return True
        return gatilho < datetime.now(timezone.utc) - timedelta(hours=hours)

    def fake_set_triggered(rule_id):
        ultimo_disparo[rule_id] = datetime.now(timezone.utc)

    def fake_read_article(url, timeout=30.0, url_publisher=""):
        leituras.append(url)
        return {"url": url, "conteudo": "Texto suficiente da matéria de teste " * 10,
                "extrator": "trafilatura", "data_publicacao": None}

    candidata = {"titulo": "materia unica", "fonte": "Farm Progress",
                "url": "https://e.com/unica", "url_publisher": "https://e.com"}

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=fake_cooldown_ok), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered", side_effect=fake_set_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=[dict(candidata)]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=_capture_conteudo_real), \
         patch("backend.services.alert_checker.web_search.read_article", side_effect=fake_read_article), \
         patch("backend.services.alert_checker.web_search.resolve_google_news", return_value=""), \
         patch("backend.services.alert_checker.whatsapp.send_message",
               side_effect=RuntimeError("Evolution fora do ar")):
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        for _ in range(3):
            enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
            assert enviados == 0

    assert leituras == ["https://e.com/unica"]


def test_confirma_frescor_usa_timeout_menor_que_o_prazo_externo():
    """Achado 4 (05/09/2026): o timeout PRÓPRIO de `read_article` (chamado via
    `_capture_conteudo`) tem que ficar ABAIXO do prazo externo da pré-leitura —
    senão um link que ainda cai no caminho de render herda o piso de 75s por
    dentro, MAIOR que os 40s que a rodada dá para a pré-leitura inteira."""
    # Lista, não dict: a captura vazia da pré-leitura dispara uma 2ª chamada
    # pós-envio (achado 3), com o timeout GRANDE de `_CONTEUDO_TIMEOUT` — só a
    # PRIMEIRA chamada (a pré-leitura em si) é o que este teste mede.
    timeouts_vistos = []

    def fake_capture(url, url_publisher="", timeout=None):
        timeouts_vistos.append(timeout)
        return alert_checker._CAPTURA_VAZIA

    candidatas = [{"titulo": "materia", "fonte": "F1", "url": "https://e.com/x"}]
    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=fake_capture), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert timeouts_vistos[0] is not None
    assert timeouts_vistos[0] < alert_checker._PRE_LEITURA_TIMEOUT_S


def test_confirma_frescor_teto_agregado_de_1_velha_nao_estoura_e_nao_envia(monkeypatch):
    """Item 8 original, ajustado pelo item 2 da 3ª revisão do Apolo
    (05/09/2026): `_MAX_PRE_LEITURAS` caiu de 2 para 1 — só a candidata de
    MAIOR nota é lida de verdade nesta rodada. Com `_PRE_LEITURA_TIMEOUT_S`
    baixo (defensivo contra a suíte travar se algo aqui regredir) e ela
    confirmada velha, a rodada termina rápido e sem envio — a 2ª nem chega a
    ser lida (orçamento já esgotado) nem marcada (não é `_mark_sent` mais
    quem barra a candidata velha, é o cooldown de 7 dias)."""
    monkeypatch.setattr(alert_checker, "_PRE_LEITURA_TIMEOUT_S", 1.0)
    candidatas = [
        {"titulo": "velha um", "fonte": "F1", "url": "https://e.com/v1"},
        {"titulo": "nunca lida", "fonte": "F2", "url": "https://e.com/v2"},
    ]
    capturas = {
        "https://e.com/v1": alert_checker.Captura("t", "read_article:trafilatura", None, _DATA_VELHA),
    }
    t0 = time.monotonic()
    enviados, wa, mark, _ = _rodar_com_notas_e_capturas([9, 8], capturas, candidatas)
    gasto = time.monotonic() - t0

    assert enviados == 0
    wa.send_message.assert_not_called()
    mark.assert_not_called()
    assert gasto < 3.0


def test_classifier_prompt_penaliza_periodo_anterior_mesmo_com_publicado_em_recente():
    """Camada 2: reforço no PRÓPRIO classificador — mesmo que a camada 1 (data
    real da matéria) falhe aberta (sem data, timeout), o prompt já avisa que
    <publicado_em> pode ser a data de REINDEXAÇÃO do agregador, não a de
    publicação, e manda pontuar baixo um título/resumo de período já passado."""
    p = alert_checker._NEWS_CLASSIFIER_SYSTEM
    assert "REINDEXAÇÃO" in p
    assert "<publicado_em>" in p and "<hoje>" in p


# ── Item 3 (revisão do Apolo, 05/09/2026): link do Google não resolvido não
# pode disparar render de 75s dentro do prazo de 40s da pré-leitura ──────────

def test_confirma_frescor_link_do_google_nao_resolvido_nao_le():
    """`url_resolvida` ainda sendo `news.google.com` significa que a resolução
    prévia (`_link_para_mensagem`, chamada ANTES desta função) falhou. Ler
    mesmo assim cairia no `render=true` de dentro de `read_article`, que impõe
    um piso de 75s (`_RENDER_TIMEOUT_FLOOR`) — quase o dobro do prazo de 40s
    que esta função tem para a leitura inteira. Não lê: falha aberta, a
    candidata segue como se fosse fresca."""
    candidata = {"titulo": "materia", "url": "https://news.google.com/rss/articles/abc",
                "url_publisher": "https://exemplo.com"}
    with patch("backend.services.alert_checker._capture_conteudo") as mock_capture:
        velha, captura = alert_checker._confirmar_frescor(
            candidata, "https://news.google.com/rss/articles/abc")
    assert velha is False
    assert captura is None
    mock_capture.assert_not_called()


def test_confirma_frescor_link_ja_resolvido_le_normalmente():
    """Contraprova: link JÁ resolvido para o publicador (o caminho comum)
    continua lendo normalmente."""
    candidata = {"titulo": "materia", "url": "https://news.google.com/rss/articles/abc",
                "url_publisher": "https://exemplo.com"}
    captura_fake = alert_checker.Captura("texto", "read_article:trafilatura", None, None)
    with patch("backend.services.alert_checker._capture_conteudo",
               return_value=captura_fake) as mock_capture:
        velha, captura = alert_checker._confirmar_frescor(
            candidata, "https://www.exemplo.com/materia-real")
    assert velha is False
    assert captura == captura_fake
    mock_capture.assert_called_once()


# ── Item 5 (revisão do Apolo, 05/09/2026): cooldown de pré-leitura gravado
# até para candidata confirmada velha era escrita morta — `_mark_sent` já a
# barra para sempre, e a linha `preleitura_<url_id>` nunca mais seria lida.
#
# Reescrito no item 1b/2 (3ª revisão do Apolo, 05/09/2026): a candidata velha
# não leva mais `_mark_sent`, e sim `preleitura_velha_<url_id>` (7 dias) —
# provado em `test_confirma_frescor_descarta_vencedora_velha_sem_marcar_para_sempre`.
# Com `_MAX_PRE_LEITURAS=1`, um cenário de 2 candidatas na MESMA rodada não
# serve mais para provar que o cooldown de 6h ("já li, segue") é gravado só
# para quem SEGUE — a 2ª nunca seria lida nesta rodada (orçamento esgotado
# pela 1ª). Um candidato único, fresco, já prova o que importa aqui. ────────

def test_preleitura_cooldown_e_gravado_para_candidata_que_segue():
    """A candidata confirmada FRESCA (segue, é enviada) grava o cooldown de
    6h `preleitura_<url_id>` — para não reler a MESMA matéria a cada 15 min
    quando a entrega falha e ela nunca chega a ser marcada como enviada."""
    import hashlib
    candidatas = [{"titulo": "fresca", "fonte": "F1", "url": "https://e.com/fresca"}]
    url_id_fresca = hashlib.md5("https://e.com/fresca".encode()).hexdigest()

    with patch("backend.services.alert_checker._cooldown_ok", return_value=True), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered") as mock_set, \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo",
               return_value=alert_checker._CAPTURA_VAZIA), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    rule_ids = [c.args[0] for c in mock_set.call_args_list]
    assert f"preleitura_{url_id_fresca}" in rule_ids
    assert f"preleitura_velha_{url_id_fresca}" not in rule_ids


# ── Item 2 (4ª revisão do Apolo, 05/09/2026): os dois gates de pré-leitura
# (candidata confirmada velha, pré-leitura recente) não tinham try local — um
# soluço do Supabase em QUALQUER um dos dois subia até `run_checks` e abortava
# `_check_news` inteiro, tirando o alerta da rodada por um problema no
# COOLDOWN, não na notícia. `_cooldown_liberado` trata falha como "pode ler",
# mesmo padrão de `notify_admin`. ──────────────────────────────────────────

def test_gate_de_velha_falha_aberta_quando_supabase_da_erro():
    """`get_alert_last_triggered` explodindo só para o rule_id da candidata
    velha não pode abortar a rodada: a candidata segue como se não estivesse
    em cooldown nenhum, é lida e — sem data real capturada aqui — sai como
    fresca."""
    import hashlib
    candidata = {"titulo": "materia", "fonte": "F1", "url": "https://e.com/gate-velha-erro"}
    url_id = hashlib.md5(candidata["url"].encode()).hexdigest()
    velha_rule_id = f"preleitura_velha_{url_id}"

    def fake_get_last_triggered(rule_id):
        if rule_id == velha_rule_id:
            raise RuntimeError("Supabase fora do ar")
        return None

    with patch("backend.services.alert_checker.supabase.get_alert_last_triggered",
               side_effect=fake_get_last_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker._capture_conteudo",
               return_value=alert_checker._CAPTURA_VAZIA), \
         patch("backend.collectors.news.collect", return_value=[dict(candidata)]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados == 1


def test_gate_de_preleitura_falha_aberta_quando_supabase_da_erro():
    """Mesmo conserto, para o OUTRO gate (`preleitura_<url_id>`, cooldown de
    6h de 'já li, segue')."""
    import hashlib
    candidata = {"titulo": "materia", "fonte": "F1", "url": "https://e.com/gate-preleitura-erro"}
    url_id = hashlib.md5(candidata["url"].encode()).hexdigest()
    preleitura_rule_id = f"preleitura_{url_id}"

    def fake_get_last_triggered(rule_id):
        if rule_id == preleitura_rule_id:
            raise RuntimeError("Supabase fora do ar")
        return None

    with patch("backend.services.alert_checker.supabase.get_alert_last_triggered",
               side_effect=fake_get_last_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker.supabase.mark_news_sent"), \
         patch("backend.services.alert_checker._capture_conteudo",
               return_value=alert_checker._CAPTURA_VAZIA), \
         patch("backend.collectors.news.collect", return_value=[dict(candidata)]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados == 1


# ── Item 3 (4ª revisão do Apolo, 05/09/2026): os testes de 2 rodadas
# anteriores (`test_confirma_frescor_velha_libera_a_segunda_na_rodada_seguinte`,
# `test_check_news_evolution_fora_nao_rele_a_mesma_materia_a_cada_rodada`)
# comparavam `ultimo_disparo` contra `datetime.now(timezone.utc)` DE VERDADE —
# como as duas chamadas de `_check_news` acontecem em microssegundos, eles só
# provam que o cooldown segura por um instante (qualquer valor positivo já
# bastaria), nunca que ele dura ~7 dias / ~6h de verdade, nem que EXPIRA
# depois disso. Aqui o relógio é uma lista `[datetime]` que O TESTE desloca
# entre as rodadas — a mesma técnica, mas com o tempo sob controle. ──────────

def test_gate_de_velha_expira_apos_8_dias_e_rele():
    """A candidata confirmada velha na rodada 1 é RELIDA na rodada 2 depois
    do relógio avançar 8 dias (> `_PRELEITURA_VELHA_COOLDOWN_HOURS`, 168h).

    Mutação verificada À MÃO (05/09/2026, `_PRELEITURA_VELHA_COOLDOWN_HOURS = 0`,
    desfeita em seguida): este teste sozinho NÃO reprova (8 dias também passa
    de 0h — a direção da asserção, "relê depois de esperar", é a mesma dos
    dois lados). Quem some sob a mutação é o teste imediato (sem relógio
    controlado) `test_confirma_frescor_velha_libera_a_segunda_na_rodada_seguinte`
    — mas de forma INSTÁVEL: ele compara `ultimo_disparo` contra
    `datetime.now(timezone.utc)` de verdade, então com o cooldown mutado para
    0h o resultado vira uma corrida de microssegundos entre a gravação e a
    checagem (rodei 5 vezes sob a mutação: reprovou em ~metade, passou na
    outra metade). A instabilidade em si É o ponto do item 3 — nenhum teste
    baseado só no relógio real prova a DURAÇÃO do cooldown de forma
    confiável; só um relógio virtual desloca de propósito, sem depender de
    corrida nenhuma."""
    import hashlib
    candidata = {"titulo": "WASDE de maio republicado", "fonte": "Farm Progress",
                "url": "https://e.com/velha-relogio"}
    url_id = hashlib.md5(candidata["url"].encode()).hexdigest()

    relogio = [datetime.now(timezone.utc)]
    ultimo_disparo: dict[str, datetime] = {}
    leituras: list[str] = []

    def fake_cooldown_ok(rule_id, hours):
        gatilho = ultimo_disparo.get(rule_id)
        if gatilho is None:
            return True
        return gatilho < relogio[0] - timedelta(hours=hours)

    def fake_set_triggered(rule_id):
        ultimo_disparo[rule_id] = relogio[0]

    def fake_capture(url, url_publisher="", timeout=None):
        leituras.append(url)
        return alert_checker.Captura(
            "May 11, 2026 The USDA's May WASDE report...",
            "read_article:trafilatura", None, _DATA_VELHA)

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=fake_cooldown_ok), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered", side_effect=fake_set_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=[dict(candidata)]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=fake_capture), \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True

        enviados_1 = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
        assert leituras == ["https://e.com/velha-relogio"]
        assert f"preleitura_velha_{url_id}" in ultimo_disparo

        relogio[0] += timedelta(days=8)
        enviados_2 = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados_1 == 0
    assert enviados_2 == 0  # confirmada velha de novo — mas ela FOI relida
    assert leituras == ["https://e.com/velha-relogio", "https://e.com/velha-relogio"]


def test_gate_de_preleitura_expira_apos_7_horas_e_rele():
    """Contraparte do teste acima para `_PRELEITURA_COOLDOWN_HOURS` (6h,
    'já li, segue sem reler'): entrega falha sempre (Evolution fora do ar,
    mesmo cenário de `test_check_news_evolution_fora_nao_rele_a_mesma_materia_a_cada_rodada`),
    mas aqui o relógio avança 7h (> 6h) entre a 2ª e a 3ª rodada — a 3ª relê
    de verdade, em vez de repetir o 'segue sem reler' das rodadas 1 e 2."""
    import hashlib
    candidata = {"titulo": "materia unica", "fonte": "Farm Progress",
                "url": "https://e.com/segue-relogio", "url_publisher": "https://e.com"}

    relogio = [datetime.now(timezone.utc)]
    ultimo_disparo: dict[str, datetime] = {}
    leituras: list[str] = []

    def fake_cooldown_ok(rule_id, hours):
        gatilho = ultimo_disparo.get(rule_id)
        if gatilho is None:
            return True
        return gatilho < relogio[0] - timedelta(hours=hours)

    def fake_set_triggered(rule_id):
        ultimo_disparo[rule_id] = relogio[0]

    def fake_capture(url, url_publisher="", timeout=None):
        leituras.append(url)
        return alert_checker.Captura(
            "Texto fresco o bastante para não ficar vazio " * 5,
            "read_article:trafilatura", None, None)

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=fake_cooldown_ok), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered", side_effect=fake_set_triggered), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=[dict(candidata)]), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._capture_conteudo", side_effect=fake_capture), \
         patch("backend.services.alert_checker.whatsapp.send_message",
               side_effect=RuntimeError("Evolution fora do ar")):
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")

        alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
        assert leituras == ["https://e.com/segue-relogio"]

        alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])
        assert leituras == ["https://e.com/segue-relogio"]  # rodada 2: cooldown ainda ativo

        relogio[0] += timedelta(hours=7)
        alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert leituras == ["https://e.com/segue-relogio", "https://e.com/segue-relogio"]


# ── Item 5 (4ª revisão do Apolo, 05/09/2026): `_link_para_mensagem` rodava
# ANTES dos dois gates de cooldown — uma candidata em cooldown de velha (7
# dias) pagava a resolução do link (até `_LINK_PRAZO` = 5s) a CADA rodada do
# cron pelos 7 dias inteiros, sem nenhum uso do resultado (o `continue` do
# gate descarta a candidata sem nunca olhar `url_alerta`). ──────────────────

def test_link_nao_e_resolvido_para_candidata_em_cooldown_de_velha():
    candidatas = [{"titulo": "velha confirmada", "fonte": "F1", "url": "https://e.com/velha-cd"}]

    def cooldown(rule_id, hours):
        return not rule_id.startswith("preleitura_velha_")

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=cooldown), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._link_para_mensagem") as mock_link, \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados == 0
    mock_link.assert_not_called()


def test_link_e_resolvido_para_candidata_que_segue_sem_reler():
    """Contraprova: a candidata que passa pelo gate de velha mas está em
    cooldown de PRÉ-LEITURA (6h, 'segue sem reler') precisa do link resolvido
    — ela vira `melhor` e é enviada sem nunca chamar `_confirmar_frescor`."""
    candidatas = [{"titulo": "segue sem reler", "fonte": "F1", "url": "https://e.com/segue-cd"}]

    def cooldown(rule_id, hours):
        if rule_id.startswith("preleitura_velha_"):
            return True  # não bloqueada pela velha
        if rule_id.startswith("preleitura_"):
            return False  # bloqueada pela pré-leitura → "segue sem reler"
        return True

    with patch("backend.services.alert_checker._cooldown_ok", side_effect=cooldown), \
         patch("backend.services.alert_checker.supabase.is_news_sent", return_value=False), \
         patch("backend.services.alert_checker.supabase.get_recent_sent_titles", return_value=[]), \
         patch("backend.services.alert_checker.supabase.set_alert_triggered"), \
         patch("backend.services.alert_checker._mark_sent"), \
         patch("backend.collectors.news.collect", return_value=list(candidatas)), \
         patch("backend.services.alert_checker.Anthropic") as mock_cli, \
         patch("backend.services.alert_checker._link_para_mensagem",
               return_value="https://e.com/segue-cd") as mock_link, \
         patch("backend.services.alert_checker.whatsapp") as mock_wa:
        mock_cli.return_value.messages.create.return_value = _resp_nota(9, "pt 9")
        mock_wa.send_message.return_value = True
        enviados = alert_checker._check_news([{"phone": "5534999000001", "name": "A"}])

    assert enviados == 1
    mock_link.assert_called_once()
