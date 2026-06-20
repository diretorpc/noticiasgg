import json
from anthropic import Anthropic

ANALYSIS_MARKERS = ("📊", "ANÁLISE", "Visão Macro", "Visão Brasil", "Visão Agro")

SYSTEM_VALIDATOR = """Você é um validador de integridade factual para relatórios financeiros enviados via WhatsApp.

Você receberá:
1. Um relatório gerado por IA
2. Os dados brutos que o geraram (JSON)

Sua única tarefa: retornar o relatório corrigido, removendo ou reescrevendo qualquer afirmação factual que NÃO possa ser verificada nos dados recebidos.

O que DEVE ser removido ou corrigido:
- Números, percentuais ou preços que não aparecem nos dados
- Empresas, países ou organizações não mencionados nos dados ou nas notícias
- Atribuições geográficas não verificáveis ("empresa X é do país Y" sem base nos dados)
- Relações causais inventadas ("X subiu porque Y" se Y não está nos dados como fato real)
- Qualquer afirmação especulativa apresentada como verdade factual

O que DEVE ser preservado:
- Seções de dados diretos (câmbio, bolsas, cripto, indicadores) — esses vêm dos coletores e já são verificados
- Notícias que aparecem na lista de notícias dos dados
- Formatação WhatsApp (*negrito*, _itálico_, emojis, quebras de linha)
- Estrutura geral do relatório e tom de analista

Retorne APENAS o relatório corrigido, sem prefácio, sem explicação, sem comentário."""


def build_fact_corpus(data: dict) -> str:
    """Serializa as partes mais relevantes dos dados coletados para o validador.
    Limita o tamanho para manter custo de tokens baixo."""
    parts = []
    for key in ("market", "crypto", "indicators_br", "indicators_us", "commodities_br"):
        val = data.get(key)
        if val and not (isinstance(val, dict) and "erro" in val):
            parts.append(f"{key}: {json.dumps(val, ensure_ascii=False, default=str)}")
    for key, label, limit in (
        ("news", "Notícias", 10),
        ("politics_br", "Política", 5),
        ("polls_br", "Pesquisas", 3),
    ):
        val = data.get(key)
        if isinstance(val, list) and val:
            titles = [a.get("titulo", a.get("instituto", "")) for a in val[:limit]]
            parts.append(f"{label}: {json.dumps(titles, ensure_ascii=False)}")
    return "\n".join(parts)[:6000]


def validate_and_fix(report: str, data: dict, client: Anthropic) -> str:
    """Passagem de validação pós-geração via Claude Haiku.
    Remove afirmações factuais não verificáveis nos dados coletados.
    Retorna o relatório corrigido; em caso de falha retorna o original."""
    if not data or not any(m in report for m in ANALYSIS_MARKERS):
        return report
    fact_corpus = build_fact_corpus(data)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_VALIDATOR,
            messages=[{
                "role": "user",
                "content": (
                    f"Relatório para validar:\n{report}\n\n"
                    f"Dados brutos disponíveis:\n{fact_corpus}"
                ),
            }],
        )
        for block in resp.content:
            if hasattr(block, "text") and len(block.text.strip()) > 100:
                return block.text.strip()
    except Exception:
        pass
    return report
