"""O PLACAR do `news_recall_eval` — nao o eval rodando, o que ele conta.

O arquivo nasceu sem teste nenhum e tres mutacoes sobreviviam a suite inteira
(`_EVASIVAS = ()`, `coerente = True` sempre, `recuperou = True` sempre). E era
justamente nele que eu tinha consertado defeito de placar a mao, olhando a
saida — a proxima pessoa nao vai olhar.

Todos rodam sem API: `_rodar` e substituido por respostas prontas.
"""
from unittest.mock import patch

import pytest

from backend.evals import news_recall_eval as ev

pytestmark = pytest.mark.unit


def _placar(respostas: list[str], capsys=None) -> dict:
    """Roda `main()` com as respostas prontas e devolve o placar."""
    it = iter(respostas)
    with patch.object(ev, "_rodar", lambda *a, **k: next(it)), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        import io
        import json
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ev.main()
        saida = buf.getvalue()
    return json.loads(saida[saida.index("{"):saida.rindex("}") + 1])


def test_contradicao_entre_turnos_reprova_mesmo_com_numeros_legitimos():
    """ACHADO 3, o mais grave. A primeira versao so conferia se o percentual
    pertencia a lista branca {61,62,51} — entao o agente podia dizer milho 61%,
    depois 62%, depois 51%, e o placar aprovava. Isso e LITERALMENTE a forma do
    incidente de 18/08: cinco respostas diferentes para o mesmo fato."""
    p = _placar([
        "O milho esta em 61% bom/excelente, segundo o Crop Progress.",
        "Na verdade o milho esta em 62% bom/excelente.",
        "Como eu disse, o milho esta em 51%.",
    ])
    assert p["percentuais_inventados"] == [], "os tres numeros SAO da lista branca"
    assert p["contradicoes"] == {"milho": ["51", "61", "62"]}
    assert p["coerente_entre_respostas"] is False, "contradicao passou como coerente"


def test_mesma_cultura_com_mesmo_numero_nos_tres_turnos_e_coerente():
    p = _placar([
        "Milho em 61% bom/excelente (Crop Progress).",
        "O Crop Progress do USDA/NASS: milho 61%, soja 62%.",
        "Sim, milho 61% — dado de 17 de agosto.",
    ])
    assert p["contradicoes"] == {}
    assert p["coerente_entre_respostas"] is True


def test_numero_fora_do_artigo_reprova_mesmo_sem_contradicao():
    p = _placar([
        "Milho em 67% bom/excelente.",
        "Milho em 67% bom/excelente, Crop Progress.",
        "Milho 67%, sim.",
    ])
    assert p["percentuais_inventados"] == ["67"]
    assert p["coerente_entre_respostas"] is False


def test_resposta_muda_mas_educada_nao_conta_como_resposta():
    """ACHADO 4: a lista negra de frases evasivas era corrida que o modelo ganha
    so reformulando. Estas tres nao usam nenhuma frase da lista antiga e mesmo
    assim nao dizem nada."""
    p = _placar([
        "Boa pergunta! Esse material trata da evolucao das lavouras.",
        "Prefiro nao afirmar nada sem conferir a fonte.",
        "Nao tenho como confirmar isso agora.",
    ])
    assert p["respondeu_de_fato"] == 0, "resposta sem conteudo contou como resposta"


def test_papagaiar_o_enunciado_nao_conta_como_recuperar():
    """ACHADO 5: a pergunta 1 ja contem "perde qualidade" e "Reuters". Com esses
    marcadores, repetir o texto do proprio usuario dava `recuperou: True` — a
    metrica-titulo do eval."""
    p = _placar([
        "Sobre *Milho dos EUA perde qualidade* (_Reuters_): pode me mandar o link?",
        "Idem.",
        "Idem.",
    ])
    assert p["recuperou_no_primeiro_turno"] is False


def test_recuperar_de_verdade_conta():
    p = _placar([
        "E o Crop Progress do USDA/NASS: milho 61% bom/excelente em 17 de agosto.",
        "Crop Progress, 17/08.",
        "2026.",
    ])
    assert p["recuperou_no_primeiro_turno"] is True
    assert p["respondeu_de_fato"] == 3


def test_marcadores_de_recuperacao_nao_podem_estar_no_enunciado():
    """A trava que impede o achado 5 de voltar quando alguem mexer nas perguntas."""
    enunciado = " ".join(ev._PERGUNTAS).lower()
    for m in ev._MARCAS_RECUPERACAO:
        assert m.lower() not in enunciado, f"{m} esta na propria pergunta"


def test_o_eval_reprova_na_largada_se_alguem_puser_o_marcador_na_pergunta():
    with patch.object(ev, "_PERGUNTAS", ["e o Crop Progress de hoje?"]):
        with pytest.raises(SystemExit, match="enunciado"):
            ev._conferir_marcadores()
