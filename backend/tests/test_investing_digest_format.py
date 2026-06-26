from backend.services import investing_digest


def _event(**over):
    base = {"event_id": "1", "country": "Spain", "flag_emoji": "🇪🇸",
            "name": "PIB da Espanha (trimestral) (Q1)", "importance": 3,
            "previous": "0,8%", "forecast": "0,6%", "actual": "0,6%"}
    base.update(over)
    return base


def test_format_event_matches_expected_layout():
    out = investing_digest._format_event(_event())
    assert out == (
        "🇪🇸 PIB da Espanha (trimestral) (Q1)\n"
        "Anterior = 0,8%\n"
        "Projeção = 0,6%\n"
        "Atual = 0,6%"
    )


def test_format_event_omits_blank_forecast():
    out = investing_digest._format_event(_event(forecast=""))
    assert "Projeção" not in out
    assert out.endswith("Atual = 0,6%")


def test_build_message_groups_with_separators():
    msg = investing_digest._build_message([_event(), _event(name="Outro", flag_emoji="🇺🇸")])
    assert msg.startswith("📅 *Calendário Econômico — novos dados*")
    assert msg.count("━━━━━━━━━━━━━━") == 2  # divisória antes de cada bloco
    assert "🇪🇸 PIB da Espanha" in msg
    assert "🇺🇸 Outro" in msg


def test_build_message_test_mode_marks_header():
    msg = investing_digest._build_message([_event()], test_mode=True)
    assert "[TESTE]" in msg.splitlines()[0]
