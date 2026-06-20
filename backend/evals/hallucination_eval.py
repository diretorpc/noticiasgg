"""Eval de alucinação (LLM-as-judge). Roda sob demanda / agendado, NÃO bloqueia merge.

Para cada seção de texto: gera o texto a partir de dados congelados e pede a um
juiz Claude para contar afirmações ancoradas vs inventadas. Emite score por seção.
"""
import json
import os
import re as _re
from pathlib import Path

from anthropic import Anthropic

from backend.services import report_engine

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_data.json"

_JUDGE_SYSTEM = """Você é um juiz de integridade factual. Recebe um texto de relatório e os DADOS que o originaram (JSON). Conte quantas afirmações factuais do texto estão ANCORADAS nos dados e quantas são INVENTADAS (não verificáveis nos dados). Responda EXATAMENTE em 3 linhas:
ancoradas: <número>
inventadas: <número>
veredito: <ok|suspeito>"""

_CTX_BUILDERS = {
    "noticias": lambda d: report_engine.adapt_noticias(d.get("noticias", [])),
    "analise": lambda d: report_engine.adapt_analise(
        {"bolsas": d.get("bolsas", {}), "cambio": d.get("cambio", {})},
        d.get("cripto", []), d.get("indicadores_br", {}), d.get("indicadores_us", {}),
        d.get("noticias", [])),
    "politica": lambda d: report_engine.adapt_politica(d.get("politica", []), d.get("pesquisas", [])),
}


def parse_judge_verdict(text: str) -> dict:
    def _num(label):
        m = _re.search(rf"{label}:\s*(\d+)", text, _re.IGNORECASE)
        return int(m.group(1)) if m else 0
    return {"ancoradas": _num("ancoradas"), "inventadas": _num("inventadas")}


def run() -> dict:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=90.0, max_retries=1)
    scores = {}
    for section, build_ctx in _CTX_BUILDERS.items():
        ctx = build_ctx(data)
        text = report_engine._render(section, ctx, client)
        judge = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=200, system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content":
                       f"DADOS:\n{json.dumps(ctx['data'], ensure_ascii=False)}\n\nTEXTO:\n{text}"}],
        )
        verdict_text = next((b.text for b in judge.content if hasattr(b, "text")), "")
        scores[section] = parse_judge_verdict(verdict_text)
    print(json.dumps(scores, ensure_ascii=False, indent=2))
    return scores


if __name__ == "__main__":
    run()
