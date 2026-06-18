from backend.services import reporter


def test_describe_config_exposes_model_and_tools():
    cfg = reporter.describe_config()
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["validator_model"] == "claude-haiku-4-5-20251001"
    assert cfg["max_tool_rounds"] == 6
    assert cfg["max_tokens"] == 2000
    assert len(cfg["tools"]) == 5
    assert {"get_stock_data", "get_agro_data", "search_agro_web",
            "search_web", "read_article"} == {t["name"] for t in cfg["tools"]}


def test_describe_config_exposes_prompts_no_secret():
    cfg = reporter.describe_config()
    assert "INTEGRIDADE FACTUAL" in cfg["system_market"]
    assert "system_chat" in cfg and "system_validator" in cfg
    assert "ANTHROPIC_API_KEY" not in str(cfg)
