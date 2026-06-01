import datetime
import os
import re

import httpx


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
