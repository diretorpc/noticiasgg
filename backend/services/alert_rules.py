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


# Foco: variáveis que influenciam precificação de commodities.
# Câmbio (DXY) só alerta em oscilação forte (>=2%). As demais categorias
# (demanda global, oferta/clima, geopolítica, BR) são cobertas via notícias
# no alert_checker — quanto antes a informação chegar, melhor.
RULES: list[AlertRule] = [
    AlertRule("dxy_drop",  "Dólar (DXY) em queda forte", "💵", "market", ["cambio", "DXY (Índice Dólar)"], "change_pct", "below", -2.0, "%"),
    AlertRule("dxy_rally", "Dólar (DXY) em alta forte",  "💵", "market", ["cambio", "DXY (Índice Dólar)"], "change_pct", "above",  2.0, "%"),
]

# Datas das reuniões do COPOM 2026 (dia da decisão).
# Atualizar anualmente com o calendário oficial do Banco Central.
# Conferido em 09/09/2026 contra o calendário divulgado pelo BCB. Decisão sai
# sempre na quarta; o conjunto anterior era o calendário de 2025 (todas quintas).
COPOM_DATES_2026: set[str] = {
    "2026-01-28", "2026-03-18", "2026-04-29",
    "2026-06-17", "2026-08-05", "2026-09-16",
    "2026-11-04", "2026-12-09",
}
