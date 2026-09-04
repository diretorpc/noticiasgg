"""Parsing de número em formato brasileiro (ex.: "1.234,56" -> 1234.56).

Módulo neutro, sem I/O e sem estado — de propósito não é um "collector"
(`esalq.py` e `soja_disponivel.py` são). `main.py` importa todo coletor no
topo do arquivo: se essa função morasse dentro de um deles, renomear um
símbolo "privado" (`_parse_br_float`) por conveniência derrubaria o app
inteiro na importação de outro módulo que dependesse dele — foi o que quase
aconteceu quando `soja_disponivel.py` importou `_parse_br_float` direto de
`esalq.py`.
"""


def parse_br_float(text: str) -> float | None:
    try:
        cleaned = text.strip().replace(".", "").replace(",", ".").lstrip("+")
        return float(cleaned)
    except Exception:
        return None
