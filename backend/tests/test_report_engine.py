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


import datetime as _dt


@pytest.mark.unit
def test_generate_sections_orders_and_prefixes_greeting(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})
    monkeypatch.setattr(re, "_render", lambda s, ctx, client: f"CORPO::{s}")

    class _FixedDate(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 19, 7, 0, 0, tzinfo=tz)

    monkeypatch.setattr(re._dt, "datetime", _FixedDate)

    out = re.generate_sections({"bolsas": True, "analise": True}, {"name": "Gustavo Mouro"},
                               client=object())
    assert len(out) == 2
    # ordem fixa: bolsas vem antes de analise
    assert out[0].endswith("CORPO::bolsas")
    assert out[1] == "CORPO::analise"
    # saudação só na 1ª mensagem, com primeiro nome e data
    assert out[0].startswith("Bom dia, *Gustavo*! | 19/06/2026")
    assert "Bom dia" not in out[1]


@pytest.mark.unit
def test_generate_sections_omits_failed_section(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})

    def render(s, ctx, client):
        if s == "bolsas":
            raise RuntimeError("claude down")
        return f"CORPO::{s}"

    monkeypatch.setattr(re, "_render", render)
    out = re.generate_sections({"bolsas": True, "commodities": True}, {"name": "X"}, client=object())
    assert out == [f"{re._greeting_header({'name': 'X'})}\n\nCORPO::commodities"]


@pytest.mark.unit
def test_generate_sections_none_uses_all(monkeypatch):
    monkeypatch.setattr(re, "_collect", lambda s: {"data": {}})
    monkeypatch.setattr(re, "_render", lambda s, ctx, client: f"CORPO::{s}")
    out = re.generate_sections(None, {"name": "X"}, client=object())
    assert len(out) == len(re._SECTION_ORDER)


@pytest.mark.unit
def test_greeting_header_without_name():
    h = re._greeting_header({"name": ""})
    assert "*" not in h  # sem nome em negrito
    assert "|" in h      # mantém a data
