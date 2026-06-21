import pytest
from backend.services import report_prompts


@pytest.mark.unit
def test_all_sections_have_default_prompt():
    for s in report_prompts.SECTIONS:
        assert report_prompts.DEFAULTS[s].strip()


@pytest.mark.unit
def test_prompts_have_no_greeting_instruction():
    # greeting foi removido na migração
    for s in report_prompts.SECTIONS:
        body = report_prompts.DEFAULTS[s]
        assert "SAUDACAO" not in body
        assert "[SAUDACAO]" not in body


@pytest.mark.unit
def test_get_prompt_prefers_config(monkeypatch):
    monkeypatch.setattr(report_prompts.config, "get_str",
                        lambda key, default: "PROMPT DO PAINEL" if key == "report_prompt_bolsas" else default)
    assert report_prompts.get_prompt("bolsas") == "PROMPT DO PAINEL"


@pytest.mark.unit
def test_get_prompt_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(report_prompts.config, "get_str", lambda key, default: default)
    assert report_prompts.get_prompt("commodities") == report_prompts.DEFAULTS["commodities"]


@pytest.mark.unit
def test_get_prompt_unknown_section_raises():
    with pytest.raises(KeyError):
        report_prompts.get_prompt("inexistente")


@pytest.mark.unit
def test_describe_prompts_marks_custom_and_default(monkeypatch):
    overrides = {"report_prompt_bolsas": "MEU PROMPT BOLSAS"}
    monkeypatch.setattr(report_prompts.config, "get",
                        lambda key, default=None: overrides.get(key, default))

    out = {p["section"]: p for p in report_prompts.describe_prompts()}

    assert set(out) == set(report_prompts.SECTIONS)
    assert out["bolsas"]["is_custom"] is True
    assert out["bolsas"]["value"] == "MEU PROMPT BOLSAS"
    assert out["bolsas"]["default"] == report_prompts.DEFAULTS["bolsas"]

    assert out["commodities"]["is_custom"] is False
    assert out["commodities"]["value"] == report_prompts.DEFAULTS["commodities"]


@pytest.mark.unit
def test_describe_prompts_blank_override_is_not_custom(monkeypatch):
    monkeypatch.setattr(report_prompts.config, "get",
                        lambda key, default=None: "   " if key == "report_prompt_analise" else default)
    out = {p["section"]: p for p in report_prompts.describe_prompts()}
    assert out["analise"]["is_custom"] is False
    assert out["analise"]["value"] == report_prompts.DEFAULTS["analise"]
