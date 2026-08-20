from unittest.mock import MagicMock, patch

import pytest

from backend.services import reporter, supabase

pytestmark = pytest.mark.unit


def _resp(payload, status=200):
    r = MagicMock(status_code=status)
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=payload)
    return r


def _cliente(respostas):
    """Cliente httpx falso que devolve as respostas na ordem em que forem pedidas."""
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    c.get = MagicMock(side_effect=respostas)
    return c


def test_sem_telefone_le_a_lista_inteira_em_uma_consulta_so():
    c = _cliente([_resp([{"news_id": "a"}])])
    with patch.object(supabase, "_client", return_value=c):
        saida = supabase.get_news_log(hours=72, limit=20)
    assert saida == {"itens": [{"news_id": "a"}]}
    assert c.get.call_count == 1
    assert "news_log_messages" not in c.get.call_args_list[0][0][0]


def test_com_telefone_filtra_pelo_que_chegou_naquele_numero():
    """Achado 3 do Apolo (20/08/2026): `news_log` nao tem destinatario, e so
    parte dos usuarios autorizados recebe alerta. Sem este filtro, quem nunca
    recebeu ouvia "te mandei isto em 19/08 as 13h05" — falso positivo
    autoritario. O dado esta em `news_log_messages.phone` (migration 008)."""
    mensagens = _resp([{"news_log_id": 7}, {"news_log_id": 3}, {"news_log_id": 7}])
    noticias = _resp([{"news_id": "b"}])
    c = _cliente([mensagens, noticias])
    with patch.object(supabase, "_client", return_value=c):
        saida = supabase.get_news_log(hours=72, limit=20, phone="5534999945010")

    assert saida == {"itens": [{"news_id": "b"}]}
    primeira, segunda = (ch[0][0] for ch in c.get.call_args_list)
    assert primeira.startswith("/news_log_messages?phone=eq.5534999945010")
    assert "sent_at=gte." in primeira, "a janela tem que ser cortada na tabela de mensagens"
    # ids deduplicados e ordenados: a mesma noticia aparece uma vez por
    # destinatario, e o telefone filtrado pode ter mais de uma linha por engano.
    assert "id=in.(3,7)" in segunda
    # A janela NAO se repete na segunda consulta: `news_log_messages.sent_at`
    # (hora em que chegou no telefone) e `news_log.sent_at` (hora do registro)
    # sao colunas diferentes. Cortar duas vezes derruba a linha da borda e apaga
    # o sinal `truncado` exatamente quando ele importa.
    assert "sent_at=gte." not in segunda


def test_telefone_sem_nenhum_alerta_nao_dispara_a_segunda_consulta():
    c = _cliente([_resp([])])
    with patch.object(supabase, "_client", return_value=c):
        saida = supabase.get_news_log(hours=72, limit=20, phone="5511999999999")
    assert saida == {"itens": []}
    assert "aviso" not in saida, "vazio por escopo nao e falha de leitura"
    assert c.get.call_count == 1


def test_falha_na_consulta_de_mensagens_vira_aviso_e_nao_lista_vazia():
    """O modo de falha perigoso: se a primeira consulta estourasse em silencio,
    TODO usuario passaria a ouvir "nao te mandei nada". Tem que virar aviso."""
    ruim = MagicMock(status_code=500)
    ruim.raise_for_status = MagicMock(side_effect=RuntimeError("500"))
    c = _cliente([ruim])
    with patch.object(supabase, "_client", return_value=c):
        saida = supabase.get_news_log(hours=72, limit=20, phone="5534999945010")
    assert saida["itens"] == []
    assert saida["aviso"]

    # e a ferramenta traduz isso para "nao conferi", nunca para "nao enviei"
    with patch.object(supabase, "get_news_log", return_value=saida):
        resultado = reporter._get_sent_news(phone="5534999945010")
    assert resultado["consulta_ok"] is False


def test_a_ferramenta_declara_o_escopo_da_lista():
    """Sem telefone (evals, chamada interna) a lista e a da audiencia inteira.
    O modelo precisa ler isso antes de escrever "te mandei"."""
    with patch.object(supabase, "get_news_log", return_value={"itens": []}):
        pessoal = reporter._get_sent_news(phone="5534999945010")
        geral = reporter._get_sent_news()
    assert pessoal["escopo"] == "enviado a este usuário"
    assert "não necessariamente a este usuário" in geral["escopo"]
    assert "a este usuário" in pessoal["aviso"]
    assert "à lista de alertas" in geral["aviso"]
