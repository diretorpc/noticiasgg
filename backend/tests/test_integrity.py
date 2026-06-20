import pytest
from backend.services import integrity


@pytest.mark.unit
def test_build_fact_corpus_includes_market_and_truncates():
    data = {"market": {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}},
            "news": [{"titulo": "Manchete X"}, {"titulo": "Manchete Y"}]}
    corpus = integrity.build_fact_corpus(data)
    assert "IBOVESPA" in corpus
    assert "Manchete X" in corpus
    assert len(corpus) <= 6000


@pytest.mark.unit
def test_validate_and_fix_returns_original_when_no_analysis_markers():
    class _Client:  # nunca deve ser chamado
        pass
    report = "🌎 BOLSAS\n🇧🇷 IBOVESPA: 168277.55 pts 🔴 -0.1%"
    out = integrity.validate_and_fix(report, {"market": {}}, _Client())
    assert out == report
