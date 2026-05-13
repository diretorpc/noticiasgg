# PRD — Agente Notícias Finanças

## 1. Contexto e Problema

Hoje em dia, é essencial ficarmos por dentro de tudo o que acontece no mundo financeiro.
O problema é que isso demanda muito tempo: ficar entrando de site em site lendo notícias, vendo indicadores, valor da bolsa, commodities e etc. Além de tomar muito tempo, a quantidade de informações recebidas é excessiva, tornando quase impossível assimilar tudo de uma vez — sendo necessário fazer um resumo do que foi lido.

## 2. Solução Proposta

Construir um agente especialista em finanças que faça essa pesquisa diária no mundo financeiro, coletando as informações mais importantes e impactantes e, depois que coletar tudo, enviar um resumo ao usuário.

### Habilidades do Agente

- Pesquisa em vários sites (pequenos e grandes) para coletar o máximo de informação possível.
- Criar um resumo equilibrado — nem muito grande nem muito pequeno — mas o mais detalhado possível para que o usuário visualize todas as informações em uma breve apresentação.
- Capacidade de criar sub-agentes quando necessário.
- Não pesquisar em blogs ou páginas consideradas "FAKE", evitando extrair notícias falsas.

## 3. Requisitos Funcionais

### Integrações (API)
- API principalmente em buscas na web e dados financeiros em tempo real.

### Relatórios e Exportação
- O agente pode enviar os relatórios em outros formatos: PDF, WORD, ou o tipo que o usuário precisar.
- Pode criar gráficos de dados de períodos diferentes.

### Chat / Mensagens
- Possibilidade de conversar e interagir com o próprio agente financeiro via WhatsApp.

### Busca e Filtros
- Filtros por tema, período, tipo de ativo ou região geográfica.

## 4. Personas de Usuário

Apenas 1 usuário (uso pessoal).

## 5. Stack Técnica

| Camada | Tecnologia |
|--------|-----------|
| Frontend | Next.js, React, Tailwind CSS, TypeScript |
| Backend / API | Python (FastAPI), Vercel Serverless |
| IA | Claude API (Anthropic) |
| Dados de Mercado | yfinance, CoinGecko, FRED API, BCB |
| Notícias | NewsAPI |
| Mensageria | Evolution API (WhatsApp) |
| Banco de dados | Supabase |
| Automação | n8n |
| Infraestrutura | Vercel, VPS Hostinger |

## 6. Design

A ser definido — sem restrições de design informadas.

## 7. Processo de Desenvolvimento

- Dividir o build em marcos lógicos (milestones) — cada um é um incremento entregável.
- Priorizar funcionalidade core primeiro, depois iterar.
- Testar cada milestone antes de avançar.
