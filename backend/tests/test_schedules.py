import pytest
from backend.services import schedules

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


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


@pytest.mark.unit
def test_grid_to_rows_deduplica_horas_repetidas():
    """Hora repetida virava duas linhas com a mesma chave primária: o DELETE
    rodava, o INSERT dava 409 e a grade do usuário sumia."""
    rows = schedules.grid_to_rows("p", {"bolsas": {"0": [7, 7, 12]}})
    assert len(rows) == 2
    assert sorted(r["hour"] for r in rows) == [7, 12]


@pytest.mark.unit
def test_grid_to_rows_rejeita_dia_fora_da_faixa():
    with pytest.raises(ValueError):
        schedules.grid_to_rows("p", {"bolsas": {"7": [7]}})


@pytest.mark.unit
def test_grid_to_rows_rejeita_hora_fora_da_faixa():
    with pytest.raises(ValueError):
        schedules.grid_to_rows("p", {"bolsas": {"0": [24]}})


@pytest.mark.unit
def test_grid_to_rows_mesma_hora_em_secoes_diferentes_gera_duas_linhas():
    rows = schedules.grid_to_rows("p", {"bolsas": {"0": [7]}, "analise": {"0": [7]}})
    assert len(rows) == 2


@pytest.mark.unit
def test_grid_to_rows_rejeita_secao_desconhecida():
    """Seção que o motor não conhece vira agendamento fantasma: aparece no
    painel como agendado e nunca dispara."""
    with pytest.raises(ValueError):
        schedules.grid_to_rows("p", {"secao_inventada": {"0": [7]}})
