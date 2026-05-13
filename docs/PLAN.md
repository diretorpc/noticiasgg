# PLAN.md — Agente Notícias Finanças

> Plano de execução — fase 1: fluxo WhatsApp completo.
> Frontend (dashboard) será implementado em fase futura separada.
>
> **Stack desta fase:**
> - n8n.cloud — orquestração do fluxo
> - Python/FastAPI na Vercel — microserviços de coleta de dados
> - Evolution API na VPS — bridge com o WhatsApp

---

## Visão Geral dos Milestones

| # | Milestone | Branch | Foco |
|---|-----------|--------|------|
| 1 | Setup & Fundação | `milestone/1-setup` | Estrutura do projeto, config, variáveis |
| 2 | Collectors | `milestone/2-collectors` | Microserviços HTTP de coleta de dados |
| 3 | n8n — Workflow Relatório | `milestone/3-n8n-report` | WhatsApp → collectors → Claude → resposta |
| 4 | n8n — Workflow Chat | `milestone/4-n8n-chat` | Chat conversacional com memória |
| 5 | Exportação | `milestone/5-export` | PDF e Word enviados pelo WhatsApp |
| 6 | Deploy & Go Live | `milestone/6-deploy` | Vercel prod + QR code WhatsApp + smoke tests |

---

## Milestone 1 — Setup & Fundação

**Branch:** `milestone/1-setup`
**Objetivo:** Criar a estrutura do projeto, configurar variáveis de ambiente e garantir que o ambiente local sobe sem erro.

### Entregas

- [ ] Inicializar repositório Git com `.gitignore` (`.env`, `__pycache__`, `.vercel`)
- [ ] Criar estrutura de pastas:
  ```
  /
  ├── backend/
  │   ├── collectors/    # Um arquivo por fonte de dados
  │   ├── services/      # Export PDF/Word
  │   ├── api/           # Entrypoint FastAPI
  │   └── tests/
  ├── docs/
  │   └── n8n/           # Workflows exportados como JSON
  └── README.md
  ```
- [ ] Configurar `backend/requirements.txt`
- [ ] Criar `.env.example` com todas as variáveis (sem valores reais)
- [ ] Criar `vercel.json` para deploy dos collectors como Serverless Functions
- [ ] Confirmar que `uvicorn backend/api/main:app --reload` sobe sem erro

**Commit final:** `chore: project scaffold with FastAPI collectors structure`

---

## Milestone 2 — Collectors

**Branch:** `milestone/2-collectors`
**Objetivo:** Implementar os microserviços de coleta de dados, cada um expondo um endpoint HTTP que o n8n chamará em paralelo.

### Arquitetura

```
n8n (HTTP Request nodes em paralelo)
  → GET /api/collectors/market
  → GET /api/collectors/crypto
  → GET /api/collectors/indicators-us
  → GET /api/collectors/indicators-br
  → GET /api/collectors/news
```

Todos retornam `{ data: {...}, collected_at: "ISO8601" }`.

### Entregas

- [ ] `collectors/market.py` + `GET /api/collectors/market`
  - Bolsas: IBOVESPA, S&P 500, NASDAQ, Dow Jones
  - Câmbio: USD/BRL, EUR/BRL
  - Commodities: Ouro, Petróleo, Soja
  - Fonte: `yfinance`
- [ ] `collectors/crypto.py` + `GET /api/collectors/crypto`
  - Top 10 criptos por market cap
  - Fonte: CoinGecko (sem chave)
- [ ] `collectors/indicators_us.py` + `GET /api/collectors/indicators-us`
  - CPI, PPI, taxa de desemprego
  - Fonte: FRED API (`FRED_API_KEY`)
- [ ] `collectors/indicators_br.py` + `GET /api/collectors/indicators-br`
  - SELIC, IPCA
  - Fonte: BCB (API pública, sem chave)
- [ ] `collectors/news.py` + `GET /api/collectors/news`
  - Notícias financeiras em PT e EN
  - Fonte: NewsAPI (`NEWS_API_KEY`)
  - Allowlist de fontes: Reuters, Bloomberg, G1, Valor Econômico, InfoMoney, Exame, WSJ, Financial Times
- [ ] Testes: mínimo 3 testes por collector (`pytest backend/tests/ -v`)

**Commit final:** `feat: all collector microservices with HTTP endpoints and tests`

---

## Milestone 3 — n8n: Workflow Relatório

**Branch:** `milestone/3-n8n-report`
**Objetivo:** Montar no n8n.cloud o workflow principal — recebe mensagem do WhatsApp, coleta todos os dados em paralelo, gera relatório com Claude e responde.

### Fluxo

```
[Webhook Trigger — Evolution API]
  → [IF] número autorizado?
      → NÃO: encerrar sem resposta
      → SIM:
          → [Parallel] GET /api/collectors/market
          → [Parallel] GET /api/collectors/crypto
          → [Parallel] GET /api/collectors/indicators-us
          → [Parallel] GET /api/collectors/indicators-br
          → [Parallel] GET /api/collectors/news
          → [Merge] consolidar todos os dados
          → [AI Agent — Claude] gerar relatório financeiro
          → [IF] resposta > 3500 chars? → split em chunks
          → [HTTP Request] Evolution API → sendText
```

### Entregas

- [ ] Nó Webhook Trigger configurado (URL para usar na Evolution API)
- [ ] Nó IF validando `AUTHORIZED_NUMBER`
- [ ] 5 nós HTTP Request em paralelo (um por collector)
- [ ] Nó Merge consolidando os JSONs
- [ ] Nó AI Agent (Claude `claude-sonnet-4-6`) com system prompt:
  - Agente financeiro especialista
  - Resumo objetivo e equilibrado
  - Sem mencionar fontes fake ou blogs sem credibilidade
  - Formato: seções claras (Bolsas | Cripto | Indicadores BR | Indicadores EUA | Notícias)
  - Máximo 3500 caracteres
- [ ] Nó de split automático para mensagens longas (chunks de 3500 chars)
- [ ] Nó HTTP Request enviando resposta via Evolution API (`POST /message/sendText/noticiasgg`)
- [ ] Testar end-to-end localmente com ngrok: enviar "relatório" no WhatsApp e receber resumo
- [ ] Exportar workflow como `docs/n8n/workflow-report.json`

**Commit final:** `feat: n8n report workflow exported to docs/n8n/workflow-report.json`

---

## Milestone 4 — n8n: Workflow Chat

**Branch:** `milestone/4-n8n-chat`
**Objetivo:** Workflow de chat conversacional — o usuário pode fazer perguntas livres ao agente e o contexto da conversa é mantido entre mensagens.

### Fluxo

```
[Webhook Trigger — mesma URL do M3]
  → [IF] mensagem contém palavra-chave de relatório?
      → SIM: sub-workflow M3 (relatório completo)
      → NÃO: chat livre
          → [Memory] carregar histórico (key = número WhatsApp)
          → [AI Agent — Claude] responder com contexto do histórico
          → [Memory] salvar mensagem + resposta (máx 20 mensagens)
          → [HTTP Request] Evolution API → sendText
```

### Entregas

- [ ] Nó de roteamento: palavras-chave que disparam relatório completo (`relatório`, `mercado hoje`, `resumo`, `bolsa`)
- [ ] Integrar sub-workflow do M3 via nó "Execute Workflow"
- [ ] Nó Simple Memory com key baseada no número do WhatsApp
- [ ] Nó AI Agent com system prompt de assistente financeiro conversacional
- [ ] Limite de histórico: 20 mensagens por sessão
- [ ] Comando `limpar histórico` apaga a memória da sessão
- [ ] Exportar workflow unificado como `docs/n8n/workflow-main.json`
- [ ] Testar: conversa de múltiplos turnos com contexto preservado

**Commit final:** `feat: n8n chat workflow with session memory exported to docs/n8n/`

---

## Milestone 5 — Exportação

**Branch:** `milestone/5-export`
**Objetivo:** Permitir que o usuário peça o relatório em PDF ou Word diretamente pelo WhatsApp.

### Fluxo

```
Usuário: "relatório pdf"
  → n8n detecta intenção de export
  → collectors → Claude → relatório em texto
  → POST /api/export { format: "pdf" }
  → Evolution API → sendDocument (arquivo anexado no WhatsApp)
```

### Entregas

- [ ] `services/exporter.py` — geração de PDF via `reportlab`
- [ ] `services/exporter.py` — geração de Word via `python-docx`
- [ ] Endpoint `POST /api/export` — recebe `{ content: string, format: "pdf"|"docx" }` e retorna o arquivo em base64
- [ ] n8n: nó de detecção de intenção de export (`relatório pdf`, `relatório word`, `relatório doc`)
- [ ] n8n: nó HTTP chamando `POST /api/export`
- [ ] n8n: nó Evolution API `sendDocument` com o arquivo gerado
- [ ] Testes: geração de PDF e Word com conteúdo real

**Commit final:** `feat: PDF and Word export via WhatsApp command`

---

## Milestone 6 — Deploy & Go Live

**Branch:** `milestone/6-deploy`
**Objetivo:** Deploy dos collectors na Vercel, WhatsApp conectado via QR code, workflows n8n apontando para produção.

### Entregas

- [ ] **WhatsApp — conectar via QR code:**
  - [ ] Na VPS: `curl http://localhost:8080/instance/connect/noticiasgg -H "apikey: noticiasgg2026"`
  - [ ] Salvar QR code em `/tmp/qr.png` e baixar pelo File Manager do Hostinger
  - [ ] Escanear com o WhatsApp
  - [ ] Verificar: `GET http://46.202.179.33:8080/instance/connectionState/noticiasgg` → `"open"`

- [ ] **Deploy Vercel (collectors):**
  - [ ] `npm i -g vercel && vercel login`
  - [ ] `vercel` (primeiro deploy)
  - [ ] Adicionar variáveis: `vercel env add` para cada variável do `.env`
  - [ ] `vercel --prod`
  - [ ] Confirmar que `https://<projeto>.vercel.app/api/collectors/market` responde

- [ ] **Atualizar n8n para produção:**
  - [ ] Substituir URLs `localhost` pela URL da Vercel em todos os nós HTTP dos workflows
  - [ ] Reexportar workflows atualizados em `docs/n8n/`

- [ ] **Configurar webhook Evolution API → n8n:**
  - [ ] Copiar URL do webhook do n8n.cloud
  - [ ] `PATCH http://46.202.179.33:8080/webhook/set/noticiasgg` com a URL do n8n

- [ ] **Smoke tests em produção:**
  - [ ] "oi" no WhatsApp → agente responde com saudação
  - [ ] "relatório" → resumo financeiro completo recebido
  - [ ] "relatório pdf" → arquivo PDF recebido no WhatsApp
  - [ ] "o que é SELIC?" → resposta contextualizada (chat livre)
  - [ ] "limpar histórico" → confirmação de memória limpa

- [ ] Documentar URL de produção e URL do webhook n8n no `CLAUDE.md`

**Commit final:** `chore: production deployment complete, all smoke tests passing`

---

## Dependências entre Milestones

```
M1 (Setup)
  └── M2 (Collectors)
        ├── M3 (n8n Relatório)  ← precisa dos collectors rodando (ngrok local ou Vercel)
        │     └── M4 (n8n Chat) ← estende o M3
        │           └── M5 (Export)
        │                 └── M6 (Deploy)
        └── (endpoints também usados direto no M6)
```

---

## Fase Futura — Dashboard Web

Quando o fluxo WhatsApp estiver estável, adicionar:

- **M7** — Setup Next.js + Tailwind
- **M8** — Dashboard com cards de dados de mercado
- **M9** — Tela de chat no browser
- **M10** — Tela de relatórios com gráficos e exportação
- **M11** — Integração frontend ↔ collectors + n8n

---

## Checklist de Definition of Done

Antes de considerar um milestone concluído:

- [ ] Todos os checkboxes marcados
- [ ] Testes Python passando: `pytest backend/tests/ -v`
- [ ] Sem `print` de debug esquecidos
- [ ] Workflows n8n exportados como JSON em `docs/n8n/`
- [ ] Commit final criado
- [ ] Branch mergeada em `main`
