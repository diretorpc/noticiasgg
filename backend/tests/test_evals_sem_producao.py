"""A trava que impede um eval de ler o Supabase de producao.

Os evals rodam a mao e no CI semanal, sem ninguem olhando. Se um deles comecar
a ler producao, o sintoma e sutil: o numero do relatorio muda de uma semana
para outra e parece variacao do modelo. Estes testes sao o que impede isso de
voltar calado.
"""
import json
from pathlib import Path

import pytest

from backend.evals._sem_supabase import NEWS_LOG_PADRAO, TravaDoEval, supabase_congelado
from backend.services import reporter, supabase

pytestmark = pytest.mark.unit


def test_dentro_da_trava_a_ferramenta_responde_a_fixture():
    with supabase_congelado():
        saida = reporter._get_sent_news(phone="5534999945010")
    assert saida["consulta_ok"] is True
    assert saida["noticias"][0]["titulo"] == NEWS_LOG_PADRAO[0]["titulo_pt"]
    assert saida["noticias"][0]["url"] == NEWS_LOG_PADRAO[0]["url_final"]


def test_a_fixture_respeita_o_contrato_de_hoje_e_nao_o_do_plano():
    """O plano escrito mandava devolver uma LISTA. `get_news_log` devolve
    `{"itens": [...], "truncado": bool}` desde a Story 2 — lista crua faz
    `_get_sent_news` estourar em `registro.get`. Mesmo erro que o plano da
    Story 2 tinha; nao pode entrar de novo pela porta do eval."""
    with supabase_congelado():
        registro = supabase.get_news_log(hours=72, limit=20, phone="x")
    assert isinstance(registro, dict)
    assert "itens" in registro and "truncado" in registro


def test_qualquer_outro_acesso_ao_banco_ESTOURA_em_vez_de_devolver_vazio():
    """De FALHAR, nao de silenciar: mock que devolve vazio esconde o acoplamento
    novo; mock que estoura obriga quem acrescentar a proxima ferramenta a
    decidir o que ela responde no eval."""
    with supabase_congelado():
        with pytest.raises(TravaDoEval, match="Supabase de produ"):
            supabase.list_authorized()
    # BaseException de proposito: 5 das 40 funcoes de supabase.py embrulham tudo
    # num `except Exception`, e sao justamente a familia news_log — onde a proxima
    # ferramenta vai nascer. Com RuntimeError a trava era engolida ali.
    assert not issubclass(TravaDoEval, Exception)
    with supabase_congelado():
        with pytest.raises(TravaDoEval):
            supabase.get_news_by_message_id("qualquer")


def test_a_trava_solta_o_banco_de_volta_ao_sair():
    with supabase_congelado():
        pass
    assert supabase.get_news_log.__module__ == "backend.services.supabase"


def test_grounding_eval_roda_dentro_da_trava():
    """A Story 2 acrescentou uma quinta ferramenta que le o banco, e o
    `grounding_eval` so mockava as quatro antigas. A pergunta canonica dele
    ('me fale mais sobre essa noticia') e o gatilho literal dessa ferramenta.

    Medido por COMPORTAMENTO, nao casando string do codigo-fonte: a versao
    anterior exigia a linha literal `with m1, m2, m3, m4, supabase_congelado():`,
    entao quebrar a linha em duas reprovava sem defeito nenhum, e a linha dentro
    de um `if False:` passava (achado 11 do Apolo)."""
    from unittest.mock import patch as _patch

    from backend.evals import grounding_eval
    from backend.evals._sem_supabase import TravaDoEval

    def tenta_ler_o_banco(*a, **k):
        supabase.list_authorized()
        return "nao chega aqui"

    caso = {"id": "x", "pergunta": "?", "traps": [], "expected_good": []}
    with _patch.object(grounding_eval.reporter, "generate_report", tenta_ler_o_banco):
        with pytest.raises(TravaDoEval):
            grounding_eval.run_case(caso, client=None, repeats=1)


def test_o_caso_do_incidente_usa_as_chaves_que_o_eval_LE():
    """O plano escrito propunha `ancoras`/`armadilhas`. O eval le `traps` e
    `expected_good`, com `{"regex", "desc"}`. Com as chaves erradas o caso entra
    no arquivo, `n_traps` da zero, e o eval reporta 'n/a' — cobertura de
    mentira, que e pior que cobertura nenhuma."""
    casos = json.loads(
        Path("backend/evals/fixtures/grounding_cases.json").read_text(encoding="utf-8")
    )
    caso = next(c for c in casos if c["id"] == "usda_crop_progress_data_inventada")
    assert caso["traps"] and caso["expected_good"]
    for item in caso["traps"] + caso["expected_good"]:
        assert set(item) == {"regex", "desc"}, item
    assert "ancoras" not in caso and "armadilhas" not in caso


def test_as_armadilhas_do_incidente_nao_casam_com_o_artigo_congelado():
    """Armadilha que aparece no proprio corpus nao e armadilha — e um teste que
    reprova o agente por copiar a fonte direito."""
    import re

    casos = json.loads(
        Path("backend/evals/fixtures/grounding_cases.json").read_text(encoding="utf-8")
    )
    caso = next(c for c in casos if c["id"] == "usda_crop_progress_data_inventada")
    corpus = " ".join(caso["articles"].values()) + json.dumps(caso["search"])
    for trap in caso["traps"]:
        assert not re.search(trap["regex"], corpus), f"armadilha esta no corpus: {trap}"
    for bom in caso["expected_good"]:
        assert re.search(bom["regex"], corpus), f"ancora NAO esta no corpus: {bom}"


def test_a_armadilha_literal_dispara_de_verdade():
    """Ao rodar a linha de base descobri que o `regex` das armadilhas nunca era
    comparado com a resposta: `traps` so servia de contador para decidir se o
    relatorio imprimia 'n/a'. O juiz mede numero ABSURDO; as armadilhas do
    incidente de 18/08 sao plausiveis e falsas (67%, 2025, '12 de agosto'), e
    absurdas nao sao. Este teste e o que impede a medida de virar decoracao de
    novo."""
    from unittest.mock import patch as _patch

    from backend.evals import grounding_eval

    caso = {
        "id": "sintetico",
        "pergunta": "?",
        "traps": [{"regex": r"\b67\s?%", "desc": "milho a 67% — inventado"}],
        "expected_good": [{"regex": r"\b61\b", "desc": "61 esta no corpus"}],
    }
    resposta_ruim = "O milho ficou em 67% bom/excelente, contra 61 na semana."
    with _patch.object(grounding_eval.reporter, "generate_report",
                       return_value=resposta_ruim), \
         _patch.object(grounding_eval, "_judge",
                       return_value={"ancoradas": 1, "inventadas": 1, "absurdo_fato": 0,
                                     "proibidos_afirmados": 1}):
        r = grounding_eval.run_case(caso, client=None, repeats=1)

    assert r["taxa_armadilha_literal"] == "1/1", "a armadilha literal nao disparou"
    assert r["armadilhas_vistas"] == ["milho a 67% — inventado"]
    # o juiz nao viu absurdo nenhum — e por isso que a medida literal precisa existir
    assert r["taxa_armadilha"] == "0/1"
    assert r["taxa_ancora"] == "1/1"


def test_resposta_limpa_nao_dispara_armadilha_literal():
    from unittest.mock import patch as _patch

    from backend.evals import grounding_eval

    caso = {
        "id": "sintetico",
        "pergunta": "?",
        "traps": [{"regex": r"\b67\s?%", "desc": "inventado"}],
        "expected_good": [{"regex": r"\b61\b", "desc": "esta no corpus"}],
    }
    with _patch.object(grounding_eval.reporter, "generate_report",
                       return_value="O milho ficou em 61% bom/excelente."), \
         _patch.object(grounding_eval, "_judge",
                       return_value={"ancoradas": 1, "inventadas": 0, "absurdo_fato": 0,
                                     "proibidos_afirmados": 0}):
        r = grounding_eval.run_case(caso, client=None, repeats=1)
    assert r["taxa_armadilha_literal"] == "0/1"
    assert r["armadilhas_vistas"] == []
