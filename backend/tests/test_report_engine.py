import pytest
from backend.services import report_engine as re


class _Block:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeClient:
    """Captura kwargs e devolve um texto fixo por chamada."""
    def __init__(self, text="🌎 BOLSAS\n🇧🇷 IBOVESPA: 168277.55 pts 🔴 -0.1%"):
        self._text = text
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._text)


@pytest.mark.unit
def test_render_uses_section_prompt_and_returns_text():
    client = _FakeClient()
    ctx = re.adapt_bolsas({"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}})
    out = re._render("bolsas", ctx, client)
    assert "IBOVESPA" in out
    assert client.calls[0]["model"] == "claude-sonnet-4-6"
    # prompt da seção foi usado como system
    assert "🌎 BOLSAS" in client.calls[0]["system"]


@pytest.mark.unit
def test_render_text_section_runs_validator(monkeypatch):
    seen = {}

    def fake_validate(report, data, client):
        seen["called"] = True
        return report + " [validado]"

    monkeypatch.setattr(re.integrity, "validate_and_fix", fake_validate)
    client = _FakeClient(text="📊 ANÁLISE DO CENÁRIO\n*Visão Macro Global*\nteste")
    ctx = re.adapt_analise({"bolsas": {}, "cambio": {}}, [], {}, {}, [])
    out = re._render("analise", ctx, client)
    assert seen.get("called") is True
    assert out.endswith("[validado]")


@pytest.mark.unit
def test_render_data_section_skips_validator(monkeypatch):
    def fail_validate(*a, **k):
        raise AssertionError("validator não deve rodar em seção de dados")

    monkeypatch.setattr(re.integrity, "validate_and_fix", fail_validate)
    client = _FakeClient()
    ctx = re.adapt_bolsas({"bolsas": {}})
    re._render("bolsas", ctx, client)  # não deve levantar


@pytest.mark.unit
def test_collect_bolsas_uses_adapter(monkeypatch):
    monkeypatch.setattr(re.market, "collect",
                        lambda: {"bolsas": {"IBOVESPA": {"preco": 1, "variacao_pct": 2}}, "cambio": {}})
    ctx = re._collect("bolsas")
    assert ctx == {"data": {"bolsas": {"IBOVESPA": {"preco": 1, "variacao_pct": 2}}}}


@pytest.mark.unit
def test_collect_tolerates_collector_failure(monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(re.commodities_br, "collect", boom)
    ctx = re._collect("commodities")
    assert ctx == {"data": {"commodities": {}}}
