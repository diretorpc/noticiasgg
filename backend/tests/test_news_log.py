import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services import alert_checker, supabase


def _fake_client(response):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    client.get = MagicMock(return_value=response)
    client.patch = MagicMock(return_value=response)
    return client


@pytest.mark.unit
def test_log_sent_news_envia_campos_ricos():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({
            "news_id": "abc123",
            "titulo_pt": "USDA mostra queda na qualidade do milho",
            "titulo_original": "Corn Rated 61% Good to Excellent",
            "fonte": "Farm Progress",
            "feed": "GN USDA/WASDE",
            "url": "https://news.google.com/rss/articles/abc",
            "url_publisher": "https://www.farmprogress.com",
            "categoria": "OFERTA/CLIMA",
            "resumo": "Condição boa/excelente do milho cai.",
            "resumo_fonte": "Corn conditions dropped to 61% good/excellent, USDA says.",
            "direcao": "alta",
            "score": 7,
            "ativos": ["milho", "soja"],
            "publicado_em": "2026-08-18T10:00:00+00:00",
        })
    path = client.post.call_args[0][0]
    enviado = client.post.call_args[1]["json"]
    assert path == "/news_log"
    assert enviado["news_id"] == "abc123"
    assert enviado["url"] == "https://news.google.com/rss/articles/abc"
    assert enviado["url_publisher"] == "https://www.farmprogress.com"
    assert enviado["fonte"] == "Farm Progress"
    assert enviado["feed"] == "GN USDA/WASDE"
    # resumo (análise da IA) e resumo_fonte (texto do RSS) são colunas separadas —
    # não podem se misturar (achado A3, revisão 18/08/2026)
    assert enviado["resumo"] == "Condição boa/excelente do milho cai."
    assert enviado["resumo_fonte"] == "Corn conditions dropped to 61% good/excellent, USDA says."
    assert enviado["ativos"] == ["milho", "soja"]
    assert enviado["score"] == 7
    assert "sent_at" in enviado


@pytest.mark.unit
def test_log_sent_news_publicado_em_invalido_e_descartado():
    """O caminho RSS sempre entrega ISO ou None (_parse_rss_date), mas o
    NewsAPI copia `publishedAt` cru. Um valor que o Postgres rejeita fazia a
    linha INTEIRA se perder — melhor descartar só o campo (achado A11)."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "publicado_em": "ontem de manha"})
    enviado = client.post.call_args[1]["json"]
    assert "publicado_em" not in enviado
    assert enviado["news_id"] == "abc123"


@pytest.mark.unit
def test_log_sent_news_publicado_em_valido_e_preservado():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "publicado_em": "2026-08-18T10:00:00Z"})
    enviado = client.post.call_args[1]["json"]
    assert enviado["publicado_em"] == "2026-08-18T10:00:00Z"


@pytest.mark.unit
def test_log_sent_news_falha_registra_warning_sem_estourar(caplog):
    """A4: não pode ficar mudo. `caplog` prova que o warning saiu, sem imprimir
    nenhum segredo (o erro aqui é sintético, sem chave nenhuma envolvida)."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar
    assert any("news_log write failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_log_sent_news_ignora_campo_desconhecido():
    """Chave fora do contrato não pode virar coluna inexistente no POST —
    o PostgREST devolve 400 e o registro se perde em silêncio."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "coluna_que_nao_existe": "x"})
    enviado = client.post.call_args[1]["json"]
    assert "coluna_que_nao_existe" not in enviado
    assert enviado["news_id"] == "abc123"


@pytest.mark.unit
def test_log_sent_news_nunca_estoura_para_o_chamador():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar


@pytest.mark.unit
def test_get_news_log_filtra_por_janela_e_ordena():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"news_id": "abc123", "titulo_pt": "t"}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log(hours=48, limit=5)
    url = client.get.call_args[0][0]
    assert url.startswith("/news_log?")
    assert "order=sent_at.desc" in url
    assert "limit=5" in url
    assert "sent_at=gte." in url
    assert resultado == {"itens": [{"news_id": "abc123", "titulo_pt": "t"}]}


@pytest.mark.unit
def test_get_news_log_falha_devolve_aviso_nao_lista_vazia_muda():
    """Lista vazia sozinha não distingue 'sem notícia' de 'banco fora do ar' —
    a Story 2 vai usar isto como ferramenta do Claude, e confundir os dois
    vira negativa autoritária errada (achado A5)."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log()
    assert resultado == {"itens": [], "aviso": "registro indisponível"}


@pytest.mark.unit
def test_get_news_log_nao_houve_noticia_e_soh_lista_vazia_sem_aviso():
    """Dia calmo (consulta funcionou, zero linhas) não pode carregar 'aviso' —
    isso confundiria o consumidor com uma falha que não aconteceu."""
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log()
    assert resultado == {"itens": []}
    assert "aviso" not in resultado


@pytest.mark.unit
def test_get_news_log_falha_registra_warning_sem_estourar(caplog):
    """A6: o irmão log_sent_news loga a própria falha e tem teste com caplog;
    get_news_log ficava mudo — o dono não teria como saber que a LEITURA
    quebrou sem olhar o `aviso` no retorno."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            resultado = supabase.get_news_log()
    assert resultado == {"itens": [], "aviso": "registro indisponível"}
    assert any("get_news_log failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_get_news_log_trava_limit_malicioso():
    """`limit` entra CRU na URL (`_f()` só protege `cutoff`). Na Story 2 vem de
    texto interpretado pelo modelo — sem trava, `limit="5&titulo_pt=eq.x"` é
    injeção de filtro (achado A10)."""
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(limit="5&titulo_pt=eq.x")
    url = client.get.call_args[0][0]
    assert "titulo_pt=eq.x" not in url
    assert "limit=20" in url  # não convertível → cai no default


@pytest.mark.unit
def test_get_news_log_limit_acima_do_teto_e_cortado():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(limit=99999)
    assert "limit=100" in client.get.call_args[0][0]


@pytest.mark.unit
def test_log_sent_news_devolve_id_da_linha_inserida():
    """Parte B ('noticias-ancoradas', 18/08/2026): `_client()` já manda
    `Prefer: return=representation`, então o POST devolve a linha inserida —
    log_sent_news precisa repassar o `id` pra quem grava news_log_messages."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"id": 42, "news_id": "abc123"}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        news_log_id = supabase.log_sent_news({"news_id": "abc123"})
    assert news_log_id == 42


@pytest.mark.unit
def test_log_sent_news_falha_devolve_none_em_vez_de_estourar():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        news_log_id = supabase.log_sent_news({"news_id": "abc123"})
    assert news_log_id is None


@pytest.mark.unit
def test_log_sent_news_aceita_conteudo_e_conteudo_fonte():
    """Parte A: `conteudo`/`conteudo_fonte` entraram na whitelist de campos —
    sem isso o PostgREST devolveria 400 pela coluna existir só depois da
    migration 008, mas o CAMPO seria descartado antes mesmo de tentar."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"id": 1}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({
            "news_id": "abc123",
            "conteudo": "Texto completo da matéria capturado agora.",
            "conteudo_fonte": "read_article",
        })
    enviado = client.post.call_args[1]["json"]
    assert enviado["conteudo"] == "Texto completo da matéria capturado agora."
    assert enviado["conteudo_fonte"] == "read_article"


@pytest.mark.unit
def test_log_sent_news_conteudo_ausente_nao_entra_no_payload():
    """None é o valor honesto quando a captura falhou — não pode virar a
    string 'None' nem sobrar chave vazia no POST."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"id": 1}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "conteudo": None, "conteudo_fonte": None})
    enviado = client.post.call_args[1]["json"]
    assert "conteudo" not in enviado
    assert "conteudo_fonte" not in enviado


@pytest.mark.unit
def test_update_news_log_conteudo_envia_patch_com_id():
    """Conserto 1 (19/08/2026): o texto da matéria chega DEPOIS, pelo UPDATE —
    a linha já existe (criada por log_sent_news antes da captura)."""
    resp = MagicMock(status_code=204)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.update_news_log_conteudo(42, "Texto.", "read_article:trafilatura",
                                          "https://energynow.ca/materia")
    path = client.patch.call_args[0][0]
    enviado = client.patch.call_args[1]["json"]
    assert path == "/news_log?id=eq.42"
    assert enviado == {"conteudo": "Texto.", "conteudo_fonte": "read_article:trafilatura",
                       "url_final": "https://energynow.ca/materia"}


@pytest.mark.unit
def test_update_news_log_conteudo_so_envia_campos_nao_none():
    resp = MagicMock(status_code=204)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.update_news_log_conteudo(42, "Texto.", None, None)
    enviado = client.patch.call_args[1]["json"]
    assert enviado == {"conteudo": "Texto."}


@pytest.mark.unit
def test_update_news_log_conteudo_tudo_none_nao_faz_requisicao():
    """Captura vazia (_CAPTURA_VAZIA) não pode virar um PATCH inútil — nem
    tocar em `_client()`, que exigiria SUPABASE_URL/SUPABASE_KEY."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    with patch.object(supabase, "_client", return_value=client):
        supabase.update_news_log_conteudo(42, None, None, None)
    client.patch.assert_not_called()


@pytest.mark.unit
def test_update_news_log_conteudo_forca_id_inteiro():
    """`id` vai CRU na query string (não passa por `_f()`). Vem sempre do
    próprio `log_sent_news` — nunca de texto externo — mas `int()` é defesa
    contra um chamador futuro que passe outra coisa (mesmo cuidado de
    `_clamp_int`)."""
    resp = MagicMock(status_code=204)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.update_news_log_conteudo("42", "Texto.", None, None)
    assert client.patch.call_args[0][0] == "/news_log?id=eq.42"


@pytest.mark.unit
def test_update_news_log_conteudo_falha_registra_warning_sem_estourar(caplog):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.patch = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            supabase.update_news_log_conteudo(42, "Texto.", None, None)  # não deve levantar
    assert any("news_log conteudo update failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_log_alert_messages_grava_um_por_destinatario():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_alert_messages(42, [
            ("5534999945010", "3EB0AB92509EBD8A820860"),
            ("5516991016898", "3EB0AB92509EBD8A820861"),
        ])
    path = client.post.call_args[0][0]
    enviado = client.post.call_args[1]["json"]
    assert path == "/news_log_messages"
    assert len(enviado) == 2
    assert enviado[0] == {"news_log_id": 42, "phone": "5534999945010",
                          "message_id": "3EB0AB92509EBD8A820860"}


@pytest.mark.unit
def test_log_alert_messages_descarta_pares_sem_message_id():
    """A coluna message_id é NOT NULL — entrega sem id extraído não pode
    virar linha quebrada."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_alert_messages(42, [
            ("5534999945010", "3EB0AB92509EBD8A820860"),
            ("5516991016898", None),
        ])
    enviado = client.post.call_args[1]["json"]
    assert len(enviado) == 1
    assert enviado[0]["phone"] == "5534999945010"


@pytest.mark.unit
def test_log_alert_messages_sem_news_log_id_nao_faz_requisicao():
    """news_log_id None (log_sent_news falhou) não pode virar linha órfã —
    a FK nem aceitaria."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_alert_messages(None, [("5534999945010", "abc")])
    client.post.assert_not_called()


@pytest.mark.unit
def test_log_alert_messages_lista_vazia_nao_faz_requisicao():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_alert_messages(42, [])
    client.post.assert_not_called()


@pytest.mark.unit
def test_log_alert_messages_falha_registra_warning_sem_estourar(caplog):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            supabase.log_alert_messages(42, [("5534999945010", "abc")])  # não deve levantar
    assert any("news_log_messages write failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_get_news_by_message_id_casa_e_devolve_a_noticia():
    resp_msgs = MagicMock(status_code=200)
    resp_msgs.raise_for_status = MagicMock()
    resp_msgs.json = MagicMock(return_value=[{"news_log_id": 42}])
    resp_news = MagicMock(status_code=200)
    resp_news.raise_for_status = MagicMock()
    resp_news.json = MagicMock(return_value=[{"titulo_pt": "Milho perde qualidade", "url": "https://x.com"}])

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=[resp_msgs, resp_news])

    with patch.object(supabase, "_client", return_value=client):
        noticia = supabase.get_news_by_message_id("3EB0AB92509EBD8A820860")

    assert noticia == {"titulo_pt": "Milho perde qualidade", "url": "https://x.com"}
    primeira_url = client.get.call_args_list[0][0][0]
    assert "news_log_messages" in primeira_url
    assert "3EB0AB92509EBD8A820860" in primeira_url
    segunda_url = client.get.call_args_list[1][0][0]
    assert "news_log?id=eq.42" in segunda_url


@pytest.mark.unit
def test_get_news_by_message_id_desconhecido_devolve_none():
    resp_msgs = MagicMock(status_code=200)
    resp_msgs.raise_for_status = MagicMock()
    resp_msgs.json = MagicMock(return_value=[])
    client = _fake_client(resp_msgs)
    with patch.object(supabase, "_client", return_value=client):
        noticia = supabase.get_news_by_message_id("id-que-nao-existe")
    assert noticia is None


@pytest.mark.unit
def test_get_news_by_message_id_vazio_devolve_none_sem_requisicao():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    with patch.object(supabase, "_client", return_value=client):
        assert supabase.get_news_by_message_id("") is None
        assert supabase.get_news_by_message_id(None) is None
    client.get.assert_not_called()


@pytest.mark.unit
def test_get_news_by_message_id_falha_devolve_none_registra_warning(caplog):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            noticia = supabase.get_news_by_message_id("abc")
    assert noticia is None
    assert any("get_news_by_message_id failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_get_news_by_message_id_encoda_valor_externo():
    """message_id vem do webhook (contextInfo.stanzaId) — externo, precisa
    passar por `_f()` como qualquer outro valor de filtro (achado A4 aplicado
    aqui de novo)."""
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_by_message_id("abc&phone=eq.x")
    url = client.get.call_args[0][0]
    # sem encodar, "&phone=eq.x" viraria um segundo filtro solto na query
    # string — tem que aparecer só DENTRO do valor codificado de message_id
    assert "message_id=eq.abc%26phone%3Deq.x" in url


@pytest.mark.unit
def test_get_news_log_hours_malicioso_ou_negativo_cai_no_piso():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(hours=-5)
    # hours=-5 vira 1 → cutoff é ~agora, não estoura nem é ignorado
    assert client.get.call_args[0][0].count("sent_at=gte.") == 1


@pytest.mark.unit
def test_format_news_alert_inclui_link():
    result = {"categoria": "OFERTA/CLIMA", "ativos": ["milho"], "direcao": "alta"}
    msg = alert_checker._format_news_alert(
        result, "Reuters", "Milho perde qualidade nos EUA", 7, False,
        url="https://example.com/usda",
    )
    assert "https://example.com/usda" in msg
    assert "Milho perde qualidade nos EUA" in msg


@pytest.mark.unit
def test_format_news_alert_sem_url_nao_quebra():
    msg = alert_checker._format_news_alert({}, "Reuters", "Título", 7, False, url="")
    assert "Título" in msg
    assert "http" not in msg


@pytest.mark.unit
def test_format_news_alert_rejeita_url_sem_esquema_http():
    """Link de terceiro sem checagem entra na mensagem de graça — 6 dos 20 feeds
    são busca aberta do Google Notícias (achado A7)."""
    msg = alert_checker._format_news_alert(
        {}, "Reuters", "Título", 7, False, url="javascript:alert(1)"
    )
    assert "javascript:" not in msg


@pytest.mark.unit
def test_format_news_alert_rejeita_url_absurdamente_longa():
    msg = alert_checker._format_news_alert(
        {}, "Reuters", "Título", 7, False, url="https://example.com/" + "a" * 1200
    )
    assert "🔗" not in msg


@pytest.mark.unit
def test_format_news_alert_aceita_link_longo_de_google_noticias():
    """Regressão medida em 18/08/2026: o teto antigo de 400 apagava o link de
    10,7% dos itens de feed GN (máximo real medido: 713 caracteres), sem log e
    sem aviso — justo o link que a Story 1 existe para entregar."""
    url = "https://news.google.com/rss/articles/" + "CBMi" * 175  # 737 chars
    assert len(url) > 700
    msg = alert_checker._format_news_alert({}, "Reuters", "Título", 7, False, url=url)
    assert url in msg


def _prepara_check_news(monkeypatch, artigo, classificacao, sent: int = 1,
                        conteudo: tuple = (None, None, None)):
    """Isola _check_news de rede, banco e IA. Devolve (gravado, enviadas,
    mensagens, atualizacoes): o dict onde o INSERT cai, a lista de mensagens
    que teriam ido ao WhatsApp, a lista de (news_log_id, pares) que
    log_alert_messages teria recebido, e a lista de (news_log_id, conteudo,
    conteudo_fonte, url_final) que update_news_log_conteudo teria recebido —
    desde o Conserto 1 (19/08/2026) o texto capturado chega pelo UPDATE, não
    pelo INSERT (ver test_check_news_grava_conteudo_capturado_no_log).

    `sent`: quantas entregas _broadcast_com_ids finge ter feito — 0 simula a
    Evolution fora do ar (usado pelo teste irmão do A8: entrega falhou, log
    não roda). `conteudo`: o que `_capture_conteudo` finge ter capturado —
    (None, None, None) por padrão (nenhum teste deste bloco é sobre a Parte A,
    que tem arquivo próprio) — o terceiro campo é a URL canônica do publicador
    (defeito 1, 19/08/2026)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    gravado: dict = {}
    enviadas: list[str] = []
    mensagens: list[tuple] = []
    atualizacoes: list[tuple] = []

    def fake_log_sent_news(entry):
        gravado.update(entry)
        return 999  # id fake da linha inserida — sem ele log_alert_messages nunca roda

    monkeypatch.setattr(alert_checker.supabase, "log_sent_news", fake_log_sent_news)
    monkeypatch.setattr(
        alert_checker.supabase, "log_alert_messages",
        lambda news_log_id, pares: mensagens.append((news_log_id, pares)),
    )
    monkeypatch.setattr(
        alert_checker.supabase, "update_news_log_conteudo",
        lambda news_log_id, conteudo_, conteudo_fonte_, url_final_:
            atualizacoes.append((news_log_id, conteudo_, conteudo_fonte_, url_final_)),
    )
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": alert_checker.Captura(*conteudo))
    # Sem resolução por padrão: a maioria dos testes não é sobre o link, e sem
    # este stub `_link_para_mensagem` abriria conexão real com o Google (a trava
    # de rede reprova). Quem testa a resolução sobrescreve.
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "")
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)

    def fake_broadcast_com_ids(msg, recipients, errors=None):
        if not sent:
            return []
        enviadas.append(msg)
        return [(r["phone"], f"MSG_ID_TESTE_{i}") for i, r in enumerate(recipients[:sent])]

    monkeypatch.setattr(alert_checker, "_broadcast_com_ids", fake_broadcast_com_ids)
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [artigo])

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(classificacao))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)
    return gravado, enviadas, mensagens, atualizacoes


_ARTIGO = {
    "titulo": "Corn Rated 61% Good to Excellent",
    "fonte": "Farm Progress",
    "feed": "GN USDA/WASDE",
    "url": "https://news.google.com/rss/articles/abc",
    "url_publisher": "https://www.farmprogress.com",
    "publicado_em": "2026-08-18T10:00:00+00:00",
    "resumo": "Corn conditions dropped to 61% good/excellent, USDA says.",
}

_CLASSIFICACAO = {
    "score": 7,
    "categoria": "OFERTA/CLIMA",
    "titulo_pt": "Milho dos EUA perde qualidade",
    "resumo": "Condição boa/excelente cai para 61%.",
    "ativos": ["milho"],
    "direcao": "alta",
    "duplicada": False,
}


@pytest.mark.unit
def test_check_news_grava_no_log_apos_entregar(monkeypatch):
    gravado, _, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert gravado["url"] == "https://news.google.com/rss/articles/abc"
    assert gravado["titulo_pt"] == "Milho dos EUA perde qualidade"
    assert gravado["titulo_original"] == "Corn Rated 61% Good to Excellent"
    assert gravado["fonte"] == "Farm Progress"
    assert gravado["publicado_em"] == "2026-08-18T10:00:00+00:00"
    assert gravado["categoria"] == "OFERTA/CLIMA"
    assert gravado["score"] == 7
    # resumo (análise do Haiku) x resumo_fonte (descrição crua do RSS) não podem
    # se misturar — ancorar o agente na paráfrase de outro LLM é a mesma doença
    # que este log existe para curar (achado A3, revisão 18/08/2026)
    assert gravado["resumo"] == "Condição boa/excelente cai para 61%."
    assert gravado["resumo_fonte"] == "Corn conditions dropped to 61% good/excellent, USDA says."
    # publisher real (do <source> do Google Notícias) e apelido do feed de busca
    # vão em campos separados — sem isso "fonte" seria "GN USDA/WASDE" (achados A2/A6)
    assert gravado["url_publisher"] == "https://www.farmprogress.com"
    assert gravado["feed"] == "GN USDA/WASDE"


@pytest.mark.unit
def test_check_news_nao_grava_no_log_quando_entrega_falha(monkeypatch):
    """Par de test_nao_queima_a_noticia_quando_a_entrega_falha (test_alert_checker.py),
    aplicado a log_sent_news: sem isto, mover a chamada para fora do `if sent > 0`
    passaria nos 267 testes e criaria registro de notícia que ninguém recebeu
    (achado A8)."""
    gravado, enviadas, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO, sent=0)

    total = alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert total == 0
    assert enviadas == []
    assert gravado == {}


@pytest.mark.unit
def test_check_news_manda_o_link_na_mensagem(monkeypatch):
    _, enviadas, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert len(enviadas) == 1
    assert "https://news.google.com/rss/articles/abc" in enviadas[0]


@pytest.mark.unit
def test_check_news_grava_log_antes_de_marcar_dedup(monkeypatch):
    """log_sent_news (registro legível) tem que rodar ANTES de mark_news_sent
    (dedup): se o Supabase soluçar entre as duas, essa ordem perde só o dedup —
    a ordem invertida perderia o vestígio que o agente de chat usa para responder
    "me fale mais sobre essa notícia" (achado A9). O invariante morava só num
    comentário no código-fonte; nenhum teste afirmava a ordem — inverter as duas
    chamadas passava nos 299 testes existentes."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    ordem: list[str] = []
    monkeypatch.setattr(alert_checker.supabase, "log_sent_news",
                        lambda *a, **k: ordem.append("log"))
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent",
                        lambda *a, **k: ordem.append("mark"))
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(alert_checker, "_broadcast_com_ids",
                        lambda msg, recipients, errors=None: [("5534999945010", "MSG_ID_TESTE")])
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": alert_checker._CAPTURA_VAZIA)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "")
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [_ARTIGO])

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(_CLASSIFICACAO))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert "log" in ordem and "mark" in ordem
    assert ordem.index("log") < ordem.index("mark")


@pytest.mark.unit
def test_check_news_captura_roda_por_ultimo(monkeypatch):
    """Conserto 1 (19/08/2026): a captura da matéria (até 75s no caminho de
    render, e SEM teto real de tempo — `httpx.Timeout` é por OPERAÇÃO, medido
    1,0s pedido virando 15,25s reais) tem que rodar DEPOIS de tudo que marca a
    notícia como entregue (log, log_alert_messages, dedup, cooldown). Se a
    função da Vercel morrer durante a captura, a pior perda é só o texto — o
    cron de 15 min não pode reclassificar e reenviar a mesma notícia."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    ordem: list[str] = []
    monkeypatch.setattr(alert_checker.supabase, "log_sent_news",
                        lambda entry: ordem.append("log") or 999)
    monkeypatch.setattr(alert_checker.supabase, "log_alert_messages",
                        lambda *a, **k: ordem.append("log_alert_messages"))
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent",
                        lambda *a, **k: ordem.append("mark"))
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered",
                        lambda *a, **k: ordem.append("set_alert_triggered"))
    monkeypatch.setattr(alert_checker.supabase, "update_news_log_conteudo",
                        lambda *a, **k: ordem.append("update_conteudo"))
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": ordem.append("captura")
                        or alert_checker._CAPTURA_VAZIA)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(alert_checker, "_broadcast_com_ids",
                        lambda msg, recipients, errors=None: ordem.append("broadcast")
                        or [("5534999945010", "MSG_ID_TESTE")])
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "")
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [_ARTIGO])

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(_CLASSIFICACAO))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    # `set_alert_triggered("newsapi_fetch")` roda ANTES do broadcast (fora do
    # bloco de entrega) e `source` de _ARTIGO é truthy, então
    # set_alert_triggered aparece de novo entre "mark" e "captura" — checar a
    # partir de "broadcast" e só as duas últimas posições evita depender de
    # quantas vezes ele roda no meio.
    i = ordem.index("broadcast")
    assert ordem[i:i + 4] == ["broadcast", "log", "log_alert_messages", "mark"]
    assert ordem[-2:] == ["captura", "update_conteudo"]


@pytest.mark.unit
def test_check_news_em_test_mode_nao_grava_no_log(monkeypatch):
    """test_mode existe para conferência visual sem sujar o estado — o log
    não pode virar a exceção que suja."""
    gravado, _, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news(
        [{"phone": "5534999945010", "name": "Matheus"}], test_mode=True
    )

    assert gravado == {}


# ── Parte A: captura de conteúdo (sessão 'noticias-ancoradas', 18/08/2026) ──

@pytest.mark.unit
def test_capture_conteudo_sem_url_devolve_none():
    assert alert_checker._capture_conteudo("") == (None, None, None)
    assert alert_checker._capture_conteudo(None) == (None, None, None)


@pytest.mark.unit
def test_capture_conteudo_sucesso_marca_a_fonte(monkeypatch):
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"url": url, "conteudo": "Texto completo do artigo.",
                                   "extrator": "trafilatura"},
    )
    conteudo, fonte, _ = alert_checker._capture_conteudo("https://www.farmprogress.com/x")
    assert conteudo == "Texto completo do artigo."
    assert fonte == "read_article:trafilatura"


@pytest.mark.unit
def test_capture_conteudo_usa_o_teto_de_tempo_dedicado(monkeypatch):
    """render=true (necessário pros 6 feeds GN) mediu até 48,9s por link real —
    o teto de captura tem que dar folga sobre isso, não usar o default de 30s
    de read_article (pensado pro tráfego geral do chat)."""
    capturado = {}

    def fake_read_article(url, timeout=30.0, url_publisher=""):
        capturado["timeout"] = timeout
        return {"url": url, "conteudo": "x"}

    monkeypatch.setattr(alert_checker.web_search, "read_article", fake_read_article)
    alert_checker._capture_conteudo("https://www.farmprogress.com/x")
    assert capturado["timeout"] == alert_checker._CONTEUDO_TIMEOUT
    assert capturado["timeout"] > 30.0


@pytest.mark.unit
def test_capture_conteudo_erro_devolve_none_sem_estourar(monkeypatch):
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"erro": "404 Not Found", "url": url},
    )
    assert alert_checker._capture_conteudo("https://news.google.com/rss/articles/abc") == (None, None, None)


@pytest.mark.unit
def test_capture_conteudo_conteudo_vazio_devolve_none(monkeypatch):
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"url": url, "conteudo": ""},
    )
    assert alert_checker._capture_conteudo("https://x.com") == (None, None, None)


@pytest.mark.unit
def test_capture_conteudo_excecao_nao_tratada_nao_estoura(monkeypatch):
    def explode(url, timeout=30.0, url_publisher=""):
        raise RuntimeError("timeout")
    monkeypatch.setattr(alert_checker.web_search, "read_article", explode)
    assert alert_checker._capture_conteudo("https://x.com") == (None, None, None)


@pytest.mark.unit
def test_check_news_grava_conteudo_capturado_no_log(monkeypatch):
    """Conserto 1 (19/08/2026): o texto chega pelo UPDATE
    (`update_news_log_conteudo`), não pelo INSERT de `log_sent_news` — a
    captura roda DEPOIS que a notícia já foi entregue, registrada e marcada
    como enviada, então um estouro dos 300s da Vercel durante a leitura (até
    75s no caminho de render, sem teto real de tempo: `httpx.Timeout` é por
    OPERAÇÃO — 1,0s pedido virou 15,25s reais) perde só o texto, nunca o
    dedup."""
    gravado, _, _, atualizacoes = _prepara_check_news(
        monkeypatch, _ARTIGO, _CLASSIFICACAO,
        conteudo=("Texto completo capturado agora.", "read_article", None),
    )

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert "conteudo" not in gravado
    assert "conteudo_fonte" not in gravado
    assert atualizacoes == [(999, "Texto completo capturado agora.", "read_article", None)]


@pytest.mark.unit
def test_check_news_sem_captura_atualiza_com_conteudo_ausente(monkeypatch):
    """(None, None, None) é o resultado honesto de captura falha — _check_news
    repassa isso ao UPDATE tal como veio (quem decide não fazer requisição
    nenhuma é `update_news_log_conteudo`, testado à parte em
    test_update_news_log_conteudo_tudo_none_nao_faz_requisicao)."""
    gravado, _, _, atualizacoes = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert "conteudo" not in gravado
    assert "conteudo_fonte" not in gravado
    assert atualizacoes == [(999, None, None, None)]


# ── Parte B: id da mensagem por destinatário ─────────────────────────────

@pytest.mark.unit
def test_check_news_grava_id_da_mensagem_por_destinatario(monkeypatch):
    gravado, _, mensagens, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert len(mensagens) == 1
    news_log_id, pares = mensagens[0]
    assert news_log_id == 999  # id fake devolvido por log_sent_news no fixture
    assert pares == [("5534999945010", "MSG_ID_TESTE_0")]


@pytest.mark.unit
def test_check_news_sem_id_de_log_nao_grava_mensagens(monkeypatch):
    """log_sent_news falhou (devolveu None) — log_alert_messages não pode
    rodar com news_log_id inválido; a FK nem aceitaria. update_news_log_conteudo
    também não: não haveria linha para atualizar. E a captura em si (até 75s,
    35 créditos de ScraperAPI no caminho de render) nem roda — gastaria custo
    sem ter onde gravar o resultado (Conserto 1, 19/08/2026)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    mensagens: list = []
    atualizacoes: list = []
    capturas: list = []
    monkeypatch.setattr(alert_checker.supabase, "log_sent_news", lambda entry: None)
    monkeypatch.setattr(alert_checker.supabase, "log_alert_messages",
                        lambda *a, **k: mensagens.append((a, k)))
    monkeypatch.setattr(alert_checker.supabase, "update_news_log_conteudo",
                        lambda *a, **k: atualizacoes.append((a, k)))
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": capturas.append(url)
                        or alert_checker._CAPTURA_VAZIA)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "")
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(alert_checker, "_broadcast_com_ids",
                        lambda msg, recipients, errors=None: [("5534999945010", "MSG_ID")])
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [_ARTIGO])
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(_CLASSIFICACAO))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert atualizacoes == []
    assert capturas == []

    assert mensagens == []


# ── Defeito 1: o 🔗 do alerta levava o link do Google (403) — 19/08/2026 ──

_URL_GN = "https://news.google.com/rss/articles/abc"
_URL_REAL = "https://www.wisfarmer.com/story/news/2026/08/19/usda-boosts-corn"
_CAPTURA_OK = ("Texto da matéria.", "read_article:trafilatura", None)


@pytest.mark.unit
def test_capture_conteudo_devolve_a_url_canonica_do_publicador(monkeypatch):
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"url": url, "conteudo": "Texto.",
                                   "url_final": "https://energynow.ca/materia"},
    )
    captura = alert_checker._capture_conteudo(_URL_GN)
    assert captura.url_final == "https://energynow.ca/materia"


@pytest.mark.unit
def test_capture_conteudo_sem_canonica_devolve_url_final_none(monkeypatch):
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"url": url, "conteudo": "Texto."},
    )
    assert alert_checker._capture_conteudo("https://x.com/a").url_final is None


@pytest.mark.unit
def test_capture_conteudo_registra_qual_extrator_leu_a_materia(monkeypatch):
    """Sem rótulo, `conteudo_fonte` diz "read_article" tanto para o extrator
    novo quanto para o caminho bruto — que é justamente o que produziu o
    defeito 3 (entulho do site no lugar da matéria). Sem distinguir os dois,
    a próxima regressão volta calada (achado do Apolo, 19/08/2026)."""
    monkeypatch.setattr(
        alert_checker.web_search, "read_article",
        lambda url, timeout=30.0, url_publisher="": {"url": url, "conteudo": "Texto.", "extrator": "html_bruto"},
    )
    assert alert_checker._capture_conteudo("https://x.com/a").fonte == "read_article:html_bruto"


@pytest.mark.unit
def test_check_news_manda_o_link_do_publicador_na_mensagem(monkeypatch):
    """O link do Google Notícias continua no banco (é a chave de dedup), mas
    quem vai para o WhatsApp é o endereço do publicador — o do Google devolve
    403 no clique (medido na primeira validação em produção, 18/08/2026).
    Resolvido pelo próprio Google em 0,4-0,8s, sem crédito de ScraperAPI."""
    _, enviadas, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert _URL_REAL in enviadas[0]
    assert "news.google.com" not in enviadas[0]


@pytest.mark.unit
def test_check_news_sem_resolver_mantem_o_link_original(monkeypatch):
    """A resolução usa endpoint interno do Google: pode mudar sem aviso, e o IP
    de datacenter da Vercel pode receber outra coisa. Falhar volta ao
    comportamento anterior — link ruim é melhor que mensagem sem link."""
    _, enviadas, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "")

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert _URL_GN in enviadas[0]


@pytest.mark.unit
def test_check_news_envia_antes_de_capturar_o_texto(monkeypatch):
    """A leitura da matéria (até 75s no caminho de render) NÃO pode ficar na
    frente do envio: se a função da Vercel estourar os 300s ali, o alerta não
    sai. Descobrir o link é barato e vem antes; ler a matéria é caro e vem
    depois (revisão do Apolo, 19/08/2026)."""
    ordem = []
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": ordem.append("captura") or alert_checker.Captura(*_CAPTURA_OK))
    monkeypatch.setattr(alert_checker, "_broadcast_com_ids",
                        lambda msg, recipients, errors=None: ordem.append("broadcast")
                        or [("5534999945010", "MSG_ID")])

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert ordem == ["broadcast", "captura"]


@pytest.mark.unit
def test_check_news_entrega_falha_nao_gasta_credito_de_captura(monkeypatch):
    """Evolution fora do ar: `sent == 0`, nada é gravado nem marcado. Capturar
    aí queimaria 35 créditos do ScraperAPI a cada 15 minutos sem entregar
    mensagem nenhuma (achado do Apolo, 19/08/2026)."""
    capturas = []
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO, sent=0)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": capturas.append(url) or alert_checker._CAPTURA_VAZIA)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert capturas == []


@pytest.mark.unit
def test_check_news_captura_le_o_link_ja_resolvido(monkeypatch):
    """Resolver uma vez e reaproveitar: com o endereço real na mão a leitura
    dispensa o render (1 crédito e ~6s em vez de 35 créditos e ~57s)."""
    lidos = []
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": lidos.append(url) or alert_checker.Captura(*_CAPTURA_OK))

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert lidos == [_URL_REAL]


@pytest.mark.unit
def test_check_news_grava_url_final_no_log(monkeypatch):
    """O bloco <noticia_citada> mostra a URL ao modelo quando o usuário responde
    citando o alerta — com o link do Google ali, o agente repete o 403 na
    conversa."""
    gravado, _, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert gravado["url_final"] == _URL_REAL
    assert gravado["url"] == _URL_GN


@pytest.mark.unit
def test_check_news_url_final_absurda_nao_apaga_o_link(monkeypatch):
    """`_url_exibivel` reprova link gigante — se a escolha ignorasse isso, a
    mensagem sairia SEM 🔗, pior que o 403 que esta mudança veio consertar."""
    _, enviadas, _, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: "https://x.com/" + "a" * 1200)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert _URL_GN in enviadas[0]


# ── 2ª revisão do Apolo (19/08/2026): prazo duro e cruzamento com o publicador ──

@pytest.mark.unit
def test_link_para_mensagem_passa_o_prazo_do_alerta(monkeypatch):
    """Achado 2 (2ª revisão): isto roda ANTES do broadcast, então segurar demais
    = alerta não sai — um servidor gotejando segurou a resolução por 40,7s com
    timeout de 10s. O teto ABSOLUTO mora dentro de `resolve_google_news` (3ª
    revisão, achado 2: o caminho do chat precisava dele também); o que este lado
    tem que garantir é PASSAR o orçamento do alerta, senão o teto vira o default
    e ninguém percebe."""
    vistos = {}
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: vistos.update(k) or "")

    assert alert_checker._link_para_mensagem(_URL_GN) == _URL_GN
    assert vistos["timeout"] == alert_checker._LINK_PRAZO


@pytest.mark.unit
def test_check_news_leva_o_publicador_ate_a_captura(monkeypatch):
    """Achado 7 (3ª revisão): os dois lados do elo estavam testados, o MEIO não
    — trocar `url_publisher` por outra variável aqui passava nos 520 testes. Sem
    ele, a canônica da página perde a única contraprova de host que tem."""
    vistos = {}
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker, "_capture_conteudo",
                        lambda url, url_publisher="": vistos.update(pub=url_publisher)
                        or alert_checker._CAPTURA_VAZIA)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert vistos["pub"] == _ARTIGO["url_publisher"]


@pytest.mark.unit
def test_link_para_mensagem_confere_o_destino_com_o_publicador(monkeypatch):
    """Achado 4: o `<source url>` do RSS (100 de 100 itens medidos) é o
    contraprova de que o endereço devolvido pelo Google é mesmo daquele
    veículo. Sem passar isso adiante, o cruzamento não acontece."""
    vistos = {}

    def espia(url, **k):
        vistos.update(k)
        return _URL_REAL

    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news", espia)
    alert_checker._link_para_mensagem(_URL_GN, "https://www.wisfarmer.com")
    assert vistos.get("host_esperado") == "https://www.wisfarmer.com"


@pytest.mark.unit
def test_capture_conteudo_passa_o_publicador_para_a_leitura(monkeypatch):
    """A canônica da página só é aceita se bater com o host do publicador
    (achado 1) — o dado precisa chegar lá."""
    vistos = {}

    def fake_read_article(url, timeout=30.0, url_publisher=""):
        vistos["url_publisher"] = url_publisher
        return {"url": url, "conteudo": "x" * 300, "extrator": "trafilatura"}

    monkeypatch.setattr(alert_checker.web_search, "read_article", fake_read_article)
    alert_checker._capture_conteudo(_URL_GN, "https://www.wisfarmer.com")
    assert vistos["url_publisher"] == "https://www.wisfarmer.com"


@pytest.mark.unit
def test_check_news_leva_o_publicador_do_feed_ate_a_resolucao(monkeypatch):
    """Ponta a ponta: o `url_publisher` que veio do RSS tem que chegar em quem
    confere o destino."""
    vistos = {}
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: vistos.update(k) or _URL_REAL)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert vistos.get("host_esperado") == _ARTIGO["url_publisher"]


# ── 5ª revisão do Apolo (19/08/2026) ──────────────────────────────────────

@pytest.mark.unit
def test_check_news_nao_sobrescreve_o_link_resolvido_pela_canonica(monkeypatch):
    """A canônica confere HOST, não profundidade de caminho: uma página que
    declara `canonical` genérica (a home do veículo) fazia o UPDATE gravar a
    home por cima do deep link que o Google já tinha confirmado. O comentário
    do código sempre disse que a canônica só entra quando a resolução falhou —
    o código é que passava `captura.url_final` SEMPRE."""
    atualizacoes = []
    _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)
    monkeypatch.setattr(alert_checker.web_search, "resolve_google_news",
                        lambda url, **k: _URL_REAL)
    monkeypatch.setattr(
        alert_checker, "_capture_conteudo",
        lambda url, url_publisher="": alert_checker.Captura(
            "Texto.", "read_article:trafilatura", "https://www.wisfarmer.com/"),
    )
    monkeypatch.setattr(alert_checker.supabase, "update_news_log_conteudo",
                        lambda *a: atualizacoes.append(a))

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert atualizacoes[0][3] is None


@pytest.mark.unit
def test_link_para_mensagem_sobrevive_a_thread_recusada(monkeypatch):
    """O invólucro com prazo criou um caminho de exceção que não existia:
    `Thread.start()` levanta `RuntimeError` quando o SO recusa a thread, e isso
    sobe na thread CHAMADORA. Aqui roda antes do broadcast — sem defesa, a
    rodada inteira sai sem alerta nenhum por causa do enfeite do link."""
    def recusa(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(alert_checker.web_search.threading.Thread, "start", recusa)
    assert alert_checker._link_para_mensagem(_URL_GN) == _URL_GN
