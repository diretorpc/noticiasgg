import pytest

from backend.services import reporter

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def test_safe_collect_mascara_chave_de_coletor_que_vaza():
    """_safe_collect é a escotilha final antes de `json.dumps(context)` entrar
    na mensagem do usuário em TODA conversa (generate_report). Mesmo que cada
    coletor já se proteja, este é o único ponto que os 8 coletores de
    _COLLECTORS atravessam sempre — por isso mascara de novo aqui."""
    def fn_que_vaza():
        raise RuntimeError(f"falha ao chamar http://api.exemplo.com?api_key={_CHAVE_FALSA}&x=1")

    result = reporter._safe_collect(fn_que_vaza)
    assert "erro" in result
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


def test_safe_collect_repassa_resultado_normal():
    assert reporter._safe_collect(lambda: {"ok": True}) == {"ok": True}
