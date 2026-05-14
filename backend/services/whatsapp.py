import os
import httpx


def send_message(number: str, text: str) -> dict:
    url = os.environ["EVOLUTION_API_URL"]
    api_key = os.environ["EVOLUTION_API_KEY"]
    instance = os.environ["EVOLUTION_INSTANCE"]

    endpoint = f"{url}/message/sendText/{instance}"
    payload = {"number": number, "options": {"delay": 0, "presence": "composing"}, "textMessage": {"text": text}}

    with httpx.Client(timeout=30) as client:
        resp = client.post(endpoint, json=payload, headers={"apikey": api_key, "Content-Type": "application/json"})
        resp.raise_for_status()
        return resp.json()
