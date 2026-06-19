import time

from backend.services import supabase

_CACHE_TTL = 60.0
_cache: dict | None = None
_cache_at: float = 0.0


def clear_cache() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _load() -> dict:
    """Carrega todas as configs (cache com TTL). Em falha, mantém o cache
    anterior ou retorna {} (tudo cai no default) — nunca propaga exceção."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return _cache
    try:
        rows = supabase.get_all_config()
        _cache = {r["key"]: r["value"] for r in rows}
        _cache_at = now
    except Exception:
        if _cache is None:
            return {}
        _cache_at = now  # mantém cache velho, evita martelar o banco
    return _cache if _cache is not None else {}


def get(key: str, default):
    val = _load().get(key)
    return default if val is None else val


def get_list(key: str, default: list) -> list:
    val = get(key, None)
    return val if isinstance(val, list) else default


def get_str(key: str, default: str) -> str:
    val = get(key, None)
    return val if isinstance(val, str) and val.strip() else default
