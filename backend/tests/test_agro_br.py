from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_agro_br_cbot_status_200():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    assert resp.status_code == 200


def test_agro_br_cbot_schema():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body
    assert "commodities_cbot" in body["data"]


def test_agro_br_cbot_campos():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    data = resp.json()["data"]["commodities_cbot"]
    assert len(data) > 0
    for ativo in data.values():
        assert "preco" in ativo
        assert "variacao_pct" in ativo
        assert "moeda" in ativo
        assert "unidade" in ativo
    com_preco = [v for v in data.values() if v.get("preco") is not None]
    assert len(com_preco) > 0, f"Nenhum ativo com preço válido: {data}"


def test_agro_br_commodities_br_status_200():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    assert resp.status_code == 200


def test_agro_br_commodities_br_schema():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    body = resp.json()
    assert "data" in body
    assert "commodities_br" in body["data"]


def test_agro_br_commodities_br_campos():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    data = resp.json()["data"]["commodities_br"]
    assert len(data) > 0
    for ativo in data.values():
        assert "preco" in ativo
        assert "variacao_pct" in ativo
        assert "moeda" in ativo
        assert "unidade" in ativo
    com_preco = [v for v in data.values() if v.get("preco") is not None]
    assert len(com_preco) >= len(data) // 2


def test_agro_br_gado_schema():
    resp = client.get("/api/collectors/agro-br?categoria=gado")
    assert resp.status_code == 200
    body = resp.json()
    assert "gado" in body["data"]
    assert len(body["data"]["gado"]) > 0


def test_agro_br_fertilizantes_schema():
    resp = client.get("/api/collectors/agro-br?categoria=fertilizantes")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "fertilizantes" in data
    # sem fontes ativas no Notícias Agrícolas — cobertura via search_agro_web
    assert isinstance(data["fertilizantes"], dict)


def test_agro_br_defensivos_schema():
    resp = client.get("/api/collectors/agro-br?categoria=defensivos")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "defensivos" in data
    assert isinstance(data["defensivos"], dict)


def test_agro_br_all_categorias():
    resp = client.get("/api/collectors/agro-br")
    assert resp.status_code == 200
    data = resp.json()["data"]
    for cat in ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"]:
        assert cat in data
