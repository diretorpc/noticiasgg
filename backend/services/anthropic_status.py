"""Saber se a Anthropic ainda atende — e distinguir "caiu agora" de "acabou".

Por que existe (31/08/2026): o saldo da conta zerou em produção e **nada** avisou.
O `/api/health` respondia `keys: ok` porque só conferia se a variável de ambiente
EXISTE, não se ela FUNCIONA; e o cron de alertas caía no
`except Exception: logger.warning(...); continue`, logando um aviso por notícia a
cada 15 minutos, para sempre, sem que ninguém soubesse. O agente ficou mudo e o
painel ficou verde — a falha silenciosa exata que este projeto passou o dia
caçando, na dependência mais crítica de todas.

Dois problemas diferentes, dois remédios:

- **`erro_permanente`** separa o que ADIANTA repetir do que não adianta. Saldo
  zerado, chave inválida e chave sem permissão não melhoram sozinhos: exigem que
  uma pessoa faça alguma coisa. Timeout e 529 melhoram. Tratar os dois igual é o
  que fazia o cron insistir em silêncio.
- **`sondar`** pergunta à API se ela atende, gastando o mínimo possível.
"""
import anthropic

from backend.services import models

# Falhas que NÃO melhoram sozinhas — alguém precisa agir.
_PERMANENTES = (
    anthropic.AuthenticationError,     # 401: chave errada ou revogada
    anthropic.PermissionDeniedError,   # 403: chave sem acesso ao modelo
)

# O saldo esgotado chega como 400 (`BadRequestError`), que normalmente é erro de
# programação e NÃO deve virar alarme. Só estas marcas no texto o distinguem.
_MARCAS_DE_SALDO = ("credit balance", "billing", "quota", "insufficient")


def erro_permanente(e: BaseException) -> str | None:
    """Motivo em português se a falha exige ação humana; `None` se é passageira.

    Devolver texto (e não `True`) é de propósito: quem chama manda isso direto
    para o WhatsApp do dono, e "saldo da Anthropic esgotado" resolve o problema
    mais rápido que "BadRequestError".
    """
    if isinstance(e, _PERMANENTES):
        return "chave da Anthropic inválida ou sem permissão (401/403)"
    # 404 não melhora sozinho. Antes caía em "não respondeu agora" (aviso amarelo,
    # passageiro). Medido com a API real em 09/11/2026: modelo aposentado devolve
    # `not_found_error` com "model: <nome>" no texto. Sem essa marca, o 404 vem de
    # outro lugar (proxy, `ANTHROPIC_BASE_URL` errada) — mandar trocar o modelo seria
    # apontar a coisa errada.
    if isinstance(e, anthropic.NotFoundError):
        if "model" in str(e).lower():
            return ("modelo da Anthropic não encontrado (aposentado ou nome errado) — trocar "
                    "ANTHROPIC_HAIKU_MODEL / ANTHROPIC_SONNET_MODEL na Vercel")
        return "Anthropic devolveu 404 fora do modelo — conferir ANTHROPIC_BASE_URL ou proxy"
    if isinstance(e, anthropic.BadRequestError):
        texto = str(e).lower()
        if any(m in texto for m in _MARCAS_DE_SALDO):
            return "saldo da Anthropic esgotado — recarregar em console.anthropic.com"
    return None


def sondar(timeout: float = 10.0) -> dict:
    """Uma chamada mínima de verdade: é a única forma de saber que a API atende.

    `models.list()` não serve — ele responde 200 com saldo zerado, porque não é
    inferência. Só o endpoint de mensagens recusa por saldo, então a sonda tem que
    ser uma mensagem. Com `max_tokens=1` e um prompt de uma palavra, as duas chamadas
    (Haiku + Sonnet) custam da ordem de US$ 0,00004.

    NÃO chamar isto de dentro de `GET /api/health`, que é público e sem senha: é a
    mesma razão pela qual `collect_status_completo` existe separado. Uma chamada
    paga num endpoint aberto é convite para esvaziarem o saldo por você.
    """
    import os

    if not os.getenv("ANTHROPIC_API_KEY"):
        return {"status": "error", "message": "ANTHROPIC_API_KEY ausente"}
    # Os DOIS modelos em uso, cada um no seu `try`: o Sonnet aposentado derruba o chat
    # e o relatório, e uma sonda que parasse no primeiro erro deixava o segundo modelo
    # sem teste no dia (timeout no Haiku → Sonnet nunca sondado; os dois 404 → só o
    # Haiku nomeado). Toda mensagem diz QUAL modelo falhou.
    # Agrupado por motivo: com os dois modelos falhando igual, a mesma instrução de
    # ~140 caracteres saía duas vezes no boletim.
    permanentes: dict[str, list[str]] = {}
    passageiros: list[str] = []
    try:
        cliente = anthropic.Anthropic(timeout=timeout, max_retries=0)
    except Exception as e:
        # Quem chama (`health.collect_status_completo`) não protege esta chamada:
        # sair daqui com exceção derrubaria o boletim inteiro, não só esta linha.
        return {"status": "error", "message": f"cliente Anthropic não abriu: {type(e).__name__}"}
    for modelo in (models.haiku(), models.sonnet()):
        try:
            cliente.messages.create(
                model=modelo,
                max_tokens=1,
                messages=[{"role": "user", "content": "ok"}],
            )
        except Exception as e:
            motivo = erro_permanente(e)
            if motivo:
                permanentes.setdefault(motivo, []).append(modelo)
            else:
                passageiros.append(f"{modelo}: {type(e).__name__}")
    if permanentes:
        return {"status": "error", "message": "; ".join(
            f"{motivo} (falhou: {', '.join(lista)})" for motivo, lista in permanentes.items())}
    if passageiros:
        # Passageiro não é "error": um 529 momentâneo não é problema do dono, e
        # gritar por causa dele treina a pessoa a ignorar o boletim.
        return {"status": "warn", "message": f"Anthropic não respondeu agora: {'; '.join(passageiros)}"}
    return {"status": "ok"}
