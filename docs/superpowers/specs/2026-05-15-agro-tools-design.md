# Design: Agro Tools — Consulta On-Demand de Dados do Agronegócio

**Data:** 2026-05-15  
**Branch:** feature/agro-tools  
**Status:** Aprovado para implementação

---

## Contexto

O agente financeiro WhatsApp já responde perguntas sobre ações, câmbio e indicadores macro. O objetivo desta feature é capacitar o agente a responder **qualquer pergunta relacionada ao agronegócio brasileiro** — preços de commodities, insumos, fertilizantes, defensivos agrícolas, gado, e qualquer outro dado do setor — usando tools do Claude invocadas sob demanda, sem alterar os relatórios automáticos do n8n.

---

## Abordagem: Opção C — Ferramentas específicas + busca web como fallback

Duas novas tools registradas no Claude em `reporter.py`:

1. **`get_agro_data`** — dados estruturados e confiáveis para as categorias mais consultadas
2. **`search_agro_web`** — busca web via ScraperAPI como fallback para qualquer coisa não coberta

---

## Arquitetura

```
Usuário: "qual o preço da ureia hoje?"
  → Claude detecta intenção agro
    → chama get_agro_data(categoria="fertilizantes")
      → agro_br.py coleta CEPEA/AgroLink
    → Claude formula resposta com os dados

Usuário: "qual o preço de arrendamento em MT?"
  → Claude detecta que não tem ferramenta específica
    → chama search_agro_web(query="preço arrendamento terra Mato Grosso 2026")
      → ScraperAPI busca no Google → retorna snippets
    → Claude formula resposta
```

---

## Novos Arquivos

### `backend/collectors/agro_br.py`

Collector estruturado com cinco categorias:

#### `commodities_cbot` — Futuros internacionais (Yahoo Finance)

| Símbolo | Commodity | Unidade |
|---------|-----------|---------|
| ZS=F | Soja | USc/bushel |
| ZM=F | Farelo de Soja | USD/ton |
| ZL=F | Óleo de Soja | USc/lb |
| ZC=F | Milho | USc/bushel |
| ZW=F | Trigo | USc/bushel |
| CT=F | Algodão | USc/lb |
| KC=F | Café Arábica | USc/lb |
| SB=F | Açúcar | USc/lb |
| CC=F | Cacau | USD/ton |
| OJ=F | Suco de Laranja | USc/lb |
| GF=F | Boi Gordo (feeder) | USD/cwt |
| LE=F | Boi Vivo (live) | USD/cwt |
| LH=F | Suíno | USD/cwt |
| ZO=F | Aveia | USc/bushel |
| ZR=F | Arroz | USD/cwt |

#### `commodities_br` — Preços físicos BR (Notícias Agrícolas / CEPEA)

| Commodity | URL path |
|-----------|----------|
| Soja | /cotacoes/soja |
| Milho | /cotacoes/milho |
| Trigo | /cotacoes/trigo |
| Café Arábica | /cotacoes/cafe |
| Algodão | /cotacoes/algodao |
| Açúcar Cristal | /cotacoes/sucroenergetico |
| Arroz | /cotacoes/arroz |
| Feijão | /cotacoes/feijao |
| Sorgo | /cotacoes/sorgo |
| Mandioca | /cotacoes/mandioca |
| Amendoim | /cotacoes/amendoim |
| Laranja | /cotacoes/citros |
| Aveia | /cotacoes/aveia |
| Cevada | /cotacoes/cevada |
| Canola | /cotacoes/canola |
| Girassol | /cotacoes/girassol |

#### `gado` — Pecuária (Notícias Agrícolas / CEPEA)

| Produto | URL path |
|---------|----------|
| Boi Gordo | /cotacoes/boi-gordo |
| Bezerro | /cotacoes/bezerro |
| Vaca Gorda | /cotacoes/vaca-gorda |
| Frango | /cotacoes/frango |
| Suíno | /cotacoes/suinos |
| Leite | /cotacoes/leite |
| Ovos | /cotacoes/ovos |

#### `fertilizantes` — Insumos (Notícias Agrícolas / CEPEA)

| Produto | URL path |
|---------|----------|
| Ureia | /cotacoes/ureia |
| MAP | /cotacoes/map |
| KCl (Cloreto de Potássio) | /cotacoes/kcl |
| Diesel | ANP (média nacional semanal) |

#### `defensivos` — Defensivos Agrícolas (AgroLink / CEPEA)

| Produto | Categoria |
|---------|-----------|
| Glifosato | Herbicida |

> **Nota:** Glifosato é o único com cotação pública confiável e diária. Os demais defensivos (fungicidas, inseticidas) variam muito por fornecedor e região — cobertos pelo fallback `search_agro_web`.

---

### `backend/services/agro_search.py`

Serviço de busca web via ScraperAPI para fallback.

- Recebe `query: str` em linguagem natural
- Monta URL: `https://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url=https://www.google.com/search?q={query_encoded}&num=5`
- Parseia snippets dos resultados com BeautifulSoup
- Retorna lista de snippets com título + texto para o Claude usar como contexto
- Timeout: 20s
- Em caso de falha: retorna `{"erro": "busca indisponível"}`

---

## Arquivos Alterados

### `backend/services/reporter.py`

**Novas tools registradas:**

```python
_AGRO_DATA_TOOL = {
    "name": "get_agro_data",
    "description": "Busca dados de commodities agrícolas, insumos, fertilizantes, defensivos e pecuária. ...",
    "input_schema": {
        "type": "object",
        "properties": {
            "categoria": {
                "type": "string",
                "enum": ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"]
            }
        },
        "required": ["categoria"]
    }
}

_AGRO_SEARCH_TOOL = {
    "name": "search_agro_web",
    "description": "Busca web para qualquer dado do agronegócio não coberto pelas categorias estruturadas...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    }
}
```

**System prompt atualizado** (`_SYSTEM_CHAT` e `_SYSTEM_MARKET`): instrução para usar `get_agro_data` ou `search_agro_web` em qualquer pergunta sobre agronegócio, preços de insumos, commodities agrícolas, pecuária, fertilizantes, defensivos, terras, maquinários ou safra.

**Loop de tool use** em `generate_response()`: já existe para `get_stock_data` — expandir para lidar com as duas novas tools.

---

## O que NÃO muda

- Relatórios automáticos do n8n — nenhum node é tocado
- `commodities_br.py` existente — mantido como está (usado nos relatórios)
- Nenhuma nova seção no relatório diário
- Nenhuma variável de ambiente nova (usa `SCRAPER_API_KEY` já existente)

---

## Restrições e Limitações

| Limitação | Impacto |
|-----------|---------|
| Notícias Agrícolas pode mudar estrutura HTML | Scraping pode quebrar por commodity — falha silenciosa por item |
| Glifosato é o único defensivo estruturado | Demais defensivos via busca web (menos preciso) |
| Terras e maquinários sem fonte diária | Cobertos via `search_agro_web` |
| ScraperAPI tem cota mensal | Busca web só acionada quando `get_agro_data` não cobre |

---

## Critérios de Sucesso

1. Usuário pergunta "qual o preço da soja hoje?" → agente retorna preço BR (CEPEA) e futuro CBOT
2. Usuário pergunta "como está a ureia?" → agente retorna cotação estruturada
3. Usuário pergunta "qual o preço de arrendamento em Mato Grosso?" → agente busca na web e responde
4. Usuário pergunta "qual a estimativa de safra de milho da CONAB?" → agente busca na web e responde
5. Nenhum relatório automático é afetado
