import pytest

from backend.services import report_engine

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def test_safe_collect_mascara_chave_de_coletor_que_vaza():
    """Achado 3, revisão 18/08/2026 (4ª rodada): gêmeo exato de
    reporter._safe_collect (ver test_reporter_safe_collect_leak.py), mas
    ficou cru — sem sanitize_error. É o chokepoint do caminho de RELATÓRIO
    AGENDADO (report_engine._collect → generate_sections → json.dumps(ctx)
    vira o prompt de toda seção). Não há vazamento vivo hoje (nenhum dos 8
    coletores de report_engine._collect deixa a chave escapar sem mascarar
    internamente), mas o mesmo argumento que endureceu reporter._safe_collect
    ("coletor futuro sem proteção") vale igual aqui — DRY: duas verdades num
    lugar só."""
    def fn_que_vaza():
        raise RuntimeError(f"falha ao chamar http://api.exemplo.com?api_key={_CHAVE_FALSA}&x=1")

    result = report_engine._safe_collect(fn_que_vaza)
    assert "erro" in result
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


def test_safe_collect_repassa_resultado_normal():
    assert report_engine._safe_collect(lambda: {"ok": True}) == {"ok": True}
