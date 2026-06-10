import datetime
import os
import re
import time

import httpx


class _RetryTransport(httpx.HTTPTransport):
    """Um retry em falha de transporte (timeout/conexão). Seguro aqui porque os
    POSTs do Supabase são upserts idempotentes ou inserts de baixo impacto."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return super().handle_request(request)
        except (httpx.TimeoutException, httpx.ConnectError):
            time.sleep(0.5)
            return super().handle_request(request)


def _client() -> httpx.Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return httpx.Client(
        base_url=f"{url}/rest/v1",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        timeout=15,
        transport=_RetryTransport(),
    )


def get_authorized(lid: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/authorized_users?lid=eq.{lid}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def get_authorized_by_phone(phone: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/authorized_users?phone=eq.{phone}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def add_authorized(lid: str, phone: str, name: str | None = None) -> None:
    with _client() as c:
        r = c.post("/authorized_users", json={"lid": lid, "phone": phone, "name": name})
        r.raise_for_status()


def delete_authorized_by_phone(phone: str) -> None:
    with _client() as c:
        c.delete(f"/authorized_users?phone=eq.{phone}")


def upsert_pending(lid: str, push_name: str, last_message: str) -> None:
    with _client() as c:
        r = c.post(
            "/pending_auth",
            json={"lid": lid, "push_name": push_name, "last_message": last_message},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def pop_oldest_pending() -> dict | None:
    with _client() as c:
        r = c.get("/pending_auth?select=*&order=created_at.asc&limit=1")
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return None
        pending = rows[0]
        d = c.delete(f"/pending_auth?lid=eq.{pending['lid']}")
        d.raise_for_status()
        return pending


def delete_pending(lid: str) -> None:
    with _client() as c:
        r = c.delete(f"/pending_auth?lid=eq.{lid}")
        r.raise_for_status()


def save_message(phone: str, role: str, content: str) -> None:
    with _client() as c:
        r = c.post("/conversation_history", json={"phone": phone, "role": role, "content": content})
        r.raise_for_status()


def get_history(phone: str, limit: int = 10) -> list[dict]:
    with _client() as c:
        r = c.get(f"/conversation_history?phone=eq.{phone}&select=role,content&order=created_at.desc&limit={limit}")
        r.raise_for_status()
        return list(reversed(r.json()))


def count_history(phone: str) -> int:
    with _client() as c:
        r = c.get(
            f"/conversation_history?phone=eq.{phone}&select=id&limit=1",
            headers={"Prefer": "count=exact"},
        )
        r.raise_for_status()
        content_range = r.headers.get("content-range", "*/0")
        try:
            return int(content_range.split("/")[1])
        except (IndexError, ValueError):
            return 0


def delete_old_history(phone: str, keep_recent: int = 6) -> None:
    """Deleta todas as mensagens exceto as `keep_recent` mais recentes."""
    with _client() as c:
        r = c.get(
            f"/conversation_history?phone=eq.{phone}&select=created_at"
            f"&order=created_at.desc&limit=1&offset={keep_recent}",
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return
        cutoff = rows[0]["created_at"]
        c.delete(f"/conversation_history?phone=eq.{phone}&created_at=lte.{cutoff}").raise_for_status()


def get_summary(phone: str) -> str | None:
    with _client() as c:
        r = c.get(f"/conversation_summaries?phone=eq.{phone}&select=summary")
        r.raise_for_status()
        rows = r.json()
        return rows[0]["summary"] if rows else None


def save_summary(phone: str, summary: str) -> None:
    with _client() as c:
        r = c.post(
            "/conversation_summaries",
            json={
                "phone": phone,
                "summary": summary,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def get_preferences(phone: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/user_preferences?phone=eq.{phone}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def save_preferences(
    phone: str,
    sections: dict | None,
    report_time: str | None,
    audio_for_text: bool | None = None,
    audio_for_media: bool | None = None,
    tts_voice: str | None = None,
    tts_speed: float | None = None,
) -> None:
    payload: dict = {
        "phone": phone,
        "sections": sections,
        "report_time": report_time,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if audio_for_text is not None:
        payload["audio_for_text"] = audio_for_text
    if audio_for_media is not None:
        payload["audio_for_media"] = audio_for_media
    if tts_voice is not None:
        payload["tts_voice"] = tts_voice
    if tts_speed is not None:
        payload["tts_speed"] = tts_speed
    with _client() as c:
        r = c.post(
            "/user_preferences",
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def delete_preferences(phone: str) -> None:
    with _client() as c:
        r = c.delete(f"/user_preferences?phone=eq.{phone}")
        r.raise_for_status()


def save_polls(polls: list[dict]) -> None:
    with _client() as c:
        for poll in polls:
            c.post(
                "/polls_cache",
                json={
                    "instituto": poll["instituto"],
                    "turno": poll.get("turno"),
                    "data_pesquisa": poll.get("data_pesquisa"),
                    "candidatos": poll["candidatos"],
                    "fonte_url": poll.get("fonte_url"),
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            )


def get_polls() -> list[dict]:
    with _client() as c:
        r = c.get("/polls_cache?select=instituto,turno,data_pesquisa,candidatos,fonte_url&order=updated_at.desc")
        r.raise_for_status()
        return r.json()


def get_alert_last_triggered(rule_id: str) -> datetime.datetime | None:
    with _client() as c:
        r = c.get(f"/system_alert_state?rule_id=eq.{rule_id}&select=last_triggered_at")
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return None
        return datetime.datetime.fromisoformat(rows[0]["last_triggered_at"])


def set_alert_triggered(rule_id: str) -> None:
    with _client() as c:
        r = c.post(
            "/system_alert_state",
            json={
                "rule_id": rule_id,
                "last_triggered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def is_news_sent(news_id: str) -> bool:
    with _client() as c:
        r = c.get(f"/sent_news?news_id=eq.{news_id}&select=news_id")
        r.raise_for_status()
        return len(r.json()) > 0


def mark_news_sent(news_id: str, title: str | None = None) -> None:
    payload: dict = {
        "news_id": news_id,
        "sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if title:
        payload["title"] = title
    with _client() as c:
        r = c.post(
            "/sent_news",
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def get_recent_sent_titles(hours: int = 24, limit: int = 20) -> list[str]:
    """Títulos de notícias efetivamente entregues (title preenchido só em broadcast)."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    with _client() as c:
        r = c.get(
            f"/sent_news?select=title&title=not.is.null"
            f"&sent_at=gte.{cutoff}&order=sent_at.desc&limit={limit}"
        )
        r.raise_for_status()
        return [row["title"] for row in r.json()]


def get_users_for_hour(hour_brt: str) -> list[dict]:
    if not re.fullmatch(r"\d{2}:00", hour_brt):
        return []
    with _client() as c:
        r = c.get(f"/user_preferences?report_time=eq.{hour_brt}&select=phone,sections")
        r.raise_for_status()
        prefs = r.json()
        if not prefs:
            return []
        phones = ",".join(p["phone"] for p in prefs)
        r2 = c.get(f"/authorized_users?phone=in.({phones})&select=phone,name")
        r2.raise_for_status()
        users_by_phone = {u["phone"]: u.get("name") for u in r2.json()}
    return [
        {
            "phone": p["phone"],
            "name": users_by_phone.get(p["phone"]),
            "sections": p.get("sections"),
        }
        for p in prefs
        if p["phone"] in users_by_phone
    ]
