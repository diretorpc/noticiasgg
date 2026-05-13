# noticiasgg — Agente Financeiro WhatsApp

Agente de IA que coleta dados de mercado, indicadores econômicos e notícias diariamente e envia um resumo financeiro pelo WhatsApp. Orquestrado pelo n8n.cloud.

## Arquitetura

```
WhatsApp (usuário)
  → Evolution API (VPS Hostinger)
    → n8n.cloud (orquestração)
      → Collectors Python (Vercel) — dados em paralelo
      → Claude API — geração do relatório
      → Evolution API — envio da resposta
  → WhatsApp (usuário recebe o resumo)
```

## Stack

- **Orquestração:** n8n.cloud
- **Collectors:** Python 3.12 + FastAPI (Vercel Serverless)
- **IA:** Claude API (`claude-sonnet-4-6`)
- **WhatsApp:** Evolution API v1.8.2 (self-hosted)
- **Dados:** yfinance, CoinGecko, FRED API, BCB, NewsAPI

## Setup local

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

cp ../.env.example ../.env    # preencher variáveis
uvicorn backend.api.main:app --reload
```

Acesse `http://localhost:8000/api/health` para confirmar que subiu.

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Claude API |
| `FRED_API_KEY` | FRED (indicadores EUA) |
| `NEWS_API_KEY` | NewsAPI |
| `EVOLUTION_API_URL` | URL da Evolution API |
| `EVOLUTION_API_KEY` | Chave da Evolution API |
| `EVOLUTION_INSTANCE` | Nome da instância WhatsApp |
| `AUTHORIZED_NUMBER` | Número autorizado (DDI+DDD+número) |

## Testes

```bash
cd backend
pytest tests/ -v
```

## Deploy

```bash
npm i -g vercel
vercel login
vercel env add ANTHROPIC_API_KEY   # repetir para todas as variáveis
vercel --prod
```

## Workflows n8n

Os workflows exportados estão em `docs/n8n/`. Importe-os no n8n.cloud e atualize as URLs dos collectors para a URL de produção da Vercel.

## Milestones

Ver [docs/PLAN.md](docs/PLAN.md).
