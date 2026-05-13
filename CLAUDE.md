# CLAUDE.md — Agente Notícias Finanças

## Visão Geral

Agente de IA especialista em finanças que coleta dados de mercado, notícias e indicadores econômicos diariamente e envia um resumo formatado ao usuário via WhatsApp. O usuário pode também conversar com o agente diretamente pelo WhatsApp.

PRD completo: [docs/PRD.md](docs/PRD.md)
Spec de design: [docs/superpowers/specs/2026-05-11-agente-financeiro-whatsapp-design.md](docs/superpowers/specs/2026-05-11-agente-financeiro-whatsapp-design.md)
Plano de implementação: [docs/superpowers/plans/2026-05-11-agente-financeiro-whatsapp.md](docs/superpowers/plans/2026-05-11-agente-financeiro-whatsapp.md)

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend principal | Python 3.12, FastAPI |
| IA | Claude API (`claude-sonnet-4-6`) via `anthropic` SDK |
| Dados de mercado | `yfinance` (bolsas, commodities, câmbio) |
| Cripto | CoinGecko API (sem chave) |
| Indicadores EUA | FRED API (`FRED_API_KEY`) |
| Indicadores BR | BCB (Banco Central, sem chave) |
| Notícias | NewsAPI (`NEWS_API_KEY`) |
| Mensageria | Evolution API v1.8.2 (WhatsApp, self-hosted na VPS Hostinger) |
| Banco de dados | Supabase (planejado para histórico futuro) |
| Frontend | Next.js, React, Tailwind CSS, TypeScript (planejado) |
| Automação | n8n (planejado) |
| Deploy | Vercel Serverless Functions |

---

## Estrutura de Pastas

```
c:\noticiasgg\
├── api/
│   └── webhook.py          # Orquestrador FastAPI — ponto de entrada do webhook WhatsApp
├── collectors/
│   ├── market.py           # Bolsas, commodities, câmbio (yfinance)
│   ├── crypto.py           # Criptomoedas (CoinGecko)
│   ├── indicators_us.py    # Indicadores EUA: CPI, PPI, desemprego (FRED)
│   ├── indicators_br.py    # Indicadores BR: SELIC, IPCA, câmbio (BCB)
│   └── news.py             # Notícias financeiras (NewsAPI)
├── services/
│   ├── reporter.py         # Geração de relatório via Claude API
│   └── whatsapp.py         # Envio de mensagens via Evolution API
├── tests/                  # 29 testes (pytest)
├── docs/
│   ├── PRD.md
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── .env                    # Variáveis de ambiente (NÃO commitar)
├── requirements.txt
├── vercel.json
└── CLAUDE.md
```

---

## Variáveis de Ambiente

| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Chave da API Claude (Anthropic) |
| `FRED_API_KEY` | Chave da API FRED (indicadores EUA) |
| `NEWS_API_KEY` | Chave da NewsAPI |
| `EVOLUTION_API_URL` | URL da Evolution API (`http://46.202.179.33:8080`) |
| `EVOLUTION_API_KEY` | Chave da Evolution API (`noticiasgg2026`) |
| `EVOLUTION_INSTANCE` | Nome da instância WhatsApp (`noticiasgg`) |
| `AUTHORIZED_NUMBER` | Número WhatsApp autorizado (`5534999945010`) |

Copiar `.env.example` para `.env` e preencher antes de rodar localmente.

---

## Convenções

- **Python:** snake_case para funções e variáveis, PascalCase para classes.
- **TypeScript/Next.js:** camelCase para variáveis/funções, PascalCase para componentes React.
- **Commits:** mensagens em inglês, imperativas (`Add collector for crypto data`).
- **Sem comentários desnecessários** — apenas quando o "porquê" não é óbvio.
- **Sem mock de banco em testes** — testes de integração usam APIs reais onde possível.
- **Sem features além do escopo** — YAGNI.

---

## Fluxo Principal

```
WhatsApp (usuário)
  → Evolution API webhook
    → api/webhook.py
      → collectors/* (dados em paralelo)
      → services/reporter.py (Claude gera resumo)
      → services/whatsapp.py (envia resposta)
  → WhatsApp (usuário recebe relatório)
```

---

## Estado Atual (2026-05-13)

| Task | Status |
|------|--------|
| Estrutura do projeto | ✅ |
| `collectors/market.py` | ✅ |
| `collectors/crypto.py` | ✅ |
| `collectors/indicators_us.py` | ✅ |
| `collectors/indicators_br.py` | ✅ |
| `collectors/news.py` | ✅ |
| `services/reporter.py` | ✅ |
| `services/whatsapp.py` | ✅ |
| `api/webhook.py` | ✅ |
| Conectar WhatsApp via QR code | ⏳ |
| Deploy na Vercel | ⏳ |

---

## Como Rodar Localmente

```bash
pip install -r requirements.txt
cp .env.example .env  # preencher variáveis
uvicorn api.webhook:app --reload
```

## Testes

```bash
pytest tests/ -v
```

## Deploy (Vercel)

```bash
npm i -g vercel
vercel login
vercel env add ANTHROPIC_API_KEY
# (repetir para todas as variáveis)
vercel --prod
```

Após o deploy, atualizar a URL do webhook na Evolution API para a URL da Vercel.
