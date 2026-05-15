from unittest.mock import patch, MagicMock
from backend.services import reporter


def _mock_anthropic(text="relatório de teste"):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def test_collect_all_sem_sections_retorna_todas():
    with patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, ius, ibr, n, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        result = reporter._collect_all(sections=None)
    assert set(result.keys()) == {"market", "crypto", "indicators_us", "indicators_br",
                                   "news", "commodities_br", "politics_br", "polls_br"}


def test_collect_all_com_sections_filtra_coletores():
    sections = {"market": True, "crypto": False, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        m.collect.return_value = {"ok": True}
        n.collect.return_value = {"ok": True}
        for mod in [c, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        result = reporter._collect_all(sections=sections)
    assert "market" in result
    assert "news" in result
    assert "crypto" not in result
    assert "politics_br" not in result


def test_generate_report_passa_sections():
    sections = {"market": True, "crypto": True, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.services.reporter.Anthropic") as MockA, \
         patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, n, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {}
        MockA.return_value = _mock_anthropic()
        result = reporter.generate_report("teste", sections=sections)
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_report_injeta_news_feedback_no_system():
    feedback = [
        {"important_topics": ["Fed", "juros"], "unimportant_topics": ["eleições"]},
    ]
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="relatório")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA, \
         patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, n, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        MockA.return_value.messages.create.side_effect = capture_create
        reporter.generate_report("relatório", news_feedback=feedback)
    assert "PRIORIZAR" in captured_system[0]
    assert "Fed" in captured_system[0]
    assert "eleições" in captured_system[0]
    assert "EVITAR" in captured_system[0]


def test_generate_report_sem_feedback_nao_injeta():
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="relatório")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA, \
         patch("backend.services.reporter.market") as m, \
         patch("backend.services.reporter.crypto") as c, \
         patch("backend.services.reporter.news") as n, \
         patch("backend.services.reporter.indicators_us") as ius, \
         patch("backend.services.reporter.indicators_br") as ibr, \
         patch("backend.services.reporter.commodities_br") as cb, \
         patch("backend.services.reporter.politics_br") as pb, \
         patch("backend.services.reporter.polls_br") as plb:
        for mod in [m, c, n, ius, ibr, cb, pb, plb]:
            mod.collect.return_value = {"ok": True}
        MockA.return_value.messages.create.side_effect = capture_create
        reporter.generate_report("relatório", news_feedback=None)
    assert "PRIORIZAR" not in captured_system[0]


def test_generate_report_feedback_nao_injeta_em_chat():
    """news_feedback não deve afetar _SYSTEM_CHAT (quando sections={}, sem dados de mercado)."""
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    captured_system = []

    def capture_create(**kwargs):
        captured_system.append(kwargs.get("system", ""))
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="resposta")]
        mock_msg.stop_reason = "end_turn"
        return mock_msg

    with patch("backend.services.reporter.Anthropic") as MockA:
        MockA.return_value.messages.create.side_effect = capture_create
        # sections={} → _collect_all retorna {} → _SYSTEM_CHAT
        reporter.generate_report("olá", news_feedback=feedback, sections={})
    assert "PRIORIZAR" not in captured_system[0]
