import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, config, soja_fretes, supabase

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.require_admin] = lambda: {"sub": "admin", "email": "matheusmouro@hotmail.com"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_soja_fretes_devolve_describe(monkeypatch):
    fake = {"fretes": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0}, "pracas": [],
            "is_custom": False, "updated_at": None, "updated_by": None,
            "idade_dias": None, "envelhecido": True}
    monkeypatch.setattr(soja_fretes, "describe", lambda: fake)
    r = client.get("/api/admin/soja-fretes")
    assert r.status_code == 200
    assert r.json() == fake


@pytest.mark.unit
def test_put_soja_fretes_valido_faz_upsert_e_limpa_cache(monkeypatch):
    captured = {}
    monkeypatch.setattr(soja_fretes, "validar", lambda f: {"pontal": 8.0, "uberaba": 11.0, "canarana": 26.0})
    monkeypatch.setattr(supabase, "upsert_config",
                        lambda k, v, updated_by=None: captured.update(key=k, val=v, updated_by=updated_by))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    monkeypatch.setattr(soja_fretes, "describe", lambda: {"ok": True})

    body = {"pontal": 8.0, "uberaba": 11.0, "canarana": 26.0}
    r = client.put("/api/admin/soja-fretes", json=body)

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["key"] == soja_fretes.CONFIG_KEY
    assert captured["val"] == {"pontal": 8.0, "uberaba": 11.0, "canarana": 26.0}
    assert captured["updated_by"] == "matheusmouro@hotmail.com"
    assert captured["cleared"] is True


@pytest.mark.unit
def test_put_soja_fretes_invalido_retorna_400(monkeypatch):
    def _explode(f):
        raise ValueError("frete de 'pontal' precisa ser um número maior que 0 e até 200")

    monkeypatch.setattr(soja_fretes, "validar", _explode)
    r = client.put("/api/admin/soja-fretes", json={"pontal": -1, "uberaba": 11.0, "canarana": 26.0})
    assert r.status_code == 400
    assert "pontal" in r.json()["detail"]


@pytest.mark.unit
def test_put_soja_fretes_bool_e_rejeitado_nunca_vira_1_0():
    """Achado 4 do Apolo: bool é subclasse de int em Python, e o Pydantic padrão
    coage bool -> float ANTES de chegar em `validar` — {"pontal": true} virava
    200 com 1.0. StrictFloat|StrictInt no body barra isso na validação."""
    r = client.put("/api/admin/soja-fretes", json={"pontal": True, "uberaba": 11.0, "canarana": 26.0})
    assert r.status_code != 200
    assert r.status_code in (400, 422)


@pytest.mark.unit
def test_delete_soja_fretes_reseta(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "delete_config", lambda k: captured.update(key=k))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    monkeypatch.setattr(soja_fretes, "describe", lambda: {"ok": True})

    r = client.delete("/api/admin/soja-fretes")

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured == {"key": soja_fretes.CONFIG_KEY, "cleared": True}
