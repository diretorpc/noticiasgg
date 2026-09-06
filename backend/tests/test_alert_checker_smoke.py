"""Smoke do classificador de notícias — chamadas REAIS ao Haiku, NÃO rodam no
CI (ver `pytest.ini`: o marcador `smoke` fica fora do portão).

Sem `pytestmark = pytest.mark.unit` de propósito: este arquivo mora fora do
que `test_alert_checker.py` cobre porque um teste `unit` E `smoke` ao mesmo
tempo herdaria a trava de rede (`backend/tests/_trava_rede.py` bloqueia
conexão externa para todo nodeid marcado `unit`) e entraria no filtro
`-m unit` do CI gate — os dois seriam regressão grave para um teste que
existe justamente para bater na API de verdade.

Custa uma chamada real por notícia classificada (~R$ 0,01 cada, Haiku) — rode
só quando for medir a camada 2 do prompt (`_NEWS_CLASSIFIER_SYSTEM`), não em
todo `pytest` local.
"""
import calendar
import json
import os
from datetime import datetime as _real_datetime

import pytest
from anthropic import Anthropic

from backend.services import alert_checker
from backend.tests._constantes import CHAVE_ANTHROPIC_PLACEHOLDER

# Placeholder que `backend/tests/conftest.py` injeta (fixture autouse
# `_chave_anthropic_de_teste`) quando `ANTHROPIC_API_KEY` não existe no
# ambiente — sem chave real, as chamadas abaixo estourariam autenticação em
# vez de pular com uma mensagem clara (item 7, 3ª revisão do Apolo,
# 05/09/2026: antes disto o smoke não pulava nunca, só quebrava feio).
#
# A constante mora em `backend/tests/_constantes.py`, não aqui nem em
# `conftest.py` (item 6, 4ª revisão do Apolo, 05/09/2026): duas cópias
# hardcoded da mesma string podiam divergir numa troca futura, calado — ver
# o comentário do módulo compartilhado.


def _mes_ingles(numero: int) -> str:
    return calendar.month_name[numero]


def _classificar(article: dict, publicado_em_hoje: str) -> int:
    entrada = alert_checker._build_classifier_input(
        {**article, "publicado_em": publicado_em_hoje}, "", [])
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=alert_checker._NEWS_CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": entrada}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)["score"]


@pytest.mark.smoke
def test_classificador_real_rebaixa_incidente_wasde_reindexado(monkeypatch):
    """Incidente real de 05/09/2026: o Google reindexou em setembro uma
    matéria do WASDE de maio, e o classificador (camada 1 falhando aberta,
    sem data real extraída) deu nota 7 usando só o <publicado_em> do
    agregador. Este smoke prova (ou não) que a regra escrita na camada 2 do
    prompt (ver o bullet "1-2" em `_NEWS_CLASSIFIER_SYSTEM`) sozinha já
    rebaixa o caso, sem depender da camada 1 (leitura da data real da
    página).

    Item 4 (3ª revisão do Apolo, 05/09/2026) — bomba de calendário: a versão
    anterior hardcodava "May WASDE" partindo do pressuposto de que o dia real
    de execução sempre seria depois de maio — falso de janeiro a abril. Os
    meses agora saem de `datetime.now()`: incidente = mês corrente − 4
    (garantido no passado, qualquer que seja o mês em que este smoke rode),
    controle = mês corrente. `<hoje>` é FIXADO explicitamente (via
    monkeypatch de `alert_checker.datetime`, mesmo padrão de
    `test_report_engine.py::test_generate_sections_orders_and_prefixes_greeting`)
    para o teste não depender de duas chamadas a `datetime.now()` (uma aqui,
    outra dentro de `_build_classifier_input`) caindo em lados diferentes de
    uma virada de dia/mês.

    Item 3 (3ª revisão do Apolo, 05/09/2026) — a regra do prompt foi
    ESTREITADA para não penalizar "safra nomeada" (assunto diário, não
    sintoma de reindexação): dois controles novos provam isso. `_CONTROLE_EXPORTACAO`
    cita uma safra (25/26) dentro de um fato NOVO e atual (recorde de
    exportação no mês corrente) — não pode cair. `_CONTROLE_CORRECAO` é uma
    correção de HOJE sobre um relatório do mês do incidente — o fato é novo
    (a correção), mesmo citando um relatório velho — também não pode cair."""
    chave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chave or chave == CHAVE_ANTHROPIC_PLACEHOLDER:
        pytest.skip("ANTHROPIC_API_KEY não configurada (só o placeholder do conftest)")

    agora = alert_checker.datetime.now(alert_checker._BRT)

    class _DataFixa(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(agora.year, agora.month, agora.day, agora.hour, agora.minute,
                       agora.second, agora.microsecond, tzinfo=tz)

    monkeypatch.setattr(alert_checker, "datetime", _DataFixa)

    mes_corrente_num = agora.month
    mes_incidente_num = (mes_corrente_num - 4 - 1) % 12 + 1
    mes_incidente = _mes_ingles(mes_incidente_num)
    mes_corrente = _mes_ingles(mes_corrente_num)
    # Item 4 (4ª revisão do Apolo, 05/09/2026) — bomba de CALENDÁRIO: de
    # janeiro a abril, "mês corrente − 4" cai no ANO ANTERIOR (mes_corrente_num
    # <= 4 → dezembro/novembro/outubro/setembro do ano passado). Os títulos
    # abaixo não nomeavam ano nenhum — um mês citado sem ano é ambíguo entre
    # "safra deste ano" e "safra do ano passado" para o classificador, o mesmo
    # tipo de ambiguidade que o incidente real (WASDE de maio reindexado em
    # setembro) explorava, só que introduzida pelo PRÓPRIO teste em vez de
    # pelo agregador. `ano_incidente` cai um ano ANTES de `agora.year`
    # exatamente quando o mês do incidente atravessou a virada.
    ano_incidente = agora.year - (1 if mes_corrente_num <= 4 else 0)

    incidente = {
        "titulo": f"{mes_incidente} {ano_incidente} WASDE report to reveal first look at new crop outlook",
        "resumo": f"USDA will be releasing tomorrow the {mes_incidente} {ano_incidente} World "
                  "Agricultural Supply and Demand Estimates report, the first look at the new "
                  "crop outlook.",
    }
    # Controle: mesma estrutura de frase (relatório mensal do USDA, "under the
    # microscope" tão vago quanto "reveal"), mas nomeando o mês CORRENTE —
    # não pode ser penalizado pela mesma regra.
    controle_fresco = {
        "titulo": f"{mes_corrente} {agora.year} WASDE puts corn yields under the microscope",
        "resumo": f"USDA's {mes_corrente} {agora.year} WASDE report is due today and could "
                  "reshape expectations for this year's corn yield.",
    }
    # Controle 3º (item 3): safra NOMEADA dentro de um fato novo e atual —
    # exportação recorde do mês corrente, com dado OFICIAL e efeito de preço
    # explícito (basis e frete), para não ficar na fronteira entre "relevante"
    # (3-5) e "fora do escopo" por falta de gancho de preço, e sim ancorada no
    # padrão "dado oficial divulgado" da faixa 6-10. Citar a safra 25/26 NÃO
    # pode rebaixar: o assunto é diário, não sintoma de reindexação.
    controle_exportacao = {
        "titulo": "Brazil's official customs data confirm record 25/26 soybean exports in August",
        "resumo": "Government trade data confirmed Brazilian soybean exporters shipped a record "
                  "volume in August, driven by strong Chinese demand and pushing local basis and "
                  "freight rates higher.",
    }
    # Controle 4º (item 3): fato NOVO (a correção, publicada hoje) sobre um
    # relatório do mês do incidente — o relatório em si é velho, mas o que a
    # matéria anuncia (a correção) é de hoje.
    controle_correcao = {
        "titulo": f"USDA corrects {mes_incidente} {ano_incidente} WASDE data after processing error",
        "resumo": f"USDA issued a correction today to the {mes_incidente} {ano_incidente} WASDE "
                  "report's corn stocks figure after identifying a data processing error.",
    }

    publicado_em_hoje = agora.isoformat()

    notas_incidente = [_classificar(incidente, publicado_em_hoje) for _ in range(3)]
    notas_controle = [_classificar(controle_fresco, publicado_em_hoje) for _ in range(3)]
    nota_exportacao = _classificar(controle_exportacao, publicado_em_hoje)
    nota_correcao = _classificar(controle_correcao, publicado_em_hoje)

    print(f"\n<hoje> fixado em: {agora.date().isoformat()} (mês incidente={mes_incidente}, "
          f"mês corrente={mes_corrente})")
    print(f"notas incidente (WASDE de {mes_incidente}, publicado_em=hoje): {notas_incidente}")
    print(f"notas controle fresco (WASDE do mês corrente, publicado_em=hoje): {notas_controle}")
    print(f"nota controle exportação (safra citada, fato novo): {nota_exportacao}")
    print(f"nota controle correção (relatório velho, fato novo): {nota_correcao}")

    assert all(n <= 4 for n in notas_incidente), notas_incidente
    assert all(n >= 5 for n in notas_controle), notas_controle
    assert nota_exportacao >= 5, nota_exportacao
    assert nota_correcao >= 5, nota_correcao
