"""Mede a vazão de alertas de notícia — read-only, não envia nem grava nada.

Responde as duas perguntas que decidem o freio do volume:
  1. Quantos alertas/dia estão saindo de fato? (lê `sent_news`)
  2. Como as notas se distribuem com o mix de fontes atual? (classifica de verdade)

A parte (2) replica o caminho do `alert_checker._check_news` — mesmo modelo, mesmo
`_NEWS_CLASSIFIER_SYSTEM`, mesmo `_build_classifier_input`, mesmo snapshot de mercado.
Custa alguns centavos de Haiku por rodada.

Contexto: em 12/08/2026 o volume saltou de ~5,4 para 64 alertas/dia quando as 20
fontes novas entraram. Os parafusos são `_NEWS_MIN_SCORE` e
`_NEWS_GLOBAL_COOLDOWN_HOURS`, em `backend/services/alert_checker.py`.

⚠️ Amostra de uma rodada é base frágil para extrapolar o dia — a distribuição de
notas varia com a hora e com o noticiário. Rode algumas vezes antes de concluir.

Uso:  python -m backend.tools.medir_volume_alertas
      python -m backend.tools.medir_volume_alertas --dias 14 --sem-classificar
"""
import argparse
import datetime
import json
import os
from collections import Counter

from anthropic import Anthropic

from backend.collectors import market, news
from backend.services import alert_checker, supabase

_BRT = datetime.timezone(datetime.timedelta(hours=-3))


def vazao(dias: int) -> None:
    corte = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=dias)).isoformat()
    with supabase._client() as c:
        r = c.get(f"/sent_news?select=title,sent_at&title=not.is.null"
                  f"&sent_at=gte.{supabase._f(corte)}&order=sent_at.desc&limit=2000")
        r.raise_for_status()
        rows = r.json()

    por_dia: Counter = Counter()
    for x in rows:
        d = datetime.datetime.fromisoformat(x["sent_at"].replace("Z", "+00:00"))
        por_dia[d.astimezone(_BRT).strftime("%Y-%m-%d")] += 1

    print(f"ALERTAS ENVIADOS POR DIA (fuso de Brasília, {dias} dias)")
    for dia in sorted(por_dia):
        n = por_dia[dia]
        print(f"  {dia}  {n:3}  {'#' * min(n, 60)}")
    if por_dia:
        print(f"  média: {sum(por_dia.values()) / len(por_dia):.1f}/dia")


def notas() -> None:
    artigos = news.collect(include_ai=False, include_newsapi=True)
    try:
        recentes = supabase.get_recent_sent_titles()
    except Exception:
        recentes = []
    snapshot = alert_checker._market_snapshot(market.collect())
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    vivos = []
    for a in artigos[:alert_checker._NEWS_SCAN_CAP]:
        if not (a.get("titulo") or ""):
            continue
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=alert_checker._NEWS_CLASSIFIER_SYSTEM,
                messages=[{"role": "user", "content": alert_checker._build_classifier_input(
                    a, snapshot, recentes)}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                raw = raw[4:] if raw.startswith("json") else raw
                raw = raw.strip()
            r = json.loads(raw)
        except Exception as e:
            print(f"  falhou: {a['titulo'][:50]} -> {type(e).__name__}")
            continue
        if not r.get("duplicada"):
            vivos.append(r)

    print(f"\nDISTRIBUIÇÃO DE NOTAS ({len(vivos)} não-duplicadas)")
    c = Counter(x.get("score", 0) for x in vivos)
    for nota in sorted(c, reverse=True):
        print(f"  nota {nota}: {c[nota]:2} {'#' * c[nota]}")

    print(f"\nQUANTAS PASSARIAM (corte de hoje: {alert_checker._NEWS_MIN_SCORE})")
    for corte in range(3, 9):
        n = len([x for x in vivos if x.get("score", 0) >= corte])
        marca = "  <- em uso" if corte == alert_checker._NEWS_MIN_SCORE else ""
        print(f"  nota >= {corte}: {n:2} de {len(vivos)}{marca}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dias", type=int, default=14)
    p.add_argument("--sem-classificar", action="store_true",
                   help="pula a parte que gasta API")
    args = p.parse_args()
    vazao(args.dias)
    if not args.sem_classificar:
        notas()
