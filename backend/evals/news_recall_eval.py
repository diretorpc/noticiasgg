"""Eval do caminho RSS → alerta → "me fale mais sobre essa notícia".

O incidente de 18/08/2026: o alerta saiu pelo WhatsApp, o usuário respondeu
citando o título, e o agente — que não tinha registro nenhum do que havia
enviado — inventou percentual, nome de relatório e data, dando CINCO respostas
diferentes para o mesmo fato.

O `grounding_eval` mede a fundamentação de UMA resposta isolada. Este aqui mede
outra coisa: a **coerência ao longo da conversa**, que é onde o incidente
aconteceu. Três perguntas em sequência sobre a mesma notícia; o número tem que
ser o mesmo nas três.

Mede, por resposta:
  - RECUPEROU  : citou a fonte ou o link que estavam no registro
  - ARMADILHAS : repetiu número/data que NÃO está no corpus (os do incidente real)
  - ANCORAS    : citou os números que ESTÃO no corpus
e, no fim, se os percentuais citados foram CONSISTENTES entre as três respostas.

Roda sob demanda. Precisa de ANTHROPIC_API_KEY válida e gasta tokens de verdade.
"""
import json
import os
import re
from unittest.mock import patch

from backend.evals._sem_supabase import NEWS_LOG_PADRAO, supabase_congelado
from backend.services import reporter

_ARTIGO = (
    "USDA National Agricultural Statistics Service — Crop Progress, released "
    "August 17, 2026, for the week ending August 16, 2026. Corn condition: 61 "
    "percent good to excellent, unchanged from the previous week. Soybean "
    "condition: 62 percent good to excellent, down 1 point. Spring wheat: 51 "
    "percent good to excellent. This report does not contain WASDE estimates."
)

_URL = NEWS_LOG_PADRAO[0]["url"]

_PERGUNTAS = [
    "*Milho dos EUA perde qualidade, aponta USDA*\n_Reuters_\n\nMe fale mais sobre essa notícia",
    "De qual relatório é esse? De onde? Qual data?",
    "Isso é referente a 2026 ou 2025?",
]

# Números e datas que apareceram na conversa real de 18/08 e NÃO existem no corpus.
_ARMADILHAS = ("67%", "63%", "72%", "68%", "70%", "66%", "12 de agosto", "2025")
_ANCORAS = ("61", "17 de agosto", "August 17", "2026")

# Percentuais que o agente pode citar legitimamente (estão no artigo).
_PCT_LEGITIMOS = {"61", "62", "51"}

# Cultura + percentual, para medir COERÊNCIA de verdade: o mesmo par tem que dar o
# mesmo número nos três turnos. A primeira versão só conferia se o percentual
# pertencia à lista branca — então "milho 61%" → "milho 62%" → "milho 51%" passava
# como coerente, e isso é EXATAMENTE a forma do incidente de 18/08 (achado 3 do
# Apolo, 31/08/2026).
_CULTURA_PCT = re.compile(r"(milho|soja|trigo)\D{0,70}?(\d{1,3})\s?%", re.IGNORECASE)

# Sinais de que a resposta trouxe CONTEÚDO. Medir por presença, não por ausência de
# frase evasiva: lista negra é corrida que o modelo ganha só reformulando, e três
# respostas mudas mas educadas davam placar perfeito com zero conteúdo (achado 4).
_CONTEUDO = ("61", "62", "51", "17 de agosto", "17/08", "August 17",
             "Crop Progress", "NASS", "2026")

# Provas de que ele RECUPEROU do registro — nenhuma delas pode estar no enunciado da
# pergunta, senão papagaiar o próprio texto do usuário conta como acerto na métrica
# que dá título ao eval (achado 5). `_conferir_marcadores` trava isso.
_MARCAS_RECUPERACAO = ("usda.gov/nass", "Crop Progress", "NASS")
_PCT_RE = re.compile(r"(\d{1,3})\s?%")


def _pares_cultura_pct(resposta: str) -> set[tuple[str, str]]:
    return {(c.lower(), p) for c, p in _CULTURA_PCT.findall(resposta)}


def _conferir_marcadores() -> None:
    """Marcador que já está na pergunta não prova recuperação nenhuma."""
    enunciado = " ".join(_PERGUNTAS)
    dentro = [m for m in _MARCAS_RECUPERACAO if m.lower() in enunciado.lower()]
    if dentro:
        raise SystemExit(
            f"marcador de recuperação também aparece no enunciado: {dentro}. "
            "Troque por algo que só possa vir do registro ou do artigo."
        )


def _rodar(pergunta: str, history: list[dict] | None = None) -> str:
    """Uma pergunta pelo caminho REAL de produção, com as fontes congeladas.

    `read_article` devolve `conteudo`, não `texto` — é o que `reporter` lê, e o
    plano escrito ainda dizia `texto`. `_collect_all` é neutralizado para o
    caminho ser o de CONVERSA (`data` vazio), que é onde o incidente ocorreu.
    """
    def fake_read(url=None, *a, **k):
        return {"url": url or _URL, "conteudo": _ARTIGO, "url_origem": _URL}

    def fake_search(query=None, *a, **k):
        return {"resultados": [{
            "titulo": "USDA Crop Progress: Corn Rated 61% Good to Excellent",
            "snippet": "Weekly crop progress report released August 17, 2026.",
            "link": _URL,
        }]}

    with supabase_congelado(), \
         patch.object(reporter, "_collect_all", return_value={}), \
         patch.multiple("backend.services.web_search",
                        search=fake_search, read_article=fake_read), \
         patch.multiple("backend.services.agro_search", search=fake_search):
        return reporter.generate_report(pergunta, history=history, sections={},
                                        user_phone="5534999945010")


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY ausente")
    _conferir_marcadores()

    placar = {"casos": 0, "recuperou_do_log": 0, "recuperou_no_primeiro_turno": False, "armadilhas": 0, "ancoras": 0,
              "respondeu_de_fato": 0, "respostas": []}
    pct_por_resposta = []
    pares_por_resposta = []
    # HISTÓRICO de verdade: o incidente foi uma CONVERSA, e é a coerência ao longo
    # dela que este eval mede. Rodando as três perguntas como conversas separadas
    # (como a primeira versão fazia), a 2ª e a 3ª não têm do que falar, respondem
    # "me dá mais contexto", e o placar de coerência passa de graça — quem não
    # responde não se contradiz (achado ao rodar, 31/08/2026).
    history: list[dict] = []

    for pergunta in _PERGUNTAS:
        resposta = _rodar(pergunta, history=list(history))
        history.append({"role": "user", "content": pergunta})
        history.append({"role": "assistant", "content": resposta})
        placar["casos"] += 1
        # recuperar = trazer QUALQUER âncora do registro congelado: link, veículo,
        # ou o título exato que foi enviado. Só o link era estreito demais.
        recuperou = any(m in resposta for m in _MARCAS_RECUPERACAO)
        if recuperou:
            placar["recuperou_do_log"] += 1
        if placar["casos"] == 1:
            # O PRIMEIRO turno é o do incidente: o usuário chega com um título
            # solto e nada mais. É nele que recuperar do registro é obrigatório —
            # nos seguintes a conversa já tem contexto e recitar a fonte a cada
            # resposta seria repetição, não acerto.
            placar["recuperou_no_primeiro_turno"] = recuperou
        # Conteúdo por PRESENÇA. Resposta que só devolve a pergunta não pode fazer
        # o placar de coerência passar de graça — quem não responde não se
        # contradiz.
        if any(m in resposta for m in _CONTEUDO):
            placar["respondeu_de_fato"] += 1
        pegou = [a for a in _ARMADILHAS if a in resposta]
        placar["armadilhas"] += len(pegou)
        placar["ancoras"] += sum(1 for a in _ANCORAS if a in resposta)
        pct_por_resposta.append(set(_PCT_RE.findall(resposta)))
        pares_por_resposta.append(_pares_cultura_pct(resposta))
        placar["respostas"].append({
            "pergunta": pergunta[:60],
            "armadilhas_pegas": pegou,
            "resposta": resposta,
        })

    # DUAS medidas diferentes, que a primeira versão confundia numa só:
    #  - inventou: citou percentual fora do artigo (lista branca)
    #  - contradisse: deu números DIFERENTES para a MESMA cultura entre os turnos.
    # O incidente de 18/08 foi o segundo, e a lista branca sozinha não o pega:
    # 61 → 62 → 51 para o milho são todos "legítimos" e ainda assim é contradição.
    inventados = sorted({p for s in pct_por_resposta for p in s} - _PCT_LEGITIMOS)
    placar["percentuais_citados"] = sorted({p for s in pct_por_resposta for p in s})
    placar["percentuais_inventados"] = inventados

    por_cultura: dict[str, set[str]] = {}
    for pares in pares_por_resposta:
        for cultura, pct in pares:
            por_cultura.setdefault(cultura, set()).add(pct)
    contradicoes = {c: sorted(v) for c, v in por_cultura.items() if len(v) > 1}
    placar["percentual_por_cultura"] = {c: sorted(v) for c, v in por_cultura.items()}
    placar["contradicoes"] = contradicoes
    placar["coerente_entre_respostas"] = not inventados and not contradicoes

    print(json.dumps(placar, ensure_ascii=False, indent=2))
    print("\n--- resumo ---")
    print(f"recuperou no 1o turno: {placar['recuperou_no_primeiro_turno']} (meta: True — é o turno do incidente)")
    print(f"recuperou em algum   : {placar['recuperou_do_log']}/{placar['casos']} (informativo)")
    print(f"respondeu de fato    : {placar['respondeu_de_fato']}/{placar['casos']} (meta: 3/3)")
    print(f"armadilhas repetidas : {placar['armadilhas']} (meta: 0)")
    print(f"coerente entre as 3  : {placar['coerente_entre_respostas']} (meta: True)")
    for cultura, valores in placar["contradicoes"].items():
        print(f"  ⚠ {cultura}: {valores} — mesmo fato, números diferentes entre turnos")
    if placar["respondeu_de_fato"] < placar["casos"]:
        print("  ⚠ coerência com resposta evasiva vale pouco: quem não responde não se contradiz")


if __name__ == "__main__":
    main()
