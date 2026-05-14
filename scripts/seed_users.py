#!/usr/bin/env python3
"""Seed inicial dos usuários autorizados. Rodar uma vez."""
import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

USERS = [
    {"phone": "5534999945010", "name": "Matheus",  "lid": "5534999945010"},
    {"phone": "5534999301855", "name": "Ricardim", "lid": "5534999301855"},
    {"phone": "5534996568291", "name": "Cassiano", "lid": "5534996568291"},
    {"phone": "5534988162802", "name": "Jorge",    "lid": "5534988162802"},
]


def seed():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    with httpx.Client(base_url=f"{url}/rest/v1", headers=headers, timeout=15) as c:
        for user in USERS:
            r = c.post("/authorized_users", json=user)
            r.raise_for_status()
            print(f"[OK] {user['name']} ({user['phone']})")
    print(f"\nSeed completo: {len(USERS)} usuários inseridos/atualizados.")


if __name__ == "__main__":
    seed()
