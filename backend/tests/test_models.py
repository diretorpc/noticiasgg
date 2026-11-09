"""Nome dos modelos da Anthropic: uma fonte só, vinda do ambiente.

Quem decide quando um modelo é aposentado é a Anthropic, não este projeto. Com o nome
cravado em 12 lugares, a troca exigia caçar cada um — e o que ficasse para trás
falharia calado (o leitor de preferências já passou meses quebrado sem ninguém ver).
"""
import pathlib
import re
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from backend.services import anthropic_status, models

pytestmark = pytest.mark.unit

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_padrao_e_o_modelo_atual():
    with patch.dict("os.environ", {}, clear=False) as env:
        env.pop("ANTHROPIC_HAIKU_MODEL", None)
        env.pop("ANTHROPIC_SONNET_MODEL", None)
        assert models.haiku() == "claude-haiku-4-5-20251001"
        assert models.sonnet() == "claude-sonnet-4-6"


def test_variavel_de_ambiente_troca_o_modelo():
    with patch.dict("os.environ", {"ANTHROPIC_HAIKU_MODEL": "claude-haiku-9",
                                   "ANTHROPIC_SONNET_MODEL": "claude-sonnet-9"}):
        assert models.haiku() == "claude-haiku-9"
        assert models.sonnet() == "claude-sonnet-9"


def test_variavel_vazia_cai_no_padrao():
    """Variável criada na Vercel e deixada em branco não pode virar `model=""`."""
    with patch.dict("os.environ", {"ANTHROPIC_HAIKU_MODEL": "  "}):
        assert models.haiku() == "claude-haiku-4-5-20251001"


# Caminho EXATO, não o nome do arquivo: um `models.py` qualquer em outra pasta não pode
# virar esconderijo. Este teste fica de fora porque precisa citar o padrão atual.
_PERMITIDOS = {_BACKEND / "services" / "models.py", pathlib.Path(__file__).resolve()}


def test_nenhum_nome_de_modelo_cravado_fora_da_fonte_unica():
    """Largo de propósito (4ª rodada do Apolo nesta branch): a versão que exigia aspas e
    `claude-haiku|sonnet` logo depois deixava passar `"claude-3-5-haiku-latest"`,
    f-string, nome dentro de frase, JSON escapado e concatenação — e não olhava os
    testes, onde 4 nomes cravados quebravam a suíte com a variável preenchida no `.env`.
    Pega comentário também: aceito, porque nome de modelo em comentário apodrece igual."""
    cravados = []
    for arquivo in _BACKEND.rglob("*.py"):
        if arquivo.resolve() in _PERMITIDOS:
            continue
        for n, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"claude-[0-9a-z]", linha):
                cravados.append(f"{arquivo.relative_to(_BACKEND)}:{n}")
    assert cravados == [], f"modelo cravado fora de services/models.py: {cravados}"


# ── modelo aposentado é erro que exige ação, não "não respondeu agora" ────────

def _nao_encontrado(modelo):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    texto = f"model: {modelo}"
    resp = httpx.Response(404, request=req, json={"error": {"type": "not_found_error", "message": texto}})
    return anthropic.NotFoundError(texto, response=resp, body=None)


def test_modelo_aposentado_e_permanente_e_diz_qual_variavel_trocar():
    motivo = anthropic_status.erro_permanente(_nao_encontrado("claude-haiku-4-5-20251001"))
    assert motivo is not None
    assert "ANTHROPIC_HAIKU_MODEL" in motivo and "ANTHROPIC_SONNET_MODEL" in motivo


def test_sonda_confere_os_dois_modelos_gastando_o_minimo():
    chamadas = []
    cliente = MagicMock()
    cliente.messages.create = lambda **kw: chamadas.append(kw) or MagicMock()
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        assert anthropic_status.sondar() == {"status": "ok"}
    assert {c["model"] for c in chamadas} == {models.haiku(), models.sonnet()}
    assert all(c["max_tokens"] == 1 for c in chamadas)


def test_sonda_acusa_o_sonnet_aposentado():
    def create(**kw):
        if kw["model"] == models.sonnet():
            raise _nao_encontrado(kw["model"])
        return MagicMock()

    cliente = MagicMock()
    cliente.messages.create = create
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        r = anthropic_status.sondar()
    assert r["status"] == "error"
    assert models.sonnet() in r["message"]


def _sonda_com(falhas: dict):
    """`falhas`: {modelo: exceção}. Devolve (resultado, modelos chamados)."""
    chamados = []

    def create(**kw):
        chamados.append(kw["model"])
        if kw["model"] in falhas:
            raise falhas[kw["model"]]
        return MagicMock()

    cliente = MagicMock()
    cliente.messages.create = create
    with patch.object(anthropic_status.anthropic, "Anthropic", return_value=cliente), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste"}):
        return anthropic_status.sondar(), chamados


def test_sonda_com_os_dois_aposentados_nomeia_os_dois():
    """Parava no primeiro erro: com os dois quebrados só o Haiku aparecia, e o Sonnet
    ficava para o boletim do dia seguinte (4ª rodada do Apolo nesta branch)."""
    r, _ = _sonda_com({models.haiku(): _nao_encontrado(models.haiku()),
                       models.sonnet(): _nao_encontrado(models.sonnet())})
    assert r["status"] == "error"
    assert models.haiku() in r["message"] and models.sonnet() in r["message"]


def test_timeout_no_haiku_nao_impede_de_testar_o_sonnet():
    r, chamados = _sonda_com({models.haiku(): TimeoutError("estourou")})
    assert chamados == [models.haiku(), models.sonnet()]
    assert r["status"] == "warn"
    assert models.haiku() in r["message"]


def test_erro_permanente_tem_prioridade_sobre_passageiro():
    r, _ = _sonda_com({models.haiku(): TimeoutError("estourou"),
                       models.sonnet(): _nao_encontrado(models.sonnet())})
    assert r["status"] == "error"


def test_404_que_nao_fala_de_modelo_nao_manda_trocar_o_modelo():
    """Proxy ou `ANTHROPIC_BASE_URL` errada também dão 404 — mandar o dono trocar o
    modelo seria apontar a coisa errada."""
    req = httpx.Request("POST", "https://proxy.exemplo/v1/messages")
    resp = httpx.Response(404, request=req, text="Not Found")
    motivo = anthropic_status.erro_permanente(anthropic.NotFoundError("Not Found", response=resp, body=None))
    assert motivo is not None
    assert "ANTHROPIC_HAIKU_MODEL" not in motivo
    assert "ANTHROPIC_BASE_URL" in motivo


def test_motivo_igual_nos_dois_modelos_aparece_uma_vez():
    r, _ = _sonda_com({models.haiku(): _nao_encontrado(models.haiku()),
                       models.sonnet(): _nao_encontrado(models.sonnet())})
    assert r["message"].count("não encontrado") == 1
    assert f"(falhou: {models.haiku()}, {models.sonnet()})" in r["message"]
