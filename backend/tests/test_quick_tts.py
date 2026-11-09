"""Pré-check de velocidade/voz (`main._quick_tts_check`).

Ele procurava palavras soltas em QUALQUER lugar da frase e engolia pergunta de mercado
(medido em 09/11/2026, 12 de 12): "a inflação acelera em outubro?" mudava a velocidade
da fala, "qual a nova voz da oposição?" trocava a voz, "o que as vozes do mercado
dizem?" devolvia a lista de vozes — e a pergunta ficava sem resposta. Agora ele só
age quando a mensagem INTEIRA é o comando; o resto vai ao Haiku.
"""
import pytest

from backend.api.main import _quick_tts_check

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("frase,velocidade", [
    ("fala mais devagar", 0.78),
    ("Fala mais devagar.", 0.78),
    ("fale mais devagar por favor", 0.78),
    ("um pouco mais devagar por favor", 0.78),
    ("mais devagar", 0.78),
    ("velocidade mais baixa", 0.78),
    ("fala bem mais devagar", 0.7),
    ("fala muito mais lento", 0.7),
    ("fala mais rápido", 0.92),
    ("fala mais rapido!", 0.92),
    ("acelera", 0.92),
    ("fala bem mais rápido", 1.0),
    ("velocidade normal", 0.95),
    ("volta a velocidade normal", 0.95),
])
def test_comando_de_velocidade_continua_instantaneo(frase, velocidade):
    r = _quick_tts_check(frase, 0.85)
    assert r is not None and r["tts_speed"] == velocidade


@pytest.mark.parametrize("frase,voz", [
    ("muda a voz para onyx", "onyx"),
    ("Muda a voz pra echo", "echo"),
    ("voz shimmer", "shimmer"),
    ("quero a voz echo", "echo"),
    ("usa a voz nova", "nova"),
    ("troca a voz para fable", "fable"),
    ("onyx voz", "onyx"),
])
def test_comando_de_voz_continua_instantaneo(frase, voz):
    r = _quick_tts_check(frase, 0.85)
    assert r is not None and r["tts_voice"] == voz


@pytest.mark.parametrize("frase", [
    "quais vozes tem?", "quais são as vozes?", "que vozes existem", "lista as vozes",
    "mostra as vozes", "vozes disponíveis", "opções de voz",
])
def test_lista_de_vozes_continua_instantanea(frase):
    r = _quick_tts_check(frase, 0.85)
    assert r is not None and r["list_voices"] is True


@pytest.mark.parametrize("frase", [
    "a inflação acelera em outubro?",
    "o PIB acelera ou desacelera em 2027?",
    "qual a velocidade de alta do dólar essa semana?",
    "fala rápido sobre o dólar",
    "me fala rápido: o dólar subiu?",
    "fala devagar comigo que eu sou leigo, o que é Selic?",
    "o governo lançou uma voz nova no ministério?",
    "qual a nova voz da oposição no Senado?",
    "quero uma voz nova",
    "o que as vozes do mercado dizem da Selic?",
    "a economia acelera?",
    "o boi acelera a alta?",
    "o Lula falou mais devagar no discurso",
    "nova",
])
def test_frase_que_nao_e_so_o_comando_vai_ao_haiku(frase):
    assert _quick_tts_check(frase, 0.85) is None


def test_prompt_do_haiku_trata_voz_sem_nome_e_pergunta_de_conteudo():
    """Os 2 erros do Haiku nas 12 armadilhas (09/11/2026): "quero uma voz nova" gravava
    a voz chamada "nova" (já a padrão), e "me fala rápido: o dólar subiu?" mudava a
    velocidade em vez de responder."""
    from backend.api.main import _PREFERENCE_SYSTEM
    assert "quero uma voz nova" in _PREFERENCE_SYSTEM
    assert "me fala rápido: o dólar subiu?" in _PREFERENCE_SYSTEM


@pytest.mark.parametrize("frase", ["mais rápido?", "mais devagar?", "velocidade normal?", "voz onyx?"])
def test_pergunta_curta_nao_vira_comando(frase):
    """Tirar o `?` do fim fazia "mais rápido?" — dito no meio de uma conversa de
    mercado — mudar a velocidade (achado 2, 7ª revisão do Apolo). Pergunta vai ao Haiku;
    só a lista de vozes ("quais vozes tem?") aceita o `?`."""
    assert _quick_tts_check(frase, 0.85) is None


def test_mensagem_longa_de_pontuacao_nao_trava():
    r"""`re.sub(r"[\s.!?…]+$")` era quadrático: 65 mil caracteres de pontuação seguidos
    de uma letra levavam 10,66 s (achado 1, 7ª revisão do Apolo)."""
    import time
    inicio = time.perf_counter()
    _quick_tts_check("." * 65_535 + "x", 0.85)
    assert time.perf_counter() - inicio < 0.5
