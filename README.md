# noticiasgg — WhatsApp Financial Agent

AI agent that collects market data, economic indicators, and news daily and sends a
financial summary over WhatsApp. Orchestrated with n8n.cloud.

## Architecture

```
WhatsApp (user)
  → Evolution API (Hostinger VPS)
    → n8n.cloud (orchestration)
      → Python collectors (Vercel) — data in parallel
      → Claude API — report generation
      → Evolution API — sending the reply
  → WhatsApp (user receives the summary)
```

## Stack

- **Orchestration:** n8n.cloud
- **Collectors:** Python 3.12 + FastAPI (Vercel Serverless)
- **AI:** Claude API (`claude-sonnet-4-6`)
- **WhatsApp:** Evolution API v1.8.2 (self-hosted)
- **Data:** yfinance, CoinGecko, FRED API, BCB, NewsAPI

## Local setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

cp ../.env.example ../.env     # fill in the variables
uvicorn backend.api.main:app --reload
```

Open `http://localhost:8000/api/health` to confirm it's up.

## Environment variables

Copy `.env.example` to `.env` and fill it in:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API |
| `FRED_API_KEY` | FRED (US indicators) |
| `NEWS_API_KEY` | NewsAPI |
| `EVOLUTION_API_URL` | Evolution API URL |
| `EVOLUTION_API_KEY` | Evolution API key |
| `EVOLUTION_INSTANCE` | WhatsApp instance name |
| `AUTHORIZED_NUMBER` | Authorized number (country+area+number) |

## Tests

```bash
cd backend
pytest tests/ -v
```

## Deploy

```bash
npm i -g vercel
vercel login
vercel env add ANTHROPIC_API_KEY   # repeat for every variable
vercel --prod
```

## n8n workflows

Exported workflows are in `docs/n8n/`. Import them into n8n.cloud and update the
collector URLs to the production Vercel URL.

## Milestones

See [docs/PLAN.md](docs/PLAN.md).

---

## Credits

Built by [Matheus Dib Mouro](https://www.linkedin.com/in/matheus-dib-26b458160/) — AI Automation Developer (Serafim IA).
