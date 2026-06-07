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
