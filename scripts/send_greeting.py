#!/usr/bin/env python3
"""Saudação inicial — rodar UMA VEZ antes do primeiro relatório."""
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

GREETING = """\
Olá, *{primeiro_nome}*! 👋

Sou o *Agente Notícias GG*, seu assistente financeiro pessoal.

Todo dia vou te enviar um resumo com as principais notícias e movimentos do mercado: bolsas, câmbio, criptomoedas, indicadores econômicos e muito mais.

Mas não sou só um robô de relatórios — pode me fazer perguntas quando quiser! Exemplos:

• _"Como está o dólar hoje?"_
• _"O que aconteceu com a Petrobras?"_
• _"Qual a taxa Selic atual?"_

Você também pode personalizar o que recebe. É só me pedir, por exemplo:
• _"Quero só notícias e cripto"_
• _"Me manda o relatório às 8h"_

Qualquer dúvida, é só falar. Bom mercado! 📈"""


def _get_all_users() -> list[dict]:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    with httpx.Client(
        base_url=f"{url}/rest/v1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=15,
    ) as c:
        r = c.get("/authorized_users?select=phone,name&order=created_at.asc")
        r.raise_for_status()
        return r.json()


def _send(number: str, text: str) -> None:
    url = os.environ["EVOLUTION_API_URL"]
    key = os.environ["EVOLUTION_API_KEY"]
    instance = os.environ["EVOLUTION_INSTANCE"]
    with httpx.Client(timeout=30) as c:
        r = c.post(
            f"{url}/message/sendText/{instance}",
            json={"number": number, "options": {"delay": 0, "presence": "composing"}, "textMessage": {"text": text}},
            headers={"apikey": key, "Content-Type": "application/json"},
        )
        r.raise_for_status()


def main():
    users = _get_all_users()
    print(f"{len(users)} usuário(s) encontrado(s).\n")

    for user in users:
        phone = user["phone"]
        name = user.get("name") or "amigo"
        primeiro_nome = name.split()[0]
        text = GREETING.format(primeiro_nome=primeiro_nome)

        try:
            _send(phone, text)
            print(f"[OK] {name} ({phone})")
        except Exception as e:
            print(f"[ERRO] {name} ({phone}): {e}")

        time.sleep(2)

    print("\nPronto!")


if __name__ == "__main__":
    main()
