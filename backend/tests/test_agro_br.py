from backend.tests.conftest import coleta_unica

# Uma chamada real por categoria por rodada, reaproveitada entre os testes.
# Antes: cbot e commodities_br eram buscados 3x cada.
resposta_cbot = coleta_unica("/api/collectors/agro-br?categoria=commodities_cbot")
resposta_commodities_br = coleta_unica("/api/collectors/agro-br?categoria=commodities_br")
resposta_gado = coleta_unica("/api/collectors/agro-br?categoria=gado")
resposta_fertilizantes = coleta_unica("/api/collectors/agro-br?categoria=fertilizantes")
resposta_defensivos = coleta_unica("/api/collectors/agro-br?categoria=defensivos")
resposta_agro_tudo = coleta_unica("/api/collectors/agro-br")


def _conferir_ativos(data: dict) -> list:
    assert len(data) > 0
    for ativo in data.values():
        assert "preco" in ativo
        assert "variacao_pct" in ativo
        assert "moeda" in ativo
        assert "unidade" in ativo
    return [v for v in data.values() if v.get("preco") is not None]


def test_agro_br_cbot_status_200(resposta_cbot):
    assert resposta_cbot.status_code == 200


def test_agro_br_cbot_schema(resposta_cbot):
    body = resposta_cbot.json()
    assert "data" in body
    assert "collected_at" in body
    assert "commodities_cbot" in body["data"]


def test_agro_br_cbot_campos(resposta_cbot):
    data = resposta_cbot.json()["data"]["commodities_cbot"]
    com_preco = _conferir_ativos(data)
    assert len(com_preco) > 0, f"Nenhum ativo com preço válido: {data}"


def test_agro_br_commodities_br_status_200(resposta_commodities_br):
    assert resposta_commodities_br.status_code == 200


def test_agro_br_commodities_br_schema(resposta_commodities_br):
    body = resposta_commodities_br.json()
    assert "data" in body
    assert "commodities_br" in body["data"]


def test_agro_br_commodities_br_campos(resposta_commodities_br):
    data = resposta_commodities_br.json()["data"]["commodities_br"]
    com_preco = _conferir_ativos(data)
    assert len(com_preco) >= len(data) // 2


def test_agro_br_gado_schema(resposta_gado):
    assert resposta_gado.status_code == 200
    body = resposta_gado.json()
    assert "gado" in body["data"]
    assert len(body["data"]["gado"]) > 0


def test_agro_br_fertilizantes_schema(resposta_fertilizantes):
    assert resposta_fertilizantes.status_code == 200
    data = resposta_fertilizantes.json()["data"]
    assert "fertilizantes" in data
    # sem fontes ativas no Notícias Agrícolas — cobertura via search_agro_web
    assert isinstance(data["fertilizantes"], dict)


def test_agro_br_defensivos_schema(resposta_defensivos):
    assert resposta_defensivos.status_code == 200
    data = resposta_defensivos.json()["data"]
    assert "defensivos" in data
    assert isinstance(data["defensivos"], dict)


def test_agro_br_all_categorias(resposta_agro_tudo):
    assert resposta_agro_tudo.status_code == 200
    data = resposta_agro_tudo.json()["data"]
    for cat in ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"]:
        assert cat in data
