"""Auditoria read-only pré-cutover do motor de relatório.

Cruza os 3 estados por usuário:
  - authorized_users.use_new_report_engine  (flag do motor novo)
  - user_preferences.report_time            (gatilho do relatório ANTIGO via n8n)
  - report_schedules (rows)                 (gatilho do motor NOVO via cron Vercel)

Objetivo: achar quem recebe relatório hoje (report_time setado) mas ficaria
SEM relatório depois de desligar o n8n (flag off OU sem rows em report_schedules).

Uso:  python -m backend.tools.cutover_audit
Não escreve nada.
"""
import os
from pathlib import Path

import httpx


def _load_env() -> None:
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    _load_env()
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = os.environ["SUPABASE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}

    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote
    cutoff = quote((datetime.now(timezone.utc) - timedelta(days=7)).isoformat())

    with httpx.Client(base_url=base, headers=h, timeout=20) as c:
        users = c.get("/authorized_users?select=phone,name,use_new_report_engine").json()
        prefs = c.get("/user_preferences?select=phone,report_time,sections").json()
        sched = c.get("/report_schedules?select=phone,section,weekday,hour").json()
        # Mensagens de assistente nos ultimos 7 dias = quem recebe relatorio/chat hoje
        recent = c.get(
            f"/conversation_history?role=eq.assistant&created_at=gte.{cutoff}"
            "&select=phone,created_at,content&order=created_at.desc"
        ).json()

    asst_by: dict[str, list] = {}
    for m in recent:
        asst_by.setdefault(m["phone"], []).append(m)

    pref_by = {p["phone"]: p for p in prefs}
    sched_count: dict[str, int] = {}
    for r in sched:
        sched_count[r["phone"]] = sched_count.get(r["phone"], 0) + 1

    # report_time NAO indica quem recebe relatorio (e flag de skip do n8n, nao gatilho).
    # A verdade de "quem recebe hoje" vem da atividade real em conversation_history.
    print(f"\n{'phone':<16} {'name':<18} flag  report_time  sched_rows  msgs/7d  STATUS")
    print("-" * 88)
    review = []
    for u in sorted(users, key=lambda x: x["phone"]):
        ph = u["phone"]
        flag = bool(u.get("use_new_report_engine"))
        rt = (pref_by.get(ph) or {}).get("report_time")
        n = sched_count.get(ph, 0)
        recent = len(asst_by.get(ph, []))
        gets_new = flag and n > 0  # coberto pelo motor novo
        if gets_new:
            status = "motor novo cobre"
        elif recent > 0:
            status = f"REVISAR (tem atividade; ver se sao relatorios do n8n)"
            review.append(ph)
        else:
            status = "inativo"
        print(f"{ph:<16} {str(u.get('name') or ''):<18} {str(flag):<5} {str(rt or '-'):<11}  {n:<10} {recent:<7}  {status}")

    print("-" * 88)
    print(f"total usuarios: {len(users)} | revisar antes do cutover: {len(review)} {review}")
    print(f"flag ligada: {sum(1 for u in users if u.get('use_new_report_engine'))}")
    print(f"com schedule rows: {len(sched_count)} | total rows: {len(sched)}")

    print("\n=== Mensagens de assistente nos ultimos 7 dias (quem o sistema serve hoje) ===")
    for u in sorted(users, key=lambda x: x["phone"]):
        ph = u["phone"]
        msgs = asst_by.get(ph, [])
        if not msgs:
            print(f"{ph:<16} {str(u.get('name') or ''):<18} 0 msgs")
            continue
        last = msgs[0]
        snippet = (last["content"] or "").replace("\n", " ")[:70]
        print(f"{ph:<16} {str(u.get('name') or ''):<18} {len(msgs):>3} msgs | ultima {last['created_at'][:16]} | {snippet}")


if __name__ == "__main__":
    main()
