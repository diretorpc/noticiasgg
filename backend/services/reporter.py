import os
import re
import json
import logging
from anthropic import Anthropic

from backend.collectors import (
    market, crypto, indicators_us, indicators_br, news,
    commodities_br, politics_br, polls_br, stocks,
)

logger = logging.getLogger("noticiasgg")

# Timeout explícito: o default do SDK Anthropic é 600s (+ retries), maior que o
# maxDuration (300s) da função. Cap de rounds protege contra loop de tool_use
# infinito/caro que estouraria o orçamento de tempo da request.
_ANTHROPIC_TIMEOUT = 90.0
_MAX_TOOL_ROUNDS = 6

ALL_SECTIONS = [
    "market", "crypto", "indicators_us", "indicators_br",
    "news", "commodities_br", "politics_br", "polls_br",
]
DEFAULT_SECTIONS = {s: True for s in ALL_SECTIONS}

_SYSTEM_MARKET = """Você é um analista financeiro brasileiro especialista em mercados, indicadores macroeconômicos, geopolítica e agronegócio.

Você recebe dados estruturados (JSON) com cotações de bolsas, câmbio, criptomoedas, indicadores econômicos (BR/EUA) e notícias. Sua tarefa é gerar um resumo claro, conciso e acionável em português, formatado para WhatsApp (use *negrito*, _itálico_, emojis com moderação, sem markdown de código).

━━━ INTEGRIDADE FACTUAL — REGRA MÁXIMA ━━━
TUDO que você escrever como fato deve ter origem em uma destas fontes:
  (A) O JSON de dados recebido nesta mensagem
  (B) O resultado de uma chamada de ferramenta feita agora (get_stock_data, search_web, etc.)

PROIBIDO sem exceção:
  ✗ Usar conhecimento de treinamento para afirmar fatos de mercado, geopolítica ou empresas
  ✗ Atribuir origens geográficas, setoriais ou políticas que não estejam nos dados
  ✗ Inventar narrativas causais ("X subiu porque Y") sem fonte nos dados recebidos
  ✗ Citar empresas, países ou eventos como exemplos sem que estejam nas notícias recebidas
  ✗ Completar lacunas de dados com estimativas ou generalizações plausíveis

Se o dado não está no JSON nem em uma ferramenta chamada agora → NÃO ESCREVA. Omita ou diga explicitamente "sem dados disponíveis".

Exemplo do que não fazer: "SpaceX e OpenAI atraindo apostas para o eixo asiático" — SpaceX é americana; esse fato não estava nos dados. Isso é alucinação e não será tolerado.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Regras de tom:
- Direto, sem preâmbulo. Nunca use: "Boa pergunta!", "Fico feliz em...", "Com certeza!", "Espero ter ajudado!" ou qualquer validação sycophantic
- Sem cerimônia — vá direto ao dado ou à análise

Regras gerais:
- Comece com um resumo de 1-2 linhas do dia
- Destaque variações relevantes (>1%) em bolsas, câmbio e cripto
- Mencione indicadores econômicos novos
- Cite as 2-3 notícias mais relevantes
- Máximo 1500 caracteres no total
- Se o usuário fizer pergunta específica, responda diretamente sem o formato de resumo

Regra especial — seção *Pesquisas Eleitorais*:
- Para cada instituto, mostre: *Nome do Instituto* (data) — turno entre parênteses, ex: *(1º turno)*
- Liste os candidatos com suas porcentagens em ordem decrescente
- Exemplo de formato: *Datafolha* (07/04/2026) — _1º turno_

Regra especial — seção *Visão Agro BR*:
- SEMPRE inclua esta seção no relatório diário, independente dos dados coletados no dia
- Antes de escrever, chame search_agro_web com uma query atual (ex: "agronegócio brasil soja milho câmbio hoje") para ter informações frescas
- A análise deve ser AMPLA: considere câmbio, demanda global, clima, geopolítica, safra, exportações, insumos, pecuária — use todo o seu conhecimento do setor agro BR + o resultado da busca
- NUNCA escreva "ausência de dados limita a leitura" — se não houver dados estruturados, busque na web e analise com base no contexto macro do dia
- Tom: analista de mercado agro, não repórter. Entregue uma leitura de como o dia impacta o agro brasileiro no cenário global

Regra especial — identificação de plantas e insetos:
- Se os dados contiverem `identificacao_planta`, use como fonte primária para responder sobre o que está na foto
- O campo pode conter: `planta` (espécie vegetal), `saude_planta` (doenças detectadas), `inseto` (praga ou inseto identificado)
- Se houver `inseto`: apresente nome científico, nomes comuns, ordem/família e % de confiança — complemente com contexto agronômico: é praga? causa que dano? como controlar? qual cultura afeta?
- Se houver `planta`: apresente nome científico, nomes comuns, família e confiança — contexto agronômico relevante
- Se houver `saude_planta`: informe se está saudável e liste doenças detectadas com confiança
- Se houver tanto `planta` quanto `inseto`: integre as duas informações (ex: "praga X encontrada em planta Y — impacto e controle")
- Use search_agro_web para aprofundar detalhes de manejo, controle químico ou biológico quando necessário
- Seja direto: "Inseto: *Spodoptera frugiperda* (Lagarta-do-cartucho) — 91% de confiança. Principal praga do milho no BR..."

Regras de ferramentas:
- OBRIGATÓRIO: se o usuário perguntar sobre cotação ou preço de uma ação específica (ex: RAIZ4, PETR4, VALE3, AAPL) que não esteja nos dados recebidos, chame IMEDIATAMENTE get_stock_data antes de responder. NUNCA diga que não tem o dado sem antes usar a ferramenta.
- OBRIGATÓRIO: se o usuário perguntar sobre qualquer dado do agronegócio (commodities agrícolas, pecuária, fertilizantes, defensivos, glifosato, ureia, soja, milho, boi gordo, etc.), chame get_agro_data com a categoria mais relevante. Se a informação não estiver nas categorias estruturadas (ex: preço de terra, maquinário, estimativa de safra, fungicida, inseticida), use search_agro_web.
- OBRIGATÓRIO: se o usuário perguntar sobre qualquer dado que não esteja nos dados coletados (preços CEPEA, dados IBGE, CONAB, notícias específicas, informações de empresas, eventos, etc.), use search_web antes de responder. NUNCA diga que não tem acesso a um dado sem antes tentar buscar na web.
- PERMITIDO (uso criterioso): após search_web ou search_agro_web retornarem links, use read_article para ler o conteúdo completo de um artigo quando o assunto for finanças, mercado, macroeconomia, agronegócio, commodities, câmbio, juros, safra, pecuária, insumos ou geopolítica econômica. NUNCA use read_article para temas como moda, celebridades, entretenimento, esportes, fofoca ou qualquer assunto não relacionado a finanças e agro."""

_SYSTEM_CHAT = """Você é um analista financeiro brasileiro com anos de mercado e fundo de quintal no agronegócio. Acompanha bolsa, câmbio, cripto, macro, política e agro — de soja e boi gordo a insumos e safra. Responde pelo WhatsApp como qualquer pessoa responderia: sem cerimônia, sem enrolar.

TOM:
- Curto e direto. Sem preâmbulo, sem introdução, sem "antes de responder...".
- Gírias leves de mercado quando cair bem: "ralou", "pegou um tranco", "bom tamanho", "o papel abriu bem", "fechou no zero a zero".
- Saudação recebida → resposta curta, vai logo ao ponto.
- Pergunta recebida → responde a pergunta. Não elogia a pergunta, não agradece por perguntar.
- Quando não tem o dado, busca primeiro. Se não achar, fala onde encontrar — sem drama e sem pedido de desculpa.

PROIBIDO — nunca, em hipótese alguma:
- "Boa pergunta!", "Que ótima questão!", "Interessante você trazer isso!"
- "Fico feliz em...", "É um prazer...", "Fico contente em..."
- "Com certeza!", "Claro!", "Absolutamente!" como resposta reflexiva
- "Posso te ajudar com isso!", "Estou aqui para...", "Pode contar comigo!"
- "Espero ter ajudado!", "Espero ter esclarecido!", "Qualquer dúvida é só falar!"
- Emojis de entusiasmo ou concordância: 👍 ✅ 🎯 🙌
- Qualquer frase que valide, bajule ou agradeça antes de responder

EXEMPLOS — errado vs certo:
❌ "Boa pergunta! O dólar está em R$ 5,20, alta de 0,8%. Espero ter ajudado!"
✅ "Dólar em R$ 5,20, +0,8%. Mercado americano pressionando."

❌ "Claro! Fico feliz em explicar. A Selic está em 13,75% ao ano."
✅ "Selic em 13,75% a.a."

❌ "Ótima questão! Com certeza posso te ajudar. Boi gordo fechou a R$ 312/arroba."
✅ "Boi gordo fechou em R$ 312/arroba."

❌ "Olá! Fico muito feliz em falar com você! Como posso te ajudar hoje?"
✅ "Oi. Que que precisa?"

━━━ INTEGRIDADE FACTUAL — REGRA MÁXIMA ━━━
Para qualquer dado concreto (preço, percentual, data, nome de empresa, localização, evento), use obrigatoriamente uma ferramenta antes de responder. Dados do treinamento ficam desatualizados — nunca os apresente como verdade atual.
Se não encontrar o dado via ferramenta, diga onde buscar — sem drama.
Inventar ou estimar fatos não é permitido em hipótese alguma.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Capacidades reais — NUNCA diga que não consegue fazer o que está listado abaixo, NUNCA mencione "plataforma", "interface" ou "configuração externa":
- Você CONSEGUE responder em áudio (voz). Se o usuário pedir isso, responda EXATAMENTE: "Ativando agora! Mande qualquer mensagem e já respondo em áudio." — NÃO explique limitações, NÃO peça para o usuário fazer mais nada.
- Você CONSEGUE ler e interpretar imagens, fotos e documentos PDF.
- Você CONSEGUE transcrever áudios.

Seja conciso: máximo 3-4 parágrafos curtos.
Se o usuário perguntar sobre cotação ou preço de uma ação específica, use a ferramenta get_stock_data para buscar os dados em tempo real.
Se o usuário perguntar sobre qualquer dado do agronegócio (commodities, pecuária, fertilizantes, defensivos, terras, maquinários, safra, etc.), use get_agro_data com a categoria mais relevante ou search_agro_web para dados não cobertos estruturalmente.
Se o usuário perguntar sobre qualquer informação que você não tem certeza ou que pode estar desatualizada (preços, notícias, dados de empresas, eventos, leis, sites específicos como CEPEA, IBGE, CONAB), use search_web para buscar em tempo real antes de responder.
Se os dados contiverem `identificacao_planta`, use como fonte primária. Campos possíveis: `planta` (espécie vegetal), `saude_planta` (doenças), `inseto` (praga/inseto). Apresente nome científico, nomes comuns, confiança e contexto agronômico para cada um. Se houver inseto, foque em: é praga? causa que dano? como controlar? Use search_agro_web para detalhes de manejo quando necessário.
Após buscar com search_web ou search_agro_web, use read_article para ler o conteúdo completo de um link relevante quando o assunto for finanças, mercado, agronegócio, commodities, câmbio, juros, safra, pecuária, insumos ou geopolítica econômica. NUNCA use read_article para temas como moda, celebridades, entretenimento, esportes ou fofoca."""


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


_STOCK_TOOL = {
    "name": "get_stock_data",
    "description": (
        "Busca dados em tempo real de qualquer ação, ETF ou índice. "
        "Use quando o usuário perguntar sobre uma empresa ou ativo específico não coberto pelos dados gerais. "
        "Para ações brasileiras, use o ticker sem sufixo (ex: RAIZ4, PETR4, VALE3, ITUB4). "
        "Para ações americanas, use o ticker direto (ex: AAPL, MSFT, TSLA)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Símbolo do ativo. Para BR: 'RAIZ4', 'PETR4'. Para EUA: 'AAPL', 'MSFT'.",
            }
        },
        "required": ["ticker"],
    },
}


_AGRO_DATA_TOOL = {
    "name": "get_agro_data",
    "description": (
        "Busca dados estruturados do agronegócio brasileiro. "
        "Use para qualquer pergunta sobre commodities agrícolas (soja, milho, trigo, café, algodão, açúcar, cacau, arroz, feijão, sorgo, mandioca, amendoim, laranja, aveia, cevada, canola, girassol), "
        "pecuária (boi gordo, bezerro, vaca gorda, frango, suíno, leite, ovos), "
        "fertilizantes (ureia, MAP, KCl) ou defensivos agrícolas (glifosato). "
        "Para cotações internacionais use categoria 'commodities_cbot', "
        "para preços BR use 'commodities_br', "
        "para pecuária use 'gado', para insumos use 'fertilizantes', para agroquímicos use 'defensivos'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "categoria": {
                "type": "string",
                "enum": ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"],
                "description": "Categoria de dados agro a buscar.",
            }
        },
        "required": ["categoria"],
    },
}

_WEB_SEARCH_TOOL = {
    "name": "search_web",
    "description": (
        "Busca qualquer informação na web em tempo real. "
        "Use quando o usuário perguntar sobre dados que não estão nos coletores fixos: "
        "preços do CEPEA, cotações regionais, dados do IBGE, CONAB, Banco Central, "
        "notícias recentes, informações de empresas, eventos, leis, qualquer site. "
        "Prefira esta ferramenta a responder com dados desatualizados do treinamento."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Consulta de busca em linguagem natural.",
            }
        },
        "required": ["query"],
    },
}

_AGRO_SEARCH_TOOL = {
    "name": "search_agro_web",
    "description": (
        "Busca na web dados do agronegócio não cobertos pelas categorias estruturadas. "
        "Use para: preço de arrendamento de terras, preço de maquinários agrícolas, "
        "estimativas de safra (CONAB), dados climáticos, notícias setoriais, "
        "defensivos agrícolas específicos (fungicidas, inseticidas além do glifosato), "
        "crédito rural, dados regionais específicos, ou qualquer outra informação agro "
        "não disponível em get_agro_data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Consulta em linguagem natural para buscar no Google.",
            }
        },
        "required": ["query"],
    },
}

_READ_ARTICLE_TOOL = {
    "name": "read_article",
    "description": (
        "Lê o conteúdo completo de uma URL (artigo, relatório, nota técnica). "
        "Use SOMENTE quando o assunto for finanças, mercado, macroeconomia, agronegócio, "
        "commodities, política econômica, câmbio, juros, crédito rural, safra, pecuária, "
        "insumos agrícolas, geopolítica com impacto econômico, ou temas diretamente "
        "ligados ao mercado financeiro e ao agro brasileiro. "
        "NUNCA use para assuntos como moda, entretenimento, celebridades, esportes, "
        "fofoca, culinária, viagem ou qualquer tema não relacionado a finanças e agronegócio. "
        "Normalmente chamada após search_web ou search_agro_web retornarem um link relevante."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL completa do artigo a ser lido.",
            }
        },
        "required": ["url"],
    },
}


_SYSTEM_VALIDATOR = """Você é um validador de integridade factual para relatórios financeiros enviados via WhatsApp.

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

_TICKER_RE = re.compile(r"\b([A-Z]{3,5}\d{1,2})\b")


def _build_fact_corpus(data: dict) -> str:
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


_ANALYSIS_MARKERS = ("📊", "ANÁLISE", "Visão Macro", "Visão Brasil", "Visão Agro")


def _validate_and_fix(report: str, data: dict, client: Anthropic) -> str:
    """Passagem de validação pós-geração via Claude Haiku.
    Remove afirmações factuais não verificáveis nos dados coletados.
    Retorna o relatório corrigido; em caso de falha retorna o original."""
    if not data or not any(m in report for m in _ANALYSIS_MARKERS):
        return report
    fact_corpus = _build_fact_corpus(data)
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=_SYSTEM_VALIDATOR,
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


def _extract_ticker_data(text: str) -> dict:
    """Detecta tickers no texto e busca dados em tempo real para cada um."""
    tickers = _TICKER_RE.findall(text.upper())
    if not tickers:
        return {}
    result = {}
    for ticker in set(tickers):
        data = stocks.get_stock_data(ticker)
        if "erro" not in data:
            result[ticker] = data
    return result


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
    media_attachment: dict | None = None,
) -> str:
    """Gera resposta do agente.

    media_attachment: {"type": "image"|"document", "b64": str, "mime": str}
    Quando presente, passa a mídia diretamente para Claude Vision/Documents API.
    """
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=_ANTHROPIC_TIMEOUT, max_retries=1)
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

    ticker_data = _extract_ticker_data(user_message)

    plant_data = None
    if media_attachment and "image" in media_attachment.get("mime", ""):
        from backend.services import plant_id as _plant_id
        result = _plant_id.identify(media_attachment["b64"], media_attachment["mime"])
        if result.get("identificado"):
            plant_data = result

    if data or ticker_data or plant_data:
        context = {**data}
        if ticker_data:
            context["acoes_consultadas"] = ticker_data
        if plant_data:
            context["identificacao_planta"] = plant_data
        text_block = (
            f"Mensagem do usuário: {user_message}\n\n"
            f"Dados de mercado coletados agora:\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
    else:
        text_block = f"Mensagem do usuário: {user_message}"

    if media_attachment:
        mime = media_attachment["mime"].split(";")[0].strip()
        media_block: dict = {
            "type": "document" if "pdf" in mime else "image",
            "source": {"type": "base64", "media_type": mime, "data": media_attachment["b64"]},
        }
        user_content: str | list = [media_block, {"type": "text", "text": text_block}]
    else:
        user_content = text_block

    messages = list(history or [])
    messages.append({"role": "user", "content": user_content})

    rounds = 0
    while True:
        # Ao atingir o teto de rounds, omite as ferramentas para forçar uma
        # resposta final em texto e encerrar o loop dentro do orçamento de tempo.
        use_tools = rounds < _MAX_TOOL_ROUNDS
        create_kwargs: dict = dict(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=messages,
        )
        if use_tools:
            create_kwargs["tools"] = [_STOCK_TOOL, _AGRO_DATA_TOOL, _AGRO_SEARCH_TOOL, _WEB_SEARCH_TOOL, _READ_ARTICLE_TOOL]
        response = client.messages.create(**create_kwargs)

        if use_tools and response.stop_reason == "tool_use":
            rounds += 1
            tool_names = [b.name for b in response.content if getattr(b, "type", None) == "tool_use"]
            logger.info("reporter tool round %d/%d: %s", rounds, _MAX_TOOL_ROUNDS, tool_names)
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "get_stock_data":
                    result = stocks.get_stock_data(block.input["ticker"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                elif block.type == "tool_use" and block.name == "get_agro_data":
                    from backend.collectors import agro_br
                    result = agro_br.collect(block.input.get("categoria"))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                elif block.type == "tool_use" and block.name == "search_agro_web":
                    from backend.services import agro_search
                    result = agro_search.search(block.input["query"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                elif block.type == "tool_use" and block.name == "search_web":
                    from backend.services import web_search
                    result = web_search.search(block.input["query"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                elif block.type == "tool_use" and block.name == "read_article":
                    from backend.services import web_search
                    result = web_search.read_article(block.input["url"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                else:
                    if block.type == "tool_use":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"erro": f"ferramenta desconhecida: {block.name}"}),
                        })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            for block in response.content:
                if hasattr(block, "text"):
                    return _validate_and_fix(block.text, data, client)
            return ""
