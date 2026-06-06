import os
from anthropic import Anthropic

_SYSTEM = """Você é um compressor de histórico de conversa.

Você receberá mensagens trocadas entre um usuário e um assistente financeiro, e um resumo anterior (pode estar vazio).

Gere um resumo conciso e fiel que:
- Capture os tópicos principais discutidos
- Preserve preferências ou informações pessoais mencionadas pelo usuário
- Registre perguntas respondidas e decisões tomadas
- Seja útil como contexto para continuar a conversa

Regras:
- Máximo 400 palavras
- Em português
- Sem preâmbulo — comece direto
- Se houver resumo anterior, integre com as novas mensagens sem repetir o que já está resumido"""


def summarize(messages: list[dict], existing_summary: str | None = None) -> str:
    """Comprime mensagens antigas em um resumo via Claude Haiku.

    Retorna o resumo atualizado; em caso de falha retorna o resumo anterior (ou string vazia).
    """
    if not messages:
        return existing_summary or ""

    parts: list[str] = []
    if existing_summary:
        parts.append(f"RESUMO ANTERIOR:\n{existing_summary}\n")

    parts.append("MENSAGENS A RESUMIR:")
    for m in messages:
        role = "Usuário" if m["role"] == "user" else "Assistente"
        content = m["content"]
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        parts.append(f"{role}: {str(content)[:500]}")

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                return block.text.strip()
    except Exception:
        pass
    return existing_summary or ""
