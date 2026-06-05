from dataclasses import dataclass


@dataclass
class AlertRule:
    rule_id: str
    label: str
    emoji: str
    collector: str        # 'market' | 'crypto' | 'commodities_br' | 'esalq'
    data_path: list[str]  # caminho até o ativo no output do collector
    value_type: str       # 'price' | 'change_pct'
    condition: str        # 'above' | 'below'
    threshold: float
    unit: str
    cooldown_hours: int = 4


RULES: list[AlertRule] = [
    # ── Câmbio ──────────────────────────────────────────────────────────────────
    AlertRule("usd_brl_spike_up",   "Dólar disparou",              "🚨", "market", ["cambio", "USD/BRL"], "change_pct", "above",  1.5,  "%"),
    AlertRule("usd_brl_spike_down", "Dólar recuou forte",          "💚", "market", ["cambio", "USD/BRL"], "change_pct", "below", -1.5,  "%"),
    AlertRule("usd_brl_above_600",  "Dólar ultrapassou R$6,00",    "🔴", "market", ["cambio", "USD/BRL"], "price",      "above",  6.00, "R$"),
    AlertRule("usd_brl_above_580",  "Dólar acima de R$5,80",       "⚠️", "market", ["cambio", "USD/BRL"], "price",      "above",  5.80, "R$"),
    AlertRule("usd_brl_below_520",  "Dólar caiu abaixo de R$5,20", "💪", "market", ["cambio", "USD/BRL"], "price",      "below",  5.20, "R$"),

    # ── Bolsas ──────────────────────────────────────────────────────────────────
    AlertRule("ibov_drop",   "Ibovespa em queda forte", "📉", "market", ["bolsas", "IBOVESPA"], "change_pct", "below", -1.5, "%"),
    AlertRule("ibov_rally",  "Ibovespa em alta forte",  "📈", "market", ["bolsas", "IBOVESPA"], "change_pct", "above",  1.5, "%"),
    AlertRule("sp500_drop",  "S&P 500 em queda forte",  "📉", "market", ["bolsas", "S&P 500"],  "change_pct", "below", -1.5, "%"),
    AlertRule("sp500_rally", "S&P 500 em alta forte",   "📈", "market", ["bolsas", "S&P 500"],  "change_pct", "above",  1.5, "%"),

    # ── Cripto ──────────────────────────────────────────────────────────────────
    AlertRule("btc_drop",   "Bitcoin despencou", "₿", "crypto", ["BTC"], "change_pct", "below", -3.0, "%"),
    AlertRule("btc_rally",  "Bitcoin disparou",  "₿", "crypto", ["BTC"], "change_pct", "above",  3.0, "%"),

    # ── Commodities ─────────────────────────────────────────────────────────────
    AlertRule("oil_drop",   "Petróleo em queda",   "🛢️", "commodities_br", ["Petroleo Brent"], "change_pct", "below", -2.0, "%"),
    AlertRule("oil_rally",  "Petróleo em alta",    "🛢️", "commodities_br", ["Petroleo Brent"], "change_pct", "above",  2.0, "%"),
    AlertRule("soja_drop",  "Soja em queda",       "🌾", "commodities_br", ["Soja PR"],        "change_pct", "below", -1.5, "%"),
    AlertRule("soja_rally", "Soja em alta",        "🌾", "commodities_br", ["Soja PR"],        "change_pct", "above",  1.5, "%"),
    AlertRule("milho_drop", "Milho em queda",      "🌽", "commodities_br", ["Milho SP"],       "change_pct", "below", -1.5, "%"),
    AlertRule("milho_rally","Milho em alta",       "🌽", "commodities_br", ["Milho SP"],       "change_pct", "above",  1.5, "%"),
    AlertRule("cana_drop",  "Cana ATR em queda",   "🎋", "esalq",         ["cana_atr"],        "change_pct", "below", -1.5, "%"),
    AlertRule("cana_rally", "Cana ATR em alta",    "🎋", "esalq",         ["cana_atr"],        "change_pct", "above",  1.5, "%"),
    AlertRule("boi_drop",   "Boi Gordo em queda",  "🐂", "commodities_br", ["Boi Gordo SP"],   "change_pct", "below", -1.5, "%"),
    AlertRule("boi_rally",  "Boi Gordo em alta",   "🐂", "commodities_br", ["Boi Gordo SP"],   "change_pct", "above",  1.5, "%"),
]

# Datas das reuniões do COPOM 2026 (dia da decisão).
# Atualizar anualmente com o calendário oficial do Banco Central.
COPOM_DATES_2026: set[str] = {
    "2026-01-29", "2026-03-19", "2026-05-07",
    "2026-06-18", "2026-07-30", "2026-09-17",
    "2026-11-05", "2026-12-10",
}
