import datetime
import math

import pytest

from backend.services import soja_fretes, supabase

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def _iso_ha(dias: float) -> str:
    import datetime
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# validar()
# ---------------------------------------------------------------------------

_VALIDOS = {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}


def test_validar_aceita_valores_validos():
    assert soja_fretes.validar(_VALIDOS) == _VALIDOS


def test_validar_rejeita_chave_faltante():
    incompleto = {"pontal": 9.0, "uberaba": 12.0}
    with pytest.raises(ValueError):
        soja_fretes.validar(incompleto)


def test_validar_rejeita_negativo():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "pontal": -1.0})


def test_validar_rejeita_zero():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "pontal": 0})


def test_validar_rejeita_acima_do_teto():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "canarana": 200.01})


def test_validar_aceita_o_teto_exato():
    assert soja_fretes.validar({**_VALIDOS, "canarana": 200.0})["canarana"] == 200.0


def test_validar_rejeita_string():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "uberaba": "12"})


def test_validar_rejeita_nan():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "uberaba": math.nan})


def test_validar_rejeita_infinito():
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "uberaba": math.inf})


def test_validar_rejeita_bool():
    """bool é subclasse de int em Python — True/False não podem colar como frete."""
    with pytest.raises(ValueError):
        soja_fretes.validar({**_VALIDOS, "uberaba": True})


def test_validar_mensagem_nao_carrega_dado_sensivel():
    """Achado 8 do Apolo: sem pytest.raises, este teste passava verde mesmo se
    `validar` parasse de levantar (o try/except sem `pytest.fail()` engolia o caso)."""
    with pytest.raises(ValueError) as exc:
        soja_fretes.validar({"pontal": 9.0})
    assert "SUPABASE" not in str(exc.value).upper()
    assert "KEY" not in str(exc.value).upper()


# ---------------------------------------------------------------------------
# _idade_dias()
# ---------------------------------------------------------------------------


def test_idade_dias_relogio_no_futuro_nao_fica_negativa():
    """Achado 7: relógio torto (skew) 2h no futuro não pode virar idade -1,
    que passaria como "recém-editado" mesmo estando quebrado."""
    futuro = (datetime.datetime.now(datetime.timezone.utc)
              + datetime.timedelta(hours=2)).isoformat()
    assert soja_fretes._idade_dias(futuro) == 0


# ---------------------------------------------------------------------------
# descrever_defaults()
# ---------------------------------------------------------------------------


def test_descrever_defaults_formata_9_12_27():
    """Fonte única do '9/12/27' — usada em health.py e no confirm do painel
    (achado 3: o mesmo texto vivia hardcoded em três lugares)."""
    assert soja_fretes.descrever_defaults() == "9/12/27"


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------

def test_describe_defaults_quando_nao_ha_linha(monkeypatch):
    monkeypatch.setattr(supabase, "get_config_row", lambda key: None)
    out = soja_fretes.describe()
    assert out["fretes"] == {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}
    assert out["is_custom"] is False
    assert out["updated_at"] is None
    assert out["updated_by"] is None
    assert out["idade_dias"] is None
    assert out["envelhecido"] is True
    assert "erro" not in out


def test_describe_traz_defaults_mesmo_com_valor_custom(monkeypatch):
    """Achado 3: `initial.pracas` no painel traz o valor EFETIVO, não o default —
    o confirm do reset precisa do default explícito, que não muda com a edição."""
    row = {"key": "soja_fretes", "value": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
           "updated_at": _iso_ha(10), "updated_by": "x"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["defaults"] == {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}


def test_describe_traz_pracas_na_ordem_com_rotulo_exato(monkeypatch):
    monkeypatch.setattr(supabase, "get_config_row", lambda key: None)
    out = soja_fretes.describe()
    assert [p["chave"] for p in out["pracas"]] == ["pontal", "uberaba", "canarana"]
    assert out["pracas"][0]["rotulo"] == "Pontal/SP🌱1️⃣"
    assert out["pracas"][1]["rotulo"] == "Uberaba/MG🌱2️⃣"
    assert out["pracas"][2]["rotulo"] == "Canarana/MT🌱3️⃣"


def test_describe_custom_10_dias_nao_envelhecido(monkeypatch):
    row = {"key": "soja_fretes", "value": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
           "updated_at": _iso_ha(10), "updated_by": "matheusmouro@hotmail.com"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["fretes"] == {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0}
    assert out["is_custom"] is True
    assert out["idade_dias"] == 10
    assert out["envelhecido"] is False
    assert out["updated_by"] == "matheusmouro@hotmail.com"


def test_describe_custom_61_dias_envelhecido(monkeypatch):
    row = {"key": "soja_fretes", "value": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
           "updated_at": _iso_ha(61), "updated_by": "matheusmouro@hotmail.com"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["idade_dias"] == 61
    assert out["envelhecido"] is True


def test_describe_custom_60_dias_exato_nao_envelhecido(monkeypatch):
    row = {"key": "soja_fretes", "value": {"pontal": 8.5, "uberaba": 11.0, "canarana": 26.0},
           "updated_at": _iso_ha(60), "updated_by": "x"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["idade_dias"] == 60
    assert out["envelhecido"] is False


def test_describe_valor_parcial_completa_com_default_e_marca_aviso(monkeypatch):
    row = {"key": "soja_fretes", "value": {"pontal": 8.5, "canarana": 26.0},  # falta uberaba
           "updated_at": _iso_ha(5), "updated_by": "x"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["fretes"]["pontal"] == 8.5
    assert out["fretes"]["uberaba"] == 12.0  # default
    assert out["fretes"]["canarana"] == 26.0
    assert "aviso" in out


def test_describe_valor_com_chave_invalida_completa_com_default_e_marca_aviso(monkeypatch):
    row = {"key": "soja_fretes",
           "value": {"pontal": 8.5, "uberaba": "não é número", "canarana": 26.0},
           "updated_at": _iso_ha(5), "updated_by": "x"}
    monkeypatch.setattr(supabase, "get_config_row", lambda key: row)
    out = soja_fretes.describe()
    assert out["fretes"]["uberaba"] == 12.0  # default
    assert "aviso" in out


def test_describe_supabase_estourando_devolve_defaults_com_erro_sanitizado(monkeypatch):
    def _explode(key):
        raise RuntimeError("500 https://x.supabase.co/rest/v1/agent_config?apiKey=SEGREDO123")

    monkeypatch.setattr(supabase, "get_config_row", _explode)
    out = soja_fretes.describe()
    assert out["fretes"] == {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}
    assert out["is_custom"] is False
    assert out["envelhecido"] is True
    assert out["defaults"] == {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}
    assert "erro" in out
    assert "SEGREDO123" not in out["erro"]


def test_describe_nunca_levanta_mesmo_com_excecao_inesperada(monkeypatch):
    monkeypatch.setattr(supabase, "get_config_row",
                        lambda key: (_ for _ in ()).throw(KeyError("SUPABASE_URL")))
    out = soja_fretes.describe()  # não pode levantar
    assert out["erro"]
