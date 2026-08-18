import re

# httpx.HTTPStatusError (e outras exceções de rede) carregam a URL completa da
# requisição em str(e) — e a SCRAPER_API_KEY vai no query string dela. Sem
# mascarar, a chave vaza para o tool_result devolvido ao Claude em reporter.py
# (gravado em conversation_history no Supabase), para respostas HTTP públicas
# dos coletores (`raise HTTPException(..., detail=str(e))`) e para o log do
# servidor (achado A1, revisão 18/08/2026; ampliado 18/08/2026 — a mesma URL
# aparece em collectors/market.py, esalq.py e investing_calendar.py).
_API_KEY_RE = re.compile(r"api_key=[^&\s]*")


def sanitize_error(e: Exception) -> str:
    """Mascara a SCRAPER_API_KEY antes de devolver str(e) ao chamador.

    Mora aqui — módulo neutro sem lógica de negócio — porque tanto `services`
    (web_search, agro_search) quanto `collectors` (market, esalq,
    investing_calendar) chamam o mesmo fornecedor (ScraperAPI) com a chave no
    query string. Um coletor importar de dentro de `web_search.py` (um serviço
    de ferramenta do Claude) seria o coletor dependendo de uma peça de nível
    mais alto por acidente de onde a função nasceu primeiro — inversão de
    camada sem motivo. Um módulo dedicado sem I/O e sem estado é a peça
    ortogonal certa: qualquer código pode depender dela sem herdar as
    dependências de `web_search` ou de qualquer coletor específico.

    Se um dia outro parâmetro precisar de máscara, o regex acima é o único
    lugar a mudar.
    """
    return _API_KEY_RE.sub("api_key=***", str(e))
