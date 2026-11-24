"""Vigia externo: confere `/api/health` de FORA e falha quando a SESSÃO do WhatsApp
caiu ou o backend saiu do ar.

Roda no GitHub Actions (`.github/workflows/alarme-whatsapp.yml`). Saída 1 = o GitHub
manda e-mail de "workflow falhou" ao dono. É o único alarme que não depende do
WhatsApp: o boletim diário e o `notify_admin` saem por ele, e foi ele que caiu em
04/09/2026 (~35 h) e em 19–24/11/2026 (~5 dias) sem ninguém saber.

PONTOS CEGOS (robô mudo com vigia VERDE) — não prometer mais do que isto cobre:
  - sessão `open` mas mensagem não entrega (forma do incidente de 14–16/07);
  - crons da Vercel parados (nada sai, a sessão segue `open`);
  - webhook de entrada quebrado (conversa muda, envios seguem).
O sinal `broadcasts.enviados_24h` pegaria só o SEGUNDO (crons parados): envio aceito
pela Evolution conta como enviado mesmo sem chegar (`alert_checker` marca `sent_news`
no 2xx), então o primeiro só se vê pela confirmação de entrega. E só pode virar regra
depois de medir quantos dias normais têm zero envio (senão grita em dia calmo).

Só biblioteca padrão de propósito: o job não instala `requirements.txt`, então
não quebra quando uma dependência do backend quebrar.

Uso: python -m backend.tools.vigia_externo [--simular-queda]
"""
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Endereço que EU controlo — fixo com saída por variável só para testar outro ambiente.
_URL_PADRAO = "https://noticiasgg.vercel.app/api/health"
_TETO_MOTIVO = 300


def _curto(texto: str) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= _TETO_MOTIVO else texto[: _TETO_MOTIVO - 1] + "…"


def avaliar(codigo_http: int | None, corpo: str) -> str | None:
    """None = saudável. Texto = motivo do alarme.

    Estreita de propósito: só toca quando o SINO quebrou (backend fora ou WhatsApp
    sem sessão). Outros `warn`/`error` do health o boletim diário já conta — pelo
    WhatsApp, que nesse caso está de pé. Gritar por eles treinaria o dono a
    ignorar o e-mail."""
    if codigo_http is None:
        return "Backend inalcançável (sem resposta de /api/health)"
    if codigo_http != 200:
        return f"Backend respondeu HTTP {codigo_http} em /api/health"
    try:
        dados = json.loads(corpo)
    except (ValueError, TypeError):
        return "Resposta de /api/health não é JSON (Vercel fora ou página de erro)"
    if not isinstance(dados, dict) or not isinstance(dados.get("checks"), dict):
        return "Resposta de /api/health sem o bloco 'checks'"

    evo = dados["checks"].get("evolution")
    if not isinstance(evo, dict):
        # Check renomeado/removido não pode deixar o vigia verde calado.
        return "Health sem o check 'evolution' — o vigia não consegue conferir o WhatsApp"
    estado = evo.get("estado")
    if estado == "open":
        return None
    if estado:
        return _curto(f"WhatsApp do robô com estado '{estado}' (esperado 'open') — "
                      "alertas e boletim não estão saindo")
    return _curto("Evolution (servidor do WhatsApp) inalcançável: "
                  f"{evo.get('message') or 'sem detalhe'}")


def _buscar(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "noticiasgg-vigia-externo"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    # `http.client.HTTPException` cobre corpo cortado (`IncompleteRead`) e status
    # ilegível (`BadStatusLine`), que NÃO são OSError: escapavam do `checar` e um
    # soluço virava e-mail sem as repetições (achado 4 do Apolo, 24/11/2026).
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        return None, ""


def checar(url: str, tentativas: int = 3, espera: float = 90,
           buscar=_buscar, dormir=time.sleep) -> str | None:
    """Só toca se TODAS as tentativas falharem: um soluço de 1 minuto (restart da
    Evolution, cold start da Vercel) não pode virar e-mail."""
    motivo = None
    for i in range(tentativas):
        if i:
            dormir(espera)
        motivo = avaliar(*buscar(url))
        if motivo is None:
            return None
        print(f"tentativa {i + 1}/{tentativas}: {motivo}", flush=True)
    return motivo


def _escrever_resumo(texto: str) -> None:
    caminho = os.getenv("GITHUB_STEP_SUMMARY")
    if caminho:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def main(argv: list[str]) -> int:
    if "--simular-queda" in argv:
        motivo = "TESTE: queda simulada à mão — se este e-mail chegou, o alarme funciona"
    else:
        motivo = checar(os.getenv("HEALTH_URL") or _URL_PADRAO)

    if motivo is None:
        print("OK: backend no ar e WhatsApp do robô com sessão aberta")
        return 0

    print(f"ALARME: {motivo}")
    _escrever_resumo(
        "## 🔴 Robô do WhatsApp mudo\n\n"
        f"**Motivo:** {motivo}\n\n"
        "Onde está o conserto (`ESTADO.md`), por forma da queda:\n\n"
        "| Sintoma | Seção |\n|---|---|\n"
        "| estado `close` / `connecting` | incidente 19–24/11/2026 — `fetchInstances` "
        "mostra `disconnectionReasonCode`; código 401 ALI = QR novo |\n"
        "| Evolution `401`/`403` no motivo (HTTP) | chave errada, NÃO é QR: "
        "`EVOLUTION_API_KEY` da Vercel ≠ a da VPS (troca de 04/09) |\n"
        "| Evolution inalcançável / 404 | incidente 04/09/2026 — VPS reiniciou, "
        "`docker compose up -d --force-recreate evolution` |\n"
        "| backend HTTP ruim / inalcançável / não-JSON | Vercel: último deploy e logs |"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
