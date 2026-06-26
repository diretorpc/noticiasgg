# Rotina Investing — Alertador de Calendário Econômico

**Data:** 2026-06-26
**Branch:** `feat/rotina-investing`
**Status:** Aprovado (design) — aguardando plano de implementação

## Objetivo

Cron de hora em hora que monitora o calendário econômico do
[br.investing.com/economic-calendar](https://br.investing.com/economic-calendar) e envia
uma mensagem no WhatsApp conforme os indicadores de **alto impacto** são divulgados (quando o
valor **Atual** aparece), para os usuários autorizados com alertas ligados.

### Formato da mensagem (fiel ao pedido do usuário)

```
📅 *Calendário Econômico — novos dados*
━━━━━━━━━━━━━━
🇪🇸 PIB da Espanha (trimestral) (Q1)
Anterior = 0,8%
Projeção = 0,6%
Atual = 0,6%
━━━━━━━━━━━━━━
🇺🇸 Payroll (Junho)
Anterior = 139K
Projeção = 185K
Atual = 206K
```

## Escopo (decidido com o usuário)

| Dimensão | Decisão |
|----------|---------|
| Frequência | Hora em hora, **24/7** (`0 * * * *`) |
| Relevância | Apenas **alto impacto** (3 touros/estrelas no Investing) |
| Países | **Todos** |
| Gatilho | Dispara quando o valor **Atual** é divulgado |
| Agrupamento | **Uma mensagem agrupada por ciclo** (blocos separados por divisória) |
| Aquisição | Página `/economic-calendar` via ScraperAPI; eventos extraídos do JSON `__NEXT_DATA__` (ver Atualização pós-spike) |
| Destinatários | `authorized_users` com `alerts_enabled=true` (mesmo dos outros alertas) |
| IA | **Nenhuma** — dado estruturado, formatação determinística |

### Por que 24/7 e não janelado

"Todos os países" inclui a Ásia, cujos dados de alto impacto saem fora do horário comercial
brasileiro (China ~22h–23h BRT, Austrália ~21h BRT, Japão de madrugada). Janelar o cron para
o dia BRT perderia esses releases. O custo de rodar 24/7 é controlado na estratégia de fetch
(modo barato primeiro), não cortando horas.

## Atualização pós-spike (2026-06-26)

O spike de aquisição revelou que o **br.investing.com migrou para Next.js**. A estrutura
antiga (`getCalendarFilteredData`, tabela `#economicCalendarData`, linhas `js-event-item`)
**não existe mais**. Decisões revisadas (mudança de mecanismo, não de escopo nem de saída):

- **Fetch:** GET da página `https://br.investing.com/economic-calendar/` via ScraperAPI
  (modo simples, sem `render`/`premium` — o SSR já entrega o conteúdo; retornou 200 com tudo).
- **Parse:** extrair o `<script id="__NEXT_DATA__">`, fazer `json.loads`, navegar até
  `props.pageProps.state.economicCalendarStore.calendarEventsByDate` (dict por data → lista de
  eventos). Cada evento já vem com campos limpos:
  `eventId` (int estável), `importance` (string `"1"|"2"|"3"`), `actual`/`forecast`/`previous`
  (strings cruas em PT), `event` + `period` (período já vem com parênteses, ex. `"(Mai)"`),
  `country` (nome PT) e `currencyFlag` (ISO-2, ex. `"BR"`, `"ES"`).
- **Flag emoji:** derivado de `currencyFlag` (ISO-2) por indicadores regionais
  (`chr(0x1F1E6 + ord(c) - ord('A'))`) — sem mapa de países, cobre todos.
- **Filtro:** `importance == "3"` **E** `actual` não-vazio.
- **Dedup id:** `eventId` (não mais hash do nome).
- **Sinal de saúde:** path do store ausente → falha (bloqueio/layout); store presente com 0
  eventos filtrados → vazio normal.
- **Custo confirmado:** GET simples basta (~1 crédito/chamada) → ~720 ScraperAPI/mês. O risco
  de modo premium não se materializou.

Validação real (2026-06-26): 51 eventos no dia, 3 de alta relevância, 2 já com `actual`.

O dict de evento produzido pelo `parse()` mantém as chaves
`event_id/country/flag_emoji/name/importance/previous/forecast/actual`, então as camadas de
formatação, dedup e envio abaixo não mudam.

## Arquitetura

Segue os padrões já existentes no repo (cron fino → service → collector; dedup via
`system_alert_state`; broadcast para `authorized_users`).

| Camada | Arquivo (novo) | Papel |
|--------|----------------|-------|
| Coletor | `backend/collectors/investing_calendar.py` | `fetch()` + `parse(html)` → lista de eventos |
| Serviço | `backend/services/investing_digest.py` | `run()`: dedup, monta msg, broadcast, notifica admin em falha |
| Rota cron | `backend/api/cron_investing.py` | `GET /api/cron/investing` → `check_cron_secret` → `run()` |
| Registro | `backend/api/main.py` | `app.include_router(cron_investing.router)` |
| Agendamento | `vercel.json` | `{ "path": "/api/cron/investing", "schedule": "0 * * * *" }` |

### Reuso

- `_get_recipients()` e `_broadcast()` de [`alert_checker.py`](../../../backend/services/alert_checker.py)
  são reutilizados (import direto).
- `notify_admin()` de `alert_checker.py` é **generalizado** para aceitar um parâmetro opcional
  `title` (default mantém o texto atual "check-alerts com falhas"), para a rotina investing
  enviar um título próprio. Mudança retrocompatível, ~4 linhas.

## Componentes

### `collectors/investing_calendar.py`

Responsabilidade única: buscar e parsear o calendário. Não conhece WhatsApp, Supabase nem dedup.

- **`fetch() -> str`**
  - POST via ScraperAPI ao endpoint `getCalendarFilteredData` do Investing, com filtros
    `importance=[3]`, `currentTab=today`, todos os países, timezone BRT, header
    `X-Requested-With: XMLHttpRequest`.
  - Estratégia de custo: tenta o modo barato do ScraperAPI primeiro; só escala para `premium`
    se bloqueado (mesmo padrão de [`market.py`](../../../backend/collectors/market.py)).
  - **Fallback**: se o POST falhar, faz GET da página `/economic-calendar` via ScraperAPI — o
    HTML de linha (`<tr>`) é o mesmo, então o parser não muda.
  - Retorna o HTML cru (fragmento ou página).

- **`parse(html: str) -> list[dict]`**
  - Extrai cada `<tr>` de evento da tabela `#economicCalendarData`.
  - Para cada linha: `{event_id, country_code, flag_emoji, name, period, previous, forecast, actual, importance}`.
  - `flag_emoji`: deriva o emoji de bandeira do código ISO do país (offset de indicadores
    regionais). País sem mapeamento → string vazia (não quebra).
  - **Filtros aplicados aqui (defensivo, mesmo com filtro do servidor):**
    `importance == 3` **E** `actual` não-vazio.
  - Valores (`previous`/`forecast`/`actual`) são mantidos como **strings cruas** do br.investing
    (já em PT, ex.: `"0,8%"`, `"139K"`) — nenhuma reformatação de locale.
  - **Sinal de saúde:** distinguir "tabela presente mas sem eventos de alto impacto com Atual"
    (retorna `[]` — normal) de "container `#economicCalendarData` ausente no HTML" (layout mudou
    → levanta exceção, tratada como falha pelo serviço).

### `services/investing_digest.py`

Orquestra o ciclo. Responsabilidade única: decidir o que é novo, formatar e enviar.

- **`run(test_mode: bool = False) -> dict`**
  1. `recipients = alert_checker._get_recipients()`. Se vazio → notifica admin, retorna cedo.
  2. `html = investing_calendar.fetch()`; `events = investing_calendar.parse(html)`.
     - Falha de fetch/parse → notifica admin com título próprio, retorna `{"status": "error", ...}`.
  3. Para cada evento, monta `rule_id = f"investing_{event_id}_{data_BRT}"`.
     - Pula se já enviado (presence-check via `supabase.get_alert_last_triggered`).
  4. Eventos novos → monta **uma mensagem agrupada** (header + blocos separados por `━━━`).
  5. `alert_checker._broadcast(msg, recipients, errors)`.
  6. Marca cada `rule_id` com `supabase.set_alert_triggered` **apenas se o broadcast entregou > 0**.
  7. Retorna `{"status": "ok"|"error", "recipients": N, "events": K, "sent": M}`.

- **`_format_event(event: dict) -> str`** — bloco de um indicador:
  ```
  🇪🇸 PIB da Espanha (trimestral) (Q1)
  Anterior = 0,8%
  Projeção = 0,6%
  Atual = 0,6%
  ```
  Linha omitida quando o campo correspondente vem vazio (ex.: sem projeção).

### `api/cron_investing.py`

Router fino, espelhando [`check_alerts.py`](../../../backend/api/check_alerts.py):

```python
@router.get("/api/cron/investing")
async def cron_investing(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        return investing_digest.run(test_mode=test)
    except Exception as e:
        logger.exception("cron_investing failed")
        try:
            alert_checker.notify_admin([f"fatal: {e}"], title="cron investing com falha")
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
```

## Dedup & estado

- Tabela existente `system_alert_state` (chave `rule_id`, `last_triggered_at`).
- `rule_id = f"investing_{event_id}_{data_BRT}"`. Como o `rule_id` embute a data, basta um
  **presence-check** (`get_alert_last_triggered(rule_id) is not None`) — sem janela de cooldown:
  **cada divulgação é enviada uma única vez**, mesmo o cron rodando de hora em hora.
- `data_BRT` = data de hoje no fuso BRT (UTC-3), consistente com o resto do app.

## Tratamento de erro (anti-falha-silenciosa)

| Situação | Comportamento |
|----------|---------------|
| Fetch falhou (ScraperAPI/Cloudflare) | Notifica admin, retorna `error`, **não envia nada** |
| HTML voltou mas container da tabela ausente | **Falha de layout** → notifica admin (não "nada novo") |
| Tabela presente, 0 eventos de alto impacto com Atual | Normal → retorna `ok`, `sent=0`, silêncio |
| Broadcast entregou 0/N | Adiciona a `errors`, **não marca** `rule_id` (re-tenta no próximo ciclo) |

(Opcional / follow-up) Plugar uma sonda da rotina investing no `health.collect_status` para o
boletim diário da Camada 1 detectar quebra silenciosa.

## Testes (pytest, sem mock de dados externos)

- **`parse()` contra fixture** — resposta real do `getCalendarFilteredData` salva em
  `backend/tests/fixtures/` (gerada no spike da Task 1). Teste determinístico, é o núcleo.
  Cobre: filtro de importância, filtro de Atual preenchido, derivação de flag, omissão de
  campo vazio, e o sinal de "container ausente" levantando exceção.
- **`_format_event()` e geração de `rule_id`** — funções puras, testes diretos.
- **Integração** hitando ScraperAPI+Investing — `skipif` sem `SCRAPER_API_KEY` (padrão de
  [`test_agro_search.py`](../../../backend/tests/test_agro_search.py)).
- **`?test=true`** no endpoint para validação manual end-to-end (busca + formata; marca a msg
  com `[TESTE]`).

## Riscos & mitigações

| Risco | Mitigação |
|-------|-----------|
| Cloudflare exige modo premium (10–25× créditos) → ~7k–18k ScraperAPI/mês | Fetch barato-primeiro; alertar se cair sempre no premium; reavaliar plano |
| Investing muda o endpoint/layout → parser quebra silenciosamente | Sonda de "container ausente"; notifica admin; fixture de teste detecta na CI |
| Endpoint `getCalendarFilteredData` indisponível/parâmetros mudam | Fallback automático para GET da página completa (mesmo parser) |
| Latência de até 1h entre release e mensagem | Aceito pelo usuário (rotina é boletim, não tempo real) |

## Plano de tasks (alto nível — detalhar no writing-plans)

1. **Spike de aquisição**: buscar 1 resposta real do `getCalendarFilteredData` via ScraperAPI,
   confirmar parâmetros, salvar como fixture de teste.
2. Generalizar `notify_admin(title=...)` em `alert_checker.py`.
3. `collectors/investing_calendar.py` — `parse()` (TDD contra fixture) + `fetch()`.
4. `services/investing_digest.py` — `run()`, dedup, formatação, broadcast.
5. `api/cron_investing.py` + registro em `main.py` + cron em `vercel.json`.
6. Validação manual via `?test=true` em produção e ajuste fino.
7. (Opcional) sonda no `health.collect_status`.

## Fora de escopo (YAGNI)

- Toggle/config no painel admin (threshold fica como constante no código).
- Indicadores de média/baixa relevância.
- Filtro por país específico.
- Histórico/persistência dos valores divulgados além do dedup.
