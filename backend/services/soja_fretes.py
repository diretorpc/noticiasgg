"""Fretes editáveis da mensagem diária "Soja Disponível" (Porto − frete = praça).

Fonte única do rótulo/ordem que a mensagem usa (`docs` spec 04/09/2026, resposta do
primo): PRACAS. O painel lê `describe()["pracas"]` em vez de duplicar rótulo/ordem.

Guardado em `agent_config` (key=CONFIG_KEY, value=JSON {chave: valor}) — mesma tabela
dos prompts de relatório, mas lido SEM cache (config.py cacheia 60s; aqui a leitura é
1x/dia no boletim + sob demanda no painel, e o dado precisa de `updated_at`/
`updated_by`, que `config.get()` não carrega).
"""
import datetime
import math

from backend.services import secrets_mask, supabase

PRACAS = (
    ("pontal", "Pontal/SP🌱1️⃣", 9.0),
    ("uberaba", "Uberaba/MG🌱2️⃣", 12.0),
    ("canarana", "Canarana/MT🌱3️⃣", 27.0),
)

CONFIG_KEY = "soja_fretes"
LIMITE_DIAS = 60

_DEFAULTS = {chave: default for chave, _rotulo, default in PRACAS}
_TETO = 200.0


def _numero_valido(v) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return math.isfinite(v) and 0 < v <= _TETO


def validar(fretes: dict) -> dict:
    """Confere as 3 chaves de PRACAS: número finito, 0 < valor <= 200.
    Levanta ValueError com mensagem clara (sem dado sensível — nunca ecoa o
    payload inteiro nem detalhe de infraestrutura)."""
    if not isinstance(fretes, dict):
        raise ValueError("fretes precisa ser um objeto com pontal/uberaba/canarana")
    out = {}
    for chave, _rotulo, _default in PRACAS:
        if chave not in fretes:
            raise ValueError(f"falta o frete de '{chave}'")
        valor = fretes[chave]
        if not _numero_valido(valor):
            raise ValueError(
                f"frete de '{chave}' precisa ser um número maior que 0 e até 200"
            )
        out[chave] = float(valor)
    return out


def _idade_dias(updated_at: str | None) -> int | None:
    if not updated_at:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    delta = datetime.datetime.now(datetime.timezone.utc) - dt
    # Relógio torto (skew de servidor, achado 7) não pode virar idade negativa —
    # isso passaria como "recém-editado" mesmo com a data quebrada.
    return max(delta.days, 0)


def _pracas_com_valor(fretes: dict) -> list[dict]:
    return [{"chave": chave, "rotulo": rotulo, "valor": fretes[chave]} for chave, rotulo, _d in PRACAS]


def descrever_defaults() -> str:
    """'9/12/27' a partir de PRACAS, na ordem definida ali. Fonte única do texto
    usado no boletim (health.py) e no confirm de reset do painel — antes vivia
    hardcoded nos dois lugares além daqui (achado 3, 04/09/2026)."""
    partes = []
    for _chave, _rotulo, default in PRACAS:
        partes.append(str(int(default)) if float(default).is_integer() else str(default))
    return "/".join(partes)


def describe() -> dict:
    """Valor efetivo dos fretes + metadados de edição. Nunca levanta — se o
    Supabase falhar, devolve os defaults com `erro` sanitizado (achado A1,
    18/08: erro de fornecedor cru não pode voltar ao chamador)."""
    try:
        row = supabase.get_config_row(CONFIG_KEY)
    except Exception as e:
        return {
            "fretes": dict(_DEFAULTS),
            "pracas": _pracas_com_valor(dict(_DEFAULTS)),
            "is_custom": False,
            "updated_at": None,
            "updated_by": None,
            "idade_dias": None,
            "envelhecido": True,
            "defaults": dict(_DEFAULTS),
            "erro": secrets_mask.sanitize_error(e),
        }

    if row is None:
        # Nunca salvo no painel = sem data = envelhecido, de propósito (o boletim
        # não pode ficar calado sobre "está usando o padrão desde sempre").
        fretes = dict(_DEFAULTS)
        out = {
            "fretes": fretes,
            "pracas": _pracas_com_valor(fretes),
            "is_custom": False,
            "updated_at": None,
            "updated_by": None,
            "idade_dias": None,
            "envelhecido": True,
            "defaults": dict(_DEFAULTS),
        }
        return out

    valor = row.get("value")
    updated_at = row.get("updated_at")
    updated_by = row.get("updated_by")

    fretes = dict(_DEFAULTS)
    aviso = None
    if isinstance(valor, dict):
        for chave, _rotulo, _default in PRACAS:
            v = valor.get(chave)
            if _numero_valido(v):
                fretes[chave] = float(v)
            else:
                aviso = "valor salvo incompleto ou inválido — usando padrão para o(s) frete(s) faltante(s)"
    else:
        aviso = "valor salvo inválido — usando padrão"

    idade_dias = _idade_dias(updated_at)
    is_custom = True
    envelhecido = (not is_custom) or idade_dias is None or idade_dias > LIMITE_DIAS

    out = {
        "fretes": fretes,
        "pracas": _pracas_com_valor(fretes),
        "is_custom": is_custom,
        "updated_at": updated_at,
        "updated_by": updated_by,
        "idade_dias": idade_dias,
        "envelhecido": envelhecido,
        "defaults": dict(_DEFAULTS),
    }
    if aviso:
        out["aviso"] = aviso
    return out
