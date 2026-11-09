"""SÓ LEITURA. Quem tem grade em report_schedules mas `use_new_report_engine` desligada?

O cron (`backend/api/cron_report.py`) só manda para quem tem a chave ligada; a grade do
/me salva mesmo com ela desligada. Este script conta quem está nesse buraco.

Uso:  python -m backend.tools.medir_grade_desligada [caminho/do/.env]
Sem argumento lê o `.env` da raiz do repo (como `cutover_audit.py`). O argumento existe
porque um worktree não tem `.env`.

Não escreve nada. Não imprime chave, conteúdo de conversa nem telefone completo.
"""
import os
import sys
from pathlib import Path

import httpx


def _load_env(env: Path) -> None:
    if not env.exists():
        sys.exit(f"sem .env em {env}")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    env = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / ".env"
    _load_env(env)
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = os.environ["SUPABASE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}

    with httpx.Client(base_url=base, headers=h, timeout=20) as c:
        users = c.get("/authorized_users?select=phone,name,use_new_report_engine")
        users.raise_for_status()
        sched = c.get("/report_schedules?select=phone")
        sched.raise_for_status()

    rows: dict[str, int] = {}
    for r in sched.json():
        rows[r["phone"]] = rows.get(r["phone"], 0) + 1

    us = users.json()
    print(f"authorized_users: {len(us)} | flag ligada: {sum(1 for u in us if u.get('use_new_report_engine'))}")
    print(f"com linha na grade: {len(rows)}")
    atingidos = [u for u in us if rows.get(u["phone"]) and not u.get("use_new_report_engine")]
    print(f"ATINGIDOS (grade + envio desligado): {len(atingidos)}")
    for u in atingidos:
        print(f"  ...{u['phone'][-4:]}  {u.get('name') or '-'}  linhas={rows[u['phone']]}")
    sem_grade_off = [u for u in us if not rows.get(u["phone"]) and not u.get("use_new_report_engine")]
    print(f"sem grade e envio desligado (abririam o /me e veriam grade vazia): {len(sem_grade_off)}")
    orfas = [p for p in rows if p not in {u["phone"] for u in us}]
    print(f"linhas de grade de telefone fora de authorized_users: {len(orfas)}")


if __name__ == "__main__":
    main()
