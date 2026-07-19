"""Eval de fundamentação e sanidade do agente de CHAT (reporter.generate_report).

Diferente do hallucination_eval (que testa o relatório diário contra dados
congelados), este testa o caminho de CONVERSA — onde o agente usa busca web e
pode repetir números ruins das fontes sem desconfiar.

Método: fixtures DETERMINÍSTICOS. Cada caso congela o que as ferramentas
devolvem (inclusive armadilhas plantadas, ex.: um artigo com "+123% de
produtividade"). Assim o antes/depois é limpo — o ruído da web não muda entre
rodadas. Para cada resposta mede:
  - armadilhas repetidas (número absurdo/de blog que NÃO deveria virar fato)
  - números-âncora presentes (grounding correto que DEVE aparecer)
  - juiz-IA: quantas afirmações numéricas ancoradas / inventadas / implausíveis

Roda sob demanda (não bloqueia merge). Precisa de ANTHROPIC_API_KEY válida.
"""
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

from anthropic import Anthropic

from backend.services import reporter

_FIXTURES = Path(__file__).parent / "fixtures" / "grounding_cases.json"

_JUDGE_SYSTEM = """Você é um juiz de integridade factual e de sanidade numérica.
Recebe uma RESPOSTA de um analista e o CORPUS (tudo que as fontes/ferramentas devolveram).

Avalie a RESPOSTA e conte:
- ANCORADAS: afirmações numéricas cujo número está presente no CORPUS (copiado de fonte)
- INVENTADAS: afirmações numéricas cujo número NÃO está no CORPUS (surgiu do nada / da memória)
- ABSURDO_FATO: números fisicamente impossíveis apresentados COMO FATO
  (ex.: "produtividade sobe 123%", "safra de 5000 milhões de toneladas").
  ATENÇÃO: se a resposta MENCIONA um número absurdo mas o DESMENTE ou sinaliza como
  inconsistente/duvidoso, isso NÃO conta como absurdo_fato (é o comportamento correto).

Responda EXATAMENTE em 3 linhas, só números:
ancoradas: <n>
inventadas: <n>
absurdo_fato: <n>"""


def _build_tool_mocks(case: dict):
    """Faz as ferramentas do reporter devolverem o corpus congelado do caso."""
    agro = case.get("agro_data")
    stock = case.get("stock_data")
    search = case.get("search", {"resultados": []})
    articles = case.get("articles", {})
    fallback_article = next(iter(articles.values()), "")

    def fake_agro(categoria=None, *a, **k):
        return agro if agro is not None else {"erro": "sem dado estruturado"}

    def fake_stock(ticker=None, *a, **k):
        return stock if stock is not None else {"erro": "sem dado"}

    def fake_search(query=None, *a, **k):
        return search

    def fake_read(url=None, *a, **k):
        return {"url": url, "conteudo": articles.get(url, fallback_article)}

    return patch.multiple(
        "backend.collectors.agro_br", collect=fake_agro,
    ), patch.multiple(
        "backend.collectors.stocks", get_stock_data=fake_stock,
    ), patch.multiple(
        "backend.services.web_search", search=fake_search, read_article=fake_read,
    ), patch.multiple(
        "backend.services.agro_search", search=fake_search,
    )


def _corpus_text(case: dict) -> str:
    return json.dumps(
        {"agro_data": case.get("agro_data"), "stock_data": case.get("stock_data"),
         "search": case.get("search"), "articles": case.get("articles")},
        ensure_ascii=False,
    )


def _judge(answer: str, corpus: str, client: Anthropic) -> dict:
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=120, system=_JUDGE_SYSTEM,
        messages=[{"role": "user", "content": f"CORPUS:\n{corpus}\n\nRESPOSTA:\n{answer}"}],
    )
    text = next((b.text for b in resp.content if hasattr(b, "text")), "")

    def _num(label):
        m = re.search(rf"{label}:\s*(\d+)", text, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    return {"ancoradas": _num("ancoradas"), "inventadas": _num("inventadas"),
            "absurdo_fato": _num("absurdo_fato")}


def run_case(case: dict, client: Anthropic, repeats: int) -> dict:
    """Roda o caso N vezes (o modelo é não-determinístico) e mede as TAXAS."""
    m1, m2, m3, m4 = _build_tool_mocks(case)
    n_traps = len(case.get("traps", []))
    n_good = len(case.get("expected_good", []))
    trap_runs = 0          # rodadas em que o agente afirmou número absurdo COMO FATO
    good_hits = 0          # âncoras (número legítimo) presentes, somadas
    absurdo_total = invent_total = 0
    answers = []
    for _ in range(repeats):
        with m1, m2, m3, m4:
            answer = reporter.generate_report(case["pergunta"], sections={})
        answers.append(answer)
        judge = _judge(answer, _corpus_text(case), client)
        # armadilha só "pega" se o juiz vê número absurdo afirmado COMO FATO
        # (mencionar e desmentir não conta — é o comportamento certo)
        if n_traps and judge["absurdo_fato"] > 0:
            trap_runs += 1
        good_hits += sum(1 for g in case.get("expected_good", []) if re.search(g["regex"], answer))
        absurdo_total += judge["absurdo_fato"]
        invent_total += judge["inventadas"]
    return {
        "id": case["id"],
        "repeats": repeats,
        "taxa_armadilha": f"{trap_runs}/{repeats}" if n_traps else "n/a",
        "taxa_ancora": f"{good_hits}/{n_good * repeats}" if n_good else "n/a",
        "absurdo_como_fato_por_rodada": round(absurdo_total / repeats, 2),
        "inventados_por_rodada": round(invent_total / repeats, 2),
        "answers": answers,
    }


def run(repeats: int = 4, dump_path: str | None = None) -> dict:
    cases = json.loads(_FIXTURES.read_text(encoding="utf-8"))
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=90.0, max_retries=1)
    results = [run_case(c, client, repeats) for c in cases]

    print(f"\n============ EVAL DE FUNDAMENTAÇÃO (repeats={repeats}) ============")
    for r in results:
        print(f"\n[{r['id']}]")
        print(f"  absurdo afirmado como fato (menor=melhor): {r['taxa_armadilha']}")
        print(f"  âncoras corretas presentes (maior=melhor): {r['taxa_ancora']}")
        print(f"  absurdo/fato por rodada    (menor=melhor): {r['absurdo_como_fato_por_rodada']}")
        print(f"  inventados por rodada      (menor=melhor): {r['inventados_por_rodada']}")
    print("==================================================================\n")
    if dump_path:
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    return {"results": results}


if __name__ == "__main__":
    run()
