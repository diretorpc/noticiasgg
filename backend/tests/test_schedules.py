import pytest
from backend.services import schedules


@pytest.mark.unit
def test_grid_to_rows_expands_each_hour():
    grid = {"commodities": {"0": [7, 12], "4": [7]}}
    rows = schedules.grid_to_rows("5534999945010", grid)
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 0, "hour": 7} in rows
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 0, "hour": 12} in rows
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 4, "hour": 7} in rows
    assert len(rows) == 3


@pytest.mark.unit
def test_grid_to_rows_empty():
    assert schedules.grid_to_rows("x", {}) == []
    assert schedules.grid_to_rows("x", {"bolsas": {"0": []}}) == []


@pytest.mark.unit
def test_rows_to_grid_groups_and_sorts():
    rows = [
        {"section": "bolsas", "weekday": 0, "hour": 12},
        {"section": "bolsas", "weekday": 0, "hour": 7},
        {"section": "analise", "weekday": 6, "hour": 18},
    ]
    grid = schedules.rows_to_grid(rows)
    assert grid == {"bolsas": {"0": [7, 12]}, "analise": {"6": [18]}}


@pytest.mark.unit
def test_roundtrip_grid_rows_grid():
    grid = {"politica": {"0": [12], "2": [7, 19]}}
    rows = schedules.grid_to_rows("p", grid)
    back = schedules.rows_to_grid([{k: r[k] for k in ("section", "weekday", "hour")} for r in rows])
    assert back == grid
