from backend.services.report_prompts import SECTIONS
from backend.services.supabase import _client, _f


def grid_to_rows(phone: str, schedule: dict) -> list[dict]:
    """Valida e deduplica ANTES de tocar no banco: replace_for_phone faz DELETE
    e depois INSERT, então linha duplicada (mesma PK) ou valor fora da faixa
    derrubava o INSERT depois de a grade antiga já ter sido apagada."""
    rows: list[dict] = []
    seen: set[tuple] = set()
    for section, days in (schedule or {}).items():
        if section not in SECTIONS:
            raise ValueError(f"seção desconhecida: {section!r}")
        for weekday, hours in (days or {}).items():
            wd = int(weekday)
            if not 0 <= wd <= 6:
                raise ValueError(f"weekday fora da faixa 0-6: {weekday!r}")
            for hour in hours:
                h = int(hour)
                if not 0 <= h <= 23:
                    raise ValueError(f"hour fora da faixa 0-23: {hour!r}")
                key = (section, wd, h)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"phone": phone, "section": section, "weekday": wd, "hour": h})
    return rows


def rows_to_grid(rows: list[dict]) -> dict:
    grid: dict = {}
    for r in rows:
        grid.setdefault(r["section"], {}).setdefault(str(r["weekday"]), []).append(r["hour"])
    for section in grid:
        for wd in grid[section]:
            grid[section][wd] = sorted(set(grid[section][wd]))
    return grid


def due_now(weekday: int, hour: int) -> list[dict]:
    with _client() as c:
        r = c.get(f"/report_schedules?weekday=eq.{int(weekday)}&hour=eq.{int(hour)}&select=phone,section")
        r.raise_for_status()
        return r.json()


def get_for_phone(phone: str) -> list[dict]:
    with _client() as c:
        r = c.get(f"/report_schedules?phone=eq.{_f(phone)}&select=section,weekday,hour")
        r.raise_for_status()
        return r.json()


def replace_for_phone(phone: str, rows: list[dict]) -> None:
    with _client() as c:
        d = c.delete(f"/report_schedules?phone=eq.{_f(phone)}")
        d.raise_for_status()
        if rows:
            p = c.post("/report_schedules", json=rows)
            p.raise_for_status()


def set_engine_flag(phone: str, enabled: bool) -> None:
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"use_new_report_engine": bool(enabled)})
        r.raise_for_status()


def phones_with_engine_enabled() -> set[str]:
    with _client() as c:
        r = c.get("/authorized_users?use_new_report_engine=is.true&select=phone")
        r.raise_for_status()
        return {row["phone"] for row in r.json()}
