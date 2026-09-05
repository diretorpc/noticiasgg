import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.collectors import soja_disponivel
from backend.services import auth, soja_fretes, soja_msg

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
pytestmark = pytest.mark.unit

client = TestClient(app)


# ---------------------------------------------------------------------------
# formatar_brl()
# ---------------------------------------------------------------------------


def test_formatar_brl_duas_casas():
    assert soja_msg.formatar_brl(1234.5) == "1234,50"


def test_formatar_brl_arredonda_meio_para_cima_duas_casas():
    assert soja_msg.formatar_brl(159.445) == "159,45"


def test_formatar_brl_arredonda_meio_para_cima_tres_casas():
    """`f"{12.9425:.3f}"` pode devolver "12.942" por representação binária —
    passando por `Decimal(str(v))` o arredondamento bate com o que o primo
    espera (meio para cima sobre o texto do número)."""
    assert soja_msg.formatar_brl(12.9425, casas=3) == "12,943"


def test_formatar_brl_tres_casas_caso_do_dolar():
    assert soja_msg.formatar_brl(5.1235, casas=3) == "5,124"


def test_formatar_brl_none_devolve_none():
    assert soja_msg.formatar_brl(None) is None


def test_formatar_brl_nan_devolve_none():
    assert soja_msg.formatar_brl(float("nan")) is None


def test_formatar_brl_infinito_devolve_none():
    assert soja_msg.formatar_brl(float("inf")) is None


# ---------------------------------------------------------------------------
# montar() — byte a byte
# ---------------------------------------------------------------------------


def test_montar_byte_a_byte():
    esperado = (
        "Soja Disponível\n"
        "\n"
        "Porto 🌱🛳️ = 159,44\n"
        "Pontal/SP🌱1️⃣ = 150,44\n"
        "Uberaba/MG🌱2️⃣ = 147,44\n"
        "Canarana/MT🌱3️⃣ = 132,44\n"
        "\n"
        "💵 = 5,153\n"
        "🇺🇸🌱ZSU6 Setembro26 = 12,504/bushel"
    )
    resultado = soja_msg.montar(
        159.44,
        {"pontal": 9, "uberaba": 12, "canarana": 27},
        5.153,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    assert resultado == esperado


def test_montar_nao_tem_quebra_de_linha_final():
    resultado = soja_msg.montar(
        159.44, {"pontal": 9, "uberaba": 12, "canarana": 27}, 5.153,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    assert not resultado.endswith("\n")


# ---------------------------------------------------------------------------
# montar() — indisponibilidades
# ---------------------------------------------------------------------------


def test_montar_porto_none_derruba_as_3_pracas_mas_nao_dolar_nem_cbot():
    resultado = soja_msg.montar(
        None, {"pontal": 9, "uberaba": 12, "canarana": 27}, 5.153,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    esperado = (
        "Soja Disponível\n"
        "\n"
        "Porto 🌱🛳️ = indisponível\n"
        "Pontal/SP🌱1️⃣ = indisponível\n"
        "Uberaba/MG🌱2️⃣ = indisponível\n"
        "Canarana/MT🌱3️⃣ = indisponível\n"
        "\n"
        "💵 = 5,153\n"
        "🇺🇸🌱ZSU6 Setembro26 = 12,504/bushel"
    )
    assert resultado == esperado


def test_montar_dolar_none_nao_afeta_o_resto():
    resultado = soja_msg.montar(
        159.44, {"pontal": 9, "uberaba": 12, "canarana": 27}, None,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    linhas = resultado.splitlines()
    assert linhas[2] == "Porto 🌱🛳️ = 159,44"
    assert "💵 = indisponível" in linhas
    assert linhas[-1] == "🇺🇸🌱ZSU6 Setembro26 = 12,504/bushel"


def test_montar_cbot_none_nao_afeta_o_resto():
    resultado = soja_msg.montar(
        159.44, {"pontal": 9, "uberaba": 12, "canarana": 27}, 5.153, None,
    )
    linhas = resultado.splitlines()
    assert linhas[2] == "Porto 🌱🛳️ = 159,44"
    assert linhas[-1] == "🇺🇸🌱CBOT = indisponível"
    assert "💵 = 5,153" in linhas


def test_montar_frete_faltante_so_derruba_a_propria_praca():
    resultado = soja_msg.montar(
        159.44, {"pontal": 9, "canarana": 27}, 5.153,  # falta uberaba
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    linhas = resultado.splitlines()
    assert "Pontal/SP🌱1️⃣ = 150,44" in linhas
    assert "Uberaba/MG🌱2️⃣ = indisponível" in linhas
    assert "Canarana/MT🌱3️⃣ = 132,44" in linhas


def test_montar_todos_indisponiveis_nunca_estoura():
    resultado = soja_msg.montar(None, {}, None, None)
    assert "indisponível" in resultado
    assert resultado.startswith("Soja Disponível\n")


def test_montar_porto_nan_vira_indisponivel():
    """achado 7: NaN não é `None`, mas também não é número exibível."""
    resultado = soja_msg.montar(
        float("nan"), {"pontal": 9, "uberaba": 12, "canarana": 27}, 5.153,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    linhas = resultado.splitlines()
    assert linhas[2] == "Porto 🌱🛳️ = indisponível"


# ---------------------------------------------------------------------------
# _praca() e montar() — praça negativa (achado 2, 2ª revisão)
# ---------------------------------------------------------------------------


def test_praca_positiva_retorna_o_valor():
    assert soja_msg._praca(159.0, 9.0) == 150.0


def test_praca_zero_vira_none():
    assert soja_msg._praca(159.0, 159.0) is None


def test_praca_negativa_vira_none():
    """achado 2: frete (200, dentro do teto de `soja_fretes.validar`) maior
    que o Porto (159) produz -41 — não é uma praça real."""
    assert soja_msg._praca(159.0, 200.0) is None


def test_montar_praca_negativa_vira_indisponivel_mas_nao_derruba_as_outras():
    resultado = soja_msg.montar(
        159.0, {"pontal": 9, "uberaba": 12, "canarana": 200}, 5.153,
        {"rotulo": "ZSU6 Setembro26", "preco_usd_bushel": 12.504},
    )
    linhas = resultado.splitlines()
    assert "Pontal/SP🌱1️⃣ = 150,00" in linhas
    assert "Uberaba/MG🌱2️⃣ = 147,00" in linhas
    assert "Canarana/MT🌱3️⃣ = indisponível" in linhas


# ---------------------------------------------------------------------------
# gerar()
# ---------------------------------------------------------------------------


def _dados_ok():
    return {
        "porto": {"preco": 159.44, "data_ref": "03/09/2026"},
        "cbot": {
            "simbolo": "ZSU26.CBT",
            "rotulo": "ZSU6 Setembro26",
            "preco_usd_bushel": 12.504,
        },
        "dolar": {"preco": 5.153},
    }


def _blocos_indisponiveis_no_texto(texto: str) -> set[str]:
    """Deriva do TEXTO final quais blocos aparecem como "indisponível" — usada
    pra provar que `indisponiveis` nunca diverge do que o usuário realmente vê
    (achado 1, 2ª revisão do Apolo). Lê linha EXATA ("rótulo = indisponível"),
    não substring, pra não confundir com o CBOT disponível (que também começa
    com o emoji 🇺🇸🌱, só que seguido do rótulo do contrato, não de "CBOT")."""
    linhas = texto.splitlines()

    def _indisponivel(rotulo: str) -> bool:
        return f"{rotulo} = {soja_msg._INDISPONIVEL}" in linhas

    blocos: set[str] = set()
    if _indisponivel(soja_msg._ROTULO_PORTO):
        blocos.add("Porto")
    if any(_indisponivel(rotulo) for _chave, rotulo, _default in soja_fretes.PRACAS):
        blocos.add("Praças (fretes)")
    if _indisponivel(soja_msg._ROTULO_DOLAR):
        blocos.add("Dólar")
    if _indisponivel(soja_msg._ROTULO_CBOT_INDISPONIVEL):
        blocos.add("CBOT")
    return blocos


def _fretes_ok():
    return {
        "fretes": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
        "pracas": [], "is_custom": True, "updated_at": "2026-09-04T00:00:00+00:00",
        "updated_by": "matheusmouro@hotmail.com", "idade_dias": 0, "envelhecido": False,
        "defaults": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
    }


def test_gerar_caminho_feliz(monkeypatch):
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "Porto 🌱🛳️ = 159,44" in out["texto"]
    assert "🇺🇸🌱ZSU6 Setembro26 = 12,504/bushel" in out["texto"]
    assert out["porto_data_ref"] == "03/09/2026"
    assert out["cbot_simbolo"] == "ZSU26.CBT"
    assert out["avisos"] == []
    assert out["indisponiveis"] == []


def test_gerar_porto_com_erro_vira_indisponivel_e_entra_na_lista(monkeypatch):
    dados = _dados_ok()
    dados["porto"] = {"erro": "500 protected domain"}
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "Porto 🌱🛳️ = indisponível" in out["texto"]
    assert "Pontal/SP🌱1️⃣ = indisponível" in out["texto"]
    # Porto indisponível cascateia pras 3 praças no TEXTO (achado 1, 2ª
    # revisão) — "Praças (fretes)" entra junto, por construção, pra não
    # deixar 4 linhas "indisponível" com 1 só entrada explicando o porquê.
    assert out["indisponiveis"] == ["Porto", "Praças (fretes)"]
    assert out["porto_data_ref"] is None


def test_gerar_dolar_com_erro_vira_indisponivel_sozinho(monkeypatch):
    dados = _dados_ok()
    dados["dolar"] = {"erro": "sem preço"}
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "💵 = indisponível" in out["texto"]
    assert "Porto 🌱🛳️ = 159,44" in out["texto"]
    assert out["indisponiveis"] == ["Dólar"]


def test_gerar_cbot_com_erro_vira_indisponivel_sozinho(monkeypatch):
    dados = _dados_ok()
    dados["cbot"] = {"erro": "404 em todos os candidatos"}
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "🇺🇸🌱CBOT = indisponível" in out["texto"]
    assert out["indisponiveis"] == ["CBOT"]
    assert out["cbot_simbolo"] is None


def test_gerar_fretes_envelhecidos_gera_aviso(monkeypatch):
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    fretes = _fretes_ok()
    fretes["envelhecido"] = True
    fretes["is_custom"] = True
    fretes["idade_dias"] = 61
    monkeypatch.setattr(soja_fretes, "describe", lambda: fretes)

    out = soja_msg.gerar()

    assert any("61 dias" in a for a in out["avisos"])


def test_gerar_fretes_nunca_salvos_gera_aviso_com_defaults(monkeypatch):
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    fretes = {
        "fretes": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
        "pracas": [], "is_custom": False, "updated_at": None, "updated_by": None,
        "idade_dias": None, "envelhecido": True,
        "defaults": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
    }
    monkeypatch.setattr(soja_fretes, "describe", lambda: fretes)

    out = soja_msg.gerar()

    assert any("nunca foram salvos" in a for a in out["avisos"])


def test_gerar_fretes_com_aviso_de_valor_invalido_propaga(monkeypatch):
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    fretes = _fretes_ok()
    fretes["aviso"] = "valor salvo incompleto ou inválido — usando padrão"
    monkeypatch.setattr(soja_fretes, "describe", lambda: fretes)

    out = soja_msg.gerar()

    assert any("incompleto" in a for a in out["avisos"])


def test_gerar_nunca_levanta_mesmo_com_collect_estourando(monkeypatch):
    def _explode():
        raise RuntimeError("timeout apiKey=SEGREDO123")

    monkeypatch.setattr(soja_disponivel, "collect", _explode)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()  # não pode levantar

    assert out["indisponiveis"] == ["Porto", "Praças (fretes)", "Dólar", "CBOT"]
    assert "indisponível" in out["texto"]
    assert any("coleta" in a for a in out["avisos"])
    assert not any("SEGREDO123" in a for a in out["avisos"])


def test_gerar_nunca_levanta_mesmo_com_describe_estourando(monkeypatch):
    def _explode():
        raise RuntimeError("500 apiKey=SEGREDO123")

    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    monkeypatch.setattr(soja_fretes, "describe", _explode)

    out = soja_msg.gerar()  # não pode levantar

    assert "indisponível" in out["texto"]  # praças caem sem frete
    assert any("fretes" in a for a in out["avisos"])
    assert not any("SEGREDO123" in a for a in out["avisos"])


# ---------------------------------------------------------------------------
# gerar() — Supabase fora / fretes corrompidos não podem forjar praça (achado 1)
# ---------------------------------------------------------------------------


def test_gerar_fretes_com_erro_derruba_pracas_mas_nao_porto(monkeypatch):
    """`describe()` fora do ar devolve `erro` + fretes DEFAULT (9/12/27) — o
    contrato dela é nunca deixar `fretes` vazio. `gerar()` não pode usar esse
    default calado: sem saber se é 9/12/27 de verdade, a praça precisa cair,
    não o Porto (que veio de outra fonte, sem erro)."""
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    monkeypatch.setattr(soja_fretes, "describe", lambda: {
        "fretes": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
        "pracas": [], "is_custom": False, "updated_at": None, "updated_by": None,
        "idade_dias": None, "envelhecido": True,
        "defaults": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
        "erro": "sem conexão com o Supabase",
    })

    out = soja_msg.gerar()

    assert "Porto 🌱🛳️ = 159,44" in out["texto"]
    assert "Pontal/SP🌱1️⃣ = indisponível" in out["texto"]
    assert "Uberaba/MG🌱2️⃣ = indisponível" in out["texto"]
    assert "Canarana/MT🌱3️⃣ = indisponível" in out["texto"]
    assert "Praças (fretes)" in out["indisponiveis"]


def test_gerar_fretes_com_aviso_de_valor_corrompido_tambem_derruba_pracas(monkeypatch):
    """Mesmo achado, outra porta de entrada: valor salvo parcial/corrompido
    (`aviso`, não `erro`) — mistura real+default é tão calada quanto o erro."""
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    fretes = _fretes_ok()
    fretes["aviso"] = "valor salvo incompleto ou inválido — usando padrão"
    monkeypatch.setattr(soja_fretes, "describe", lambda: fretes)

    out = soja_msg.gerar()

    assert "Pontal/SP🌱1️⃣ = indisponível" in out["texto"]
    assert "Uberaba/MG🌱2️⃣ = indisponível" in out["texto"]
    assert "Canarana/MT🌱3️⃣ = indisponível" in out["texto"]
    assert "Praças (fretes)" in out["indisponiveis"]


# ---------------------------------------------------------------------------
# gerar() — bloco sem `erro` E sem preço não pode estourar (achado 2)
# ---------------------------------------------------------------------------


def test_gerar_cbot_sem_preco_usd_bushel_vira_indisponivel_sem_estourar(monkeypatch):
    dados = _dados_ok()
    dados["cbot"] = {"simbolo": "ZSU26.CBT", "rotulo": "ZSU6 Setembro26"}  # sem preco_usd_bushel
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()  # não pode levantar (Decimal(str(None)))

    assert "🇺🇸🌱CBOT = indisponível" in out["texto"]
    assert out["indisponiveis"] == ["CBOT"]


def test_gerar_cbot_sem_rotulo_vira_indisponivel_sem_estourar(monkeypatch):
    dados = _dados_ok()
    dados["cbot"] = {"simbolo": "ZSU26.CBT", "preco_usd_bushel": 12.504}  # sem rotulo
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "🇺🇸🌱CBOT = indisponível" in out["texto"]
    assert out["indisponiveis"] == ["CBOT"]


def test_gerar_porto_com_data_ref_mas_sem_preco_vira_indisponivel(monkeypatch):
    """achado 6: texto e resumo (`indisponiveis`/`porto_data_ref`) têm que
    concordar — não dá pra ter data de referência sem preço."""
    dados = _dados_ok()
    dados["porto"] = {"data_ref": "03/09/2026"}  # sem preco
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "Porto" in out["indisponiveis"]
    assert out["porto_data_ref"] is None


def test_gerar_dolar_sem_preco_vira_indisponivel_sem_estourar(monkeypatch):
    dados = _dados_ok()
    dados["dolar"] = {"simbolo": "BRL=X"}  # sem preco
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert "💵 = indisponível" in out["texto"]
    assert out["indisponiveis"] == ["Dólar"]


def test_gerar_montar_estourando_devolve_texto_degradado_e_aviso_sanitizado(monkeypatch):
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    def _explode(*_a, **_k):
        raise RuntimeError("boom apiKey=SEGREDO123")

    monkeypatch.setattr(soja_msg, "montar", _explode)

    out = soja_msg.gerar()  # não pode levantar

    assert out["texto"].count("indisponível") >= 5  # todas as linhas caem
    assert any("render" in a for a in out["avisos"])
    assert not any("SEGREDO123" in a for a in out["avisos"])
    # achado 1-a (2ª revisão): o render falhou DEPOIS de porto/dólar/cbot
    # terem vindo bons (`_dados_ok`) — sem o conserto, os metadados ficariam
    # presos com os valores antigos por cima de um texto todo "indisponível"
    # (o rodapé do painel mostraria "CEPEA de 03/09..." sob uma mensagem
    # vazia). Texto e `indisponiveis`/metadados têm que bater exatamente.
    assert set(out["indisponiveis"]) == _blocos_indisponiveis_no_texto(out["texto"])
    assert set(out["indisponiveis"]) == {"Porto", "Praças (fretes)", "Dólar", "CBOT"}
    assert out["porto_data_ref"] is None
    assert out["cbot_simbolo"] is None
    assert out["cbot_atualizado_em"] is None
    assert out["dolar_atualizado_em"] is None


def test_gerar_porto_nan_entra_em_indisponiveis_e_derruba_pracas(monkeypatch):
    """achado 1-b (2ª revisão): NaN não é `None` — o guarda antigo
    (`.get("preco") is None`) deixava passar calado, com o texto mostrando
    Porto e as 3 praças "indisponível" mas `indisponiveis`/`avisos` vazios."""
    dados = _dados_ok()
    dados["porto"]["preco"] = float("nan")
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert set(out["indisponiveis"]) == _blocos_indisponiveis_no_texto(out["texto"])
    assert set(out["indisponiveis"]) == {"Porto", "Praças (fretes)"}
    assert out["porto_data_ref"] is None


def test_gerar_describe_sem_chave_fretes_deixa_pracas_indisponiveis_e_avisa(monkeypatch):
    """achado 1-c (2ª revisão): `describe()` malformado (sem "erro"/"aviso" E
    sem a chave "fretes") derrubava as 3 praças no texto sem nenhuma entrada
    em `indisponiveis` explicando — Porto/dólar/CBOT continuam bons."""
    monkeypatch.setattr(soja_disponivel, "collect", _dados_ok)
    monkeypatch.setattr(soja_fretes, "describe", lambda: {
        "pracas": [], "is_custom": True, "updated_at": "2026-09-04T00:00:00+00:00",
        "updated_by": "matheusmouro@hotmail.com", "idade_dias": 0, "envelhecido": False,
        "defaults": {"pontal": 9.0, "uberaba": 12.0, "canarana": 27.0},
        # sem a chave "fretes" de propósito
    })

    out = soja_msg.gerar()

    assert "Porto 🌱🛳️ = 159,44" in out["texto"]
    assert set(out["indisponiveis"]) == _blocos_indisponiveis_no_texto(out["texto"])
    assert out["indisponiveis"] == ["Praças (fretes)"]


def test_gerar_praca_negativa_entra_em_indisponiveis_e_avisa(monkeypatch):
    """achado 2 (2ª revisão): frete válido (<=200) porém maior que o Porto
    do dia vira -40,56 em vez de indisponível — sem alertar o Matheus."""
    dados = _dados_ok()
    dados["porto"]["preco"] = 159.0
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    fretes = _fretes_ok()
    fretes["fretes"] = {"pontal": 9.0, "uberaba": 12.0, "canarana": 200.0}
    monkeypatch.setattr(soja_fretes, "describe", lambda: fretes)

    out = soja_msg.gerar()

    assert "Praças (fretes)" in out["indisponiveis"]
    assert any("frete maior que o Porto" in a for a in out["avisos"])
    assert "Canarana/MT🌱3️⃣ = indisponível" in out["texto"]
    assert "Pontal/SP🌱1️⃣ = 150,00" in out["texto"]  # as outras praças seguem reais


# ---------------------------------------------------------------------------
# gerar() — defasagem (achado 3): epochs de atualização do CBOT e do dólar
# ---------------------------------------------------------------------------


def test_gerar_retorna_epochs_de_atualizacao(monkeypatch):
    dados = _dados_ok()
    dados["cbot"]["atualizado_em"] = 1725400000
    dados["dolar"]["atualizado_em"] = 1725400500
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert out["cbot_atualizado_em"] == 1725400000
    assert out["dolar_atualizado_em"] == 1725400500


def test_gerar_epochs_none_quando_bloco_indisponivel(monkeypatch):
    dados = _dados_ok()
    dados["cbot"] = {"erro": "falhou"}
    dados["dolar"] = {"erro": "falhou"}
    monkeypatch.setattr(soja_disponivel, "collect", lambda: dados)
    monkeypatch.setattr(soja_fretes, "describe", _fretes_ok)

    out = soja_msg.gerar()

    assert out["cbot_atualizado_em"] is None
    assert out["dolar_atualizado_em"] is None


# ---------------------------------------------------------------------------
# _avisos_fretes() — erro não pode conviver com "nunca foram salvos" (achado 5)
# ---------------------------------------------------------------------------


def test_avisos_fretes_com_erro_nao_soma_aviso_de_nunca_salvo():
    """`describe()` em erro devolve `envelhecido=True`/`is_custom=False`
    (formato do fallback) — sem o corte cedo isso soava como 'nunca foram
    salvos', contradizendo o próprio aviso de erro."""
    desc = {"erro": "sem conexão com o Supabase", "envelhecido": True, "is_custom": False}

    avisos = soja_msg._avisos_fretes(desc)

    assert avisos == ["fretes: sem conexão com o Supabase"]


# ---------------------------------------------------------------------------
# rota /api/admin/soja-preview
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.require_admin] = lambda: {"sub": "admin", "email": "matheusmouro@hotmail.com"}
    yield
    app.dependency_overrides.clear()


def test_rota_soja_preview_devolve_gerar(monkeypatch):
    fake = {"texto": "Soja Disponível\n...", "porto_data_ref": "03/09/2026",
            "cbot_simbolo": "ZSU26.CBT", "avisos": [], "indisponiveis": []}
    monkeypatch.setattr(soja_msg, "gerar", lambda: fake)

    r = client.get("/api/admin/soja-preview")

    assert r.status_code == 200
    assert r.json() == fake


@pytest.mark.unit
def test_gerar_fretes_parcial_entra_em_indisponiveis(monkeypatch):
    """describe() devolvendo dict sem uma praça: o texto derruba a praça e a
    lista tem que dizer isso (3ª revisão do Apolo — completude, não só vazio)."""
    monkeypatch.setattr(soja_msg.soja_disponivel, "collect", lambda: {
        "porto": {"preco": 159.44, "data_ref": "03/09/2026"},
        "dolar": {"preco": 5.153, "atualizado_em": 1},
        "cbot": {"simbolo": "ZSU26.CBT", "rotulo": "ZSU6 Setembro26",
                 "preco_usd_bushel": 12.504, "atualizado_em": 1},
    })
    monkeypatch.setattr(soja_msg.soja_fretes, "describe",
                        lambda: {"fretes": {"pontal": 9.0, "uberaba": 12.0}, "is_custom": True})
    out = soja_msg.gerar()
    assert "Canarana/MT🌱3️⃣ = indisponível" in out["texto"]
    assert "Praças (fretes)" in out["indisponiveis"]
