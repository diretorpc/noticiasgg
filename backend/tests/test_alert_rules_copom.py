from datetime import date

import pytest

from backend.services.alert_rules import COPOM_DATES_2026

pytestmark = pytest.mark.unit

# Calendário oficial divulgado pelo BCB (decisão sai no 2º dia, sempre quarta).
_OFICIAL_2026 = {
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-08-05", "2026-09-16", "2026-11-04", "2026-12-09",
}


@pytest.mark.unit
def test_copom_2026_tem_oito_reunioes_todas_na_quarta():
    """Copom decide sempre na quarta. Pega de graça o erro de 2026: as 8 datas
    eram quintas (calendário de 2025 rotulado como 2026)."""
    assert len(COPOM_DATES_2026) == 8
    for d in COPOM_DATES_2026:
        assert date.fromisoformat(d).weekday() == 2, f"{d} não é quarta-feira"


@pytest.mark.unit
def test_copom_2026_bate_com_calendario_oficial():
    assert COPOM_DATES_2026 == _OFICIAL_2026


@pytest.mark.unit
def test_calendario_copom_e_do_ano_corrente():
    """Catraca: em 2027 o alerta morreria calado (nenhuma data casa, zero log).
    Este teste quebra o CI em janeiro para obrigar a atualização anual."""
    for d in COPOM_DATES_2026:
        assert int(d[:4]) == date.today().year, f"{d}: calendário do Copom vencido"
