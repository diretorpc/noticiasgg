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

# O link da BUSCA e DIFERENTE do link do REGISTRO de proposito. Com os dois iguais,
# `usda.gov/nass` aparecia nas duas fontes e a metrica de recuperacao nao distinguia
# "usou o alerta que recebeu" de "achou algo parecido na web" (achado 7, 2a revisao).
# Separados, o eval passa a medir a diferenca — que e o ponto da Story 2 inteira.
_URL_BUSCA = "https://www.agweb.com/news/crops/corn-condition-holds-61-percent"

_BUSCA_CONGELADA = {"resultados": [{
    "titulo": "Corn Condition Holds at 61% Good to Excellent",
    "snippet": "Weekly crop progress report released August 17, 2026.",
    "link": _URL_BUSCA,
}]}

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
_PCT_TOKEN = re.compile(r"(?<![\d.,])(\d{1,3})\s?%")
_CULTURA = re.compile(r"milho|soja|trigo", re.IGNORECASE)
_FIM_DE_FRASE = ".;\n"

# Sinais de que a resposta trouxe CONTEÚDO. Medir por presença, não por ausência de
# frase evasiva: lista negra é corrida que o modelo ganha só reformulando, e três
# respostas mudas mas educadas davam placar perfeito com zero conteúdo (achado 4).
# `2026` saiu: está no enunciado da pergunta 3, então repeti-lo não prova conteúdo —
# mesma classe do achado 5. Os numéricos são casados com borda, senão "61" casa
# dentro de "R$ 1.618,00" (achado 6, 2ª revisão).
_CONTEUDO_NUM = ("61", "62", "51")
_CONTEUDO_TXT = ("17 de agosto", "17/08", "August 17", "Crop Progress", "NASS")

# Marcas de NEGAÇÃO. A pergunta 3 é "isso é de 2026 ou 2025?", e a resposta CERTA
# nomeia 2025 para negá-lo — contar isso como armadilha acusa alucinação justamente
# quando o agente acerta. Era o mesmo defeito que tirei do eval irmão e deixei aqui
# (achado 3, 2ª revisão do Apolo).
_NEGACAO = re.compile(r"\b(n[ãa]o|nenhum|nunca|jamais|incorret|errad|desmenti)", re.IGNORECASE)
_RAIO_NEGACAO = 70

# Provas de que ele RECUPEROU DO REGISTRO. Não pode estar no enunciado (senão
# papagaiar o usuário vira acerto — achado 5) NEM no artigo/busca (senão a métrica
# mede o `read_article`, não o registro — achado 7). `11h05` é o `sent_at` da
# fixture convertido para BRT: só existe no registro. `_conferir_marcadores` trava
# as duas portas.
_MARCAS_RECUPERACAO = ("usda.gov/nass", "11h05")
_PCT_RE = re.compile(r"(\d{1,3})\s?%")


def _pares_cultura_pct(resposta: str) -> set[tuple[str, str]]:
    r"""Cultura mais PRÓXIMA de cada percentual, sem atravessar fim de frase.

    A primeira versão era `(milho|soja|trigo)\D{0,70}?(\d+)%`, e errava dos dois
    lados (achado 2, 2ª revisão do Apolo, tudo medido):
      - "o milho segue firme; o trigo está em 51%" dava (milho, 51) — atribuía ao
        milho o número do TRIGO, inventando contradição numa resposta correta;
      - "61% para o milho" não casava nada, então três turnos dizendo 61/62/51 para
        o milho passavam como coerentes. O cartão saía perfeito para a conversa que
        é a forma exata do incidente.
    """
    pares = set()
    for m in _PCT_TOKEN.finditer(resposta):
        ini = max((resposta.rfind(c, 0, m.start()) for c in _FIM_DE_FRASE), default=-1) + 1
        antes = _CULTURA.findall(resposta[ini:m.start()])
        if antes:
            pares.add((antes[-1].lower(), m.group(1)))
            continue
        cortes = [i for i in (resposta.find(c, m.end()) for c in _FIM_DE_FRASE) if i != -1]
        depois = _CULTURA.findall(resposta[m.end():min(cortes, default=len(resposta))])
        if depois:
            pares.add((depois[0].lower(), m.group(1)))
    return pares


def _tem_conteudo(resposta: str) -> bool:
    if any(t in resposta for t in _CONTEUDO_TXT):
        return True
    return any(re.search(rf"(?<![\d.,]){n}(?![\d])", resposta) for n in _CONTEUDO_NUM)


def _armadilhas_afirmadas(resposta: str) -> list[str]:
    """Armadilha só conta se AFIRMADA — negar é o comportamento certo."""
    pegas = []
    for a in _ARMADILHAS:
        i = resposta.find(a)
        if i == -1:
            continue
        redor = resposta[max(0, i - _RAIO_NEGACAO):i + len(a) + _RAIO_NEGACAO]
        if not _NEGACAO.search(redor):
            pegas.append(a)
    return pegas


def _conferir_marcadores() -> None:
    """O marcador tem que ser EXCLUSIVO do registro.

    Se estiver no enunciado, papagaiar o usuário vira acerto. Se estiver no artigo
    ou na busca, a métrica mede o `read_article` e não o registro — as duas portas,
    na mesma métrica que dá título ao eval (achados 5 e 7).
    """
    fontes = {
        "enunciado": " ".join(_PERGUNTAS),
        "artigo": _ARTIGO,
        "busca": json.dumps(_BUSCA_CONGELADA, ensure_ascii=False),
    }
    for onde, texto in fontes.items():
        dentro = [m for m in _MARCAS_RECUPERACAO if m.lower() in texto.lower()]
        if dentro:
            raise SystemExit(
                f"marcador de recuperação também aparece no {onde}: {dentro}. "
                "Ele precisa ser algo que SÓ o registro poderia ter dito."
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
        return _BUSCA_CONGELADA

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
        if _tem_conteudo(resposta):
            placar["respondeu_de_fato"] += 1
        pegou = _armadilhas_afirmadas(resposta)
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
    # `pares_medidos` publicado, e `coerente` NUNCA sai True quando nada foi medido:
    # métrica que não sabe dizer "não medi" é a mesma armadilha do `| tee` (achado 2).
    pares_medidos = sum(len(s) for s in pares_por_resposta)
    placar["pares_medidos"] = pares_medidos
    citou_pct = any(pct_por_resposta)
    if citou_pct and not pares_medidos:
        placar["coerente_entre_respostas"] = "inconclusivo"
    else:
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
