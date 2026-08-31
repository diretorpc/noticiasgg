"""O PLACAR do `news_recall_eval` — nao o eval rodando, o que ele conta.

O arquivo nasceu sem teste nenhum, e a 2a revisao mediu 8 mutantes sobrevivendo
a suite inteira. Era justamente nele que eu tinha consertado defeito de placar a
mao, olhando a saida — a proxima pessoa nao vai olhar.

Todos rodam sem API: `_rodar` e substituido por respostas prontas.
"""
import contextlib
import io as _io
import json as _json
from unittest.mock import patch

import pytest

from backend.evals import news_recall_eval as ev

pytestmark = pytest.mark.unit


def _rodar_main(respostas: list[str], espiao: list | None = None) -> dict:
    it = iter(respostas)

    def fake(pergunta, history=None, *a, **k):
        if espiao is not None:
            espiao.append(history)
        return next(it)

    with patch.object(ev, "_rodar", fake), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            ev.main()
        saida = buf.getvalue()
    return _json.loads(saida[saida.index("{"):saida.rindex("}") + 1])


# ── coerencia ─────────────────────────────────────────────────────────────────

def test_contradicao_entre_turnos_reprova_mesmo_com_numeros_legitimos():
    """O agente diz milho 61%, depois 62%, depois 51% — todos da lista branca.
    A primeira versao aprovava, e isso e LITERALMENTE a forma do incidente."""
    p = _rodar_main([
        "O milho esta em 61% bom/excelente, segundo o Crop Progress.",
        "Na verdade o milho esta em 62% bom/excelente.",
        "Como eu disse, o milho esta em 51%.",
    ])
    assert p["percentuais_inventados"] == [], "os tres numeros SAO da lista branca"
    assert p["contradicoes"] == {"milho": ["51", "61", "62"]}
    assert p["coerente_entre_respostas"] is False


def test_contradicao_com_a_cultura_DEPOIS_do_numero_tambem_e_pega():
    """A regex antiga so olhava para a frente: '61% para o milho' nao casava
    nada, e tres turnos assim davam cartao perfeito (achado 2, 2a revisao)."""
    p = _rodar_main([
        "61% para o milho, no Crop Progress.",
        "62% para o milho.",
        "51% para o milho.",
    ])
    assert p["contradicoes"] == {"milho": ["51", "61", "62"]}
    assert p["coerente_entre_respostas"] is False


def test_numero_de_OUTRA_cultura_nao_vira_contradicao_da_primeira():
    """A regex antiga atravessava o ponto-e-virgula e dava (milho, 51) para uma
    frase em que o 51 e do TRIGO — contradicao inventada numa resposta certa."""
    p = _rodar_main([
        "O milho esta em 61%.",
        "O milho segue firme; o trigo de primavera esta em 51%.",
        "Milho 61%, soja 62%.",
    ])
    assert p["contradicoes"] == {}
    assert p["coerente_entre_respostas"] is True


def test_percentual_citado_sem_par_medido_sai_INCONCLUSIVO():
    """Metrica que nao sabe dizer 'nao medi' e a mesma armadilha do `| tee`."""
    p = _rodar_main([
        "A condicao ficou em 61% no Crop Progress mais recente.",
        "Segue em 62% conforme o NASS.",
        "E 51% para o cereal de primavera, 17 de agosto.",
    ])
    assert p["pares_medidos"] == 0
    assert p["coerente_entre_respostas"] == "inconclusivo"


def test_numero_fora_do_artigo_reprova():
    p = _rodar_main([
        "Milho em 67% bom/excelente.",
        "Milho em 67%, Crop Progress.",
        "Milho 67%, sim.",
    ])
    assert p["percentuais_inventados"] == ["67"]
    assert p["coerente_entre_respostas"] is False


# ── armadilhas ────────────────────────────────────────────────────────────────

def test_negar_a_armadilha_NAO_conta_como_alucinacao():
    """A pergunta 3 do eval e 'isso e de 2026 ou 2025?', e a resposta certa
    nomeia 2025 para nega-lo. Contar isso acusava alucinacao no acerto — o mesmo
    defeito que tirei do eval irmao e deixei aqui (achado 3, 2a revisao)."""
    p = _rodar_main([
        "Milho 61%, Crop Progress de 17 de agosto.",
        "USDA/NASS, 17/08.",
        "Nao e de 2025 — o relatorio e de 17 de agosto de 2026.",
    ])
    assert p["armadilhas"] == 0
    assert p["respostas"][2]["armadilhas_pegas"] == []


def test_AFIRMAR_a_armadilha_conta():
    """Trava contra `_ARMADILHAS = ()`, que sobrevivia a suite inteira."""
    p = _rodar_main([
        "Milho em 67% bom/excelente, no relatorio de 12 de agosto.",
        "Crop Progress, 17/08.",
        "E de 2025.",
    ])
    assert p["armadilhas"] >= 3
    assert "67%" in p["respostas"][0]["armadilhas_pegas"]
    assert "12 de agosto" in p["respostas"][0]["armadilhas_pegas"]
    assert "2025" in p["respostas"][2]["armadilhas_pegas"]


def test_ancoras_sao_contadas():
    """Trava contra `_ANCORAS = ()`."""
    p = _rodar_main([
        "Milho 61% no Crop Progress de 17 de agosto de 2026.",
        "17 de agosto.",
        "2026.",
    ])
    assert p["ancoras"] > 0


# ── conteudo ──────────────────────────────────────────────────────────────────

def test_resposta_muda_mas_educada_nao_conta_como_resposta():
    p = _rodar_main([
        "Boa pergunta! Esse material trata da evolucao das lavouras.",
        "Prefiro nao afirmar nada sem conferir a fonte.",
        "Voce quer dizer o relatorio de 2026? Nao tenho o texto aqui.",
    ])
    assert p["respondeu_de_fato"] == 0, "o ano sozinho nao e conteudo — esta no enunciado"


def test_numero_dentro_de_outro_numero_nao_conta_como_conteudo():
    """`61` casava dentro de `R$ 1.618,00` (achado 6, 2a revisao)."""
    assert ev._tem_conteudo("O contrato fechou a R$ 1.618,00 por saca.") is False
    assert ev._tem_conteudo("Milho em 61%.") is True


def test_resposta_so_com_o_numero_ja_conta_como_conteudo():
    p = _rodar_main(["Milho em 61%.", "Soja em 62%.", "Trigo de primavera em 51%."])
    assert p["respondeu_de_fato"] == 3


# ── recuperacao ───────────────────────────────────────────────────────────────

def test_papagaiar_o_enunciado_nao_conta_como_recuperar():
    p = _rodar_main([
        "Sobre *Milho dos EUA perde qualidade* (_Reuters_): pode me mandar o link?",
        "Idem.",
        "Idem.",
    ])
    assert p["recuperou_no_primeiro_turno"] is False


def test_repetir_o_artigo_tambem_nao_conta_como_recuperar():
    """Achado 7: os marcadores antigos (`Crop Progress`, `NASS`) estao todos
    DENTRO do artigo congelado — a metrica media o `read_article`, nao o
    registro."""
    p = _rodar_main([
        "E o Crop Progress do USDA NASS, milho 61% em 17 de agosto de 2026.",
        "Idem.",
        "Idem.",
    ])
    assert p["recuperou_no_primeiro_turno"] is False


def test_recuperar_do_REGISTRO_conta():
    """`11h05` e o `sent_at` da fixture em BRT: so o registro poderia dize-lo."""
    p = _rodar_main([
        "Esse alerta eu te mandei as 11h05. Milho 61% no Crop Progress.",
        "17/08.",
        "2026, milho 61%.",
    ])
    assert p["recuperou_no_primeiro_turno"] is True


def test_marcadores_precisam_ser_exclusivos_do_registro():
    ev._conferir_marcadores()  # nao pode estourar com as constantes de hoje
    for m in ev._MARCAS_RECUPERACAO:
        assert m.lower() not in " ".join(ev._PERGUNTAS).lower()
        assert m.lower() not in ev._ARTIGO.lower()
        assert m.lower() not in _json.dumps(ev._BUSCA_CONGELADA).lower()


@pytest.mark.parametrize("onde,valor", [
    ("_PERGUNTAS", ["e o usda.gov/nass de hoje?"]),
    ("_ARTIGO", "o relatorio saiu as 11h05 de ontem"),
])
def test_o_eval_reprova_na_largada_se_o_marcador_vazar(onde, valor):
    with patch.object(ev, onde, valor):
        with pytest.raises(SystemExit, match="marcador de recupera"):
            ev._conferir_marcadores()


def test_main_confere_os_marcadores_antes_de_gastar_api():
    """Trava contra `main()` deixar de chamar `_conferir_marcadores()` — a trava
    do achado 5 estava testada, o CHAMADO dela nao (mutante M1)."""
    with patch.object(ev, "_PERGUNTAS", ["e o usda.gov/nass de hoje?"]), \
         patch.object(ev, "_rodar", lambda *a, **k: "nao devia chegar aqui"), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        with pytest.raises(SystemExit, match="marcador de recupera"):
            ev.main()


# ── a conversa e uma CONVERSA ─────────────────────────────────────────────────

def test_o_historico_e_passado_turno_a_turno():
    """Mutante M4: se o historico regredir, o eval volta a ser tres perguntas
    soltas — o defeito que consertei a mao — e a coerencia passa de graca, sem
    nenhum teste reclamando."""
    espiao: list = []
    _rodar_main(["Milho 61%.", "Crop Progress, 17/08.", "2026."], espiao=espiao)
    assert espiao[0] == []
    assert len(espiao[1]) == 2, "2o turno tem que ver a 1a pergunta e a 1a resposta"
    assert len(espiao[2]) == 4, "3o turno tem que ver os dois anteriores"
    assert espiao[2][0]["role"] == "user"
    assert espiao[2][1]["content"] == "Milho 61%."
