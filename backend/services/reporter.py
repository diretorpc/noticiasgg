import os
import json
from anthropic import Anthropic

from backend.collectors import (
    market, crypto, indicators_us, indicators_br, news,
    commodities_br, politics_br, polls_br,
)

ALL_SECTIONS = [
    "market", "crypto", "indicators_us", "indicators_br",
    "news", "commodities_br", "politics_br", "polls_br",
]
DEFAULT_SECTIONS = {s: True for s in ALL_SECTIONS}

_SYSTEM_MARKET = """Você é um analista financeiro brasileiro especialista em mercados, indicadores macroeconômicos e geopolítica.

Você recebe dados estruturados (JSON) com cotações de bolsas, câmbio, criptomoedas, indicadores econômicos (BR/EUA) e notícias. Sua tarefa é gerar um resumo claro, conciso e acionável em português, formatado para WhatsApp (use *negrito*, _itálico_, emojis com moderação, sem markdown de código).

Regras:
- Comece com um resumo de 1-2 linhas do dia
- Destaque variações relevantes (>1%) em bolsas, câmbio e cripto
- Mencione indicadores econômicos novos
- Cite as 2-3 notícias mais relevantes
- Termine com uma análise breve do cenário
- Máximo 1500 caracteres
- Se o usuário fizer pergunta específica, responda diretamente sem o formato de resumo"""

_SYSTEM_CHAT = """Você é um assistente financeiro brasileiro, inteligente e próximo — como um amigo que entende muito de economia, mercado e política.

Responda de forma natural e humana, como numa conversa de WhatsApp. Sem formatação de relatório, sem seções, sem bullets obrigatórios. Use *negrito* só quando realmente precisar destacar algo. Emojis com moderação e só quando ficarem naturais.

Se for uma saudação ou bate-papo casual, responda de forma leve e amigável.
Se for uma pergunta sobre qualquer assunto (política, economia, geografia, história, curiosidade), explique de forma clara e direta como se estivesse conversando — não como se fosse um documento ou automação.
Seja conciso: máximo 3-4 parágrafos curtos."""


def _safe_collect(fn):
    try:
        return fn()
    except Exception as e:
        return {"erro": str(e)}


_COLLECTORS = {
    "market": lambda: market.collect(),
    "crypto": lambda: crypto.collect(),
    "indicators_us": lambda: indicators_us.collect(),
    "indicators_br": lambda: indicators_br.collect(),
    "news": lambda: news.collect(),
    "commodities_br": lambda: commodities_br.collect(),
    "politics_br": lambda: politics_br.collect(),
    "polls_br": lambda: polls_br.collect(),
}


def _collect_all(sections: dict | None = None) -> dict:
    active = sections if sections is not None else DEFAULT_SECTIONS
    return {
        k: _safe_collect(fn)
        for k, fn in _COLLECTORS.items()
        if active.get(k, False)
    }


def generate_report(
    user_message: str,
    history: list[dict] | None = None,
    user_name: str | None = None,
    sections: dict | None = None,
) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    data = _collect_all(sections=sections)

    system = _SYSTEM_MARKET if data else _SYSTEM_CHAT
    if user_name:
        primeiro_nome = user_name.split()[0]
        system += (
            f"\n\nVocê está conversando com {user_name}. Trate por *{primeiro_nome}* "
            f"(primeiro nome). Use o nome de forma natural — em saudações, ao começar "
            f"respostas longas, ou quando quiser dar um tom pessoal — mas sem exagerar "
            f"(não em toda frase)."
        )

    if data:
        user_content = (
            f"Mensagem do usuário: {user_message}\n\n"
            f"Dados de mercado coletados agora:\n{json.dumps(data, ensure_ascii=False, default=str)}"
        )
    else:
        user_content = f"Mensagem do usuário: {user_message}"

    messages = list(history or [])
    messages.append({"role": "user", "content": user_content})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=messages,
    )

    return response.content[0].text
