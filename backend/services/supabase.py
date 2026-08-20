import datetime
import logging
import os
import re
import secrets
import time
from urllib.parse import quote

import httpx

logger = logging.getLogger("noticiasgg.supabase")


def _f(value) -> str:
    """Encoda um valor que vai num filtro PostgREST (?col=eq.{value}).
    Impede injeção de operadores via `&`/`(`/etc quando o valor vem de
    fonte externa (ex: remoteJid do webhook público)."""
    return quote(str(value), safe="")


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
        r = c.get(f"/authorized_users?lid=eq.{_f(lid)}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def get_authorized_by_phone(phone: str) -> dict | None:
    with _client() as c:
        r = c.get(f"/authorized_users?phone=eq.{_f(phone)}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def get_authorized_by_jid(jid: str) -> dict | None:
    """Encontra o usuário a partir do `remoteJid` do webhook.

    O formato varia por versão da Evolution: a v1 manda `<lid>@lid`, a v2 manda
    `<numero>@s.whatsapp.net`. Para números brasileiros o JID costuma vir sem o
    9 extra, então tenta as duas grafias.
    """
    if not jid:
        return None
    if jid.endswith("@lid"):
        return get_authorized(jid)

    number = jid.split("@")[0]
    user = get_authorized_by_phone(number)
    if user:
        return user
    if number.startswith("55"):
        if len(number) == 12:  # sem o 9 extra → tenta com
            user = get_authorized_by_phone(number[:4] + "9" + number[4:])
        elif len(number) == 13:  # com o 9 extra → tenta sem
            user = get_authorized_by_phone(number[:4] + number[5:])
    return user


def add_authorized(lid: str, phone: str, name: str | None = None) -> None:
    with _client() as c:
        r = c.post("/authorized_users", json={"lid": lid, "phone": phone, "name": name})
        r.raise_for_status()


def delete_authorized_by_phone(phone: str) -> None:
    with _client() as c:
        c.delete(f"/authorized_users?phone=eq.{_f(phone)}")


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
        d = c.delete(f"/pending_auth?lid=eq.{_f(pending['lid'])}")
        d.raise_for_status()
        return pending


def delete_pending(lid: str) -> None:
    with _client() as c:
        r = c.delete(f"/pending_auth?lid=eq.{_f(lid)}")
        r.raise_for_status()


def save_message(phone: str, role: str, content: str) -> None:
    with _client() as c:
        r = c.post("/conversation_history", json={"phone": phone, "role": role, "content": content})
        r.raise_for_status()


def get_history(phone: str, limit: int = 10) -> list[dict]:
    with _client() as c:
        r = c.get(f"/conversation_history?phone=eq.{_f(phone)}&select=role,content&order=created_at.desc&limit={limit}")
        r.raise_for_status()
        return list(reversed(r.json()))


def count_history(phone: str) -> int:
    with _client() as c:
        r = c.get(
            f"/conversation_history?phone=eq.{_f(phone)}&select=id&limit=1",
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
            f"/conversation_history?phone=eq.{_f(phone)}&select=created_at"
            f"&order=created_at.desc&limit=1&offset={keep_recent}",
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return
        cutoff = rows[0]["created_at"]
        c.delete(f"/conversation_history?phone=eq.{_f(phone)}&created_at=lte.{_f(cutoff)}").raise_for_status()


def get_summary(phone: str) -> str | None:
    with _client() as c:
        r = c.get(f"/conversation_summaries?phone=eq.{_f(phone)}&select=summary")
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
        r = c.get(f"/user_preferences?phone=eq.{_f(phone)}&select=*")
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
        r = c.delete(f"/user_preferences?phone=eq.{_f(phone)}")
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
    """`rule_id` hoje é sempre normalizado por quem chama (ex.: `_source_rule_id`),
    mas `_f()` protege qualquer chamador futuro que esqueça — sem isto um `rule_id`
    com `&`/`(` corta a query string e o filtro vira outra coisa em silêncio
    (achado A4, revisão 18/08/2026)."""
    with _client() as c:
        r = c.get(f"/system_alert_state?rule_id=eq.{_f(rule_id)}&select=last_triggered_at")
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


def claim_message(message_id: str) -> bool:
    """Reserva a etiqueta de uma mensagem do WhatsApp para deduplicação.

    Retorna True se esta chamada reservou a etiqueta (mensagem nova) e False se
    ela já estava reservada (reenvio da Evolution). A atomicidade vem da PRIMARY
    KEY de processed_messages: um POST com etiqueta repetida devolve 409 e ninguém
    sobrescreve. NÃO usa merge-duplicates de propósito — precisamos do conflito.
    """
    with _client() as c:
        r = c.post("/processed_messages", json={"message_id": message_id})
        if r.status_code == 409:  # violação de PK → etiqueta já reservada
            return False
        r.raise_for_status()
        return True


def get_recent_sent_titles(hours: int = 24, limit: int = 20) -> list[str]:
    """Títulos de notícias efetivamente entregues (title preenchido só em broadcast)."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    with _client() as c:
        r = c.get(
            f"/sent_news?select=title&title=not.is.null"
            f"&sent_at=gte.{_f(cutoff)}&order=sent_at.desc&limit={limit}"
        )
        r.raise_for_status()
        return [row["title"] for row in r.json()]


_NEWS_LOG_FIELDS = (
    "news_id", "titulo_pt", "titulo_original", "fonte", "feed", "url",
    "url_publisher", "url_final", "categoria", "resumo", "resumo_fonte", "direcao",
    "score", "ativos", "publicado_em", "conteudo", "conteudo_fonte",
)


def _iso_valido(valor) -> bool:
    """`publicado_em` do caminho NewsAPI (`publishedAt`) entra cru, sem passar
    por `_parse_rss_date`. Um valor que o Postgres rejeita (coluna TIMESTAMPTZ)
    faria o PostgREST devolver 400 e a linha INTEIRA se perder por causa de um
    campo acessório — melhor descartar só ele."""
    try:
        datetime.datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def log_sent_news(entry: dict) -> int | None:
    """Registro legível da notícia entregue como alerta.

    Devolve o `id` da linha inserida (None em falha) — a Parte B da sessão
    'noticias-ancoradas' (18/08/2026) precisa dele para gravar em
    `news_log_messages` qual mensagem, de qual destinatário, corresponde a
    qual notícia. `_client()` já manda `Prefer: return=representation`, então
    o POST devolve a linha inserida sem round-trip extra.

    Nunca estoura para o chamador: o alerta já foi ENVIADO quando isto roda,
    então falhar aqui não pode desfazer nem interromper o broadcast. A lista
    branca de campos existe porque uma chave fora do contrato faz o PostgREST
    devolver 400 e o registro se perder inteiro.
    """
    payload = {k: entry[k] for k in _NEWS_LOG_FIELDS if entry.get(k) is not None}
    if "publicado_em" in payload and not _iso_valido(payload["publicado_em"]):
        del payload["publicado_em"]
    payload["sent_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with _client() as c:
            r = c.post("/news_log", json=payload)
            r.raise_for_status()
            rows = r.json()
            return rows[0]["id"] if rows else None
    except Exception as e:
        # já foi entregue quando isto roda — não pode desfazer o broadcast, mas
        # não pode ficar mudo: sem isto, a migration não executada ou a escrita
        # falhando ficava invisível para sempre (achado A4, revisão 18/08/2026).
        logger.warning("news_log write failed: %s", e)
        return None


def update_news_log_conteudo(news_log_id: int, conteudo: str | None,
                             conteudo_fonte: str | None, url_final: str | None) -> None:
    """Preenche DEPOIS o texto da matéria (Conserto 1, 19/08/2026).

    `_check_news` grava a linha em `log_sent_news` ANTES de rodar a captura —
    a captura não tem teto REAL de tempo (`httpx.Timeout` é por OPERAÇÃO, não
    prazo absoluto: medido um servidor gotejando devolver em 15,25s reais para
    um pedido de 1,0s) e pode levar até 75s no caminho de render. Se a função
    da Vercel morrer nesse meio-tempo, a notícia já foi ENTREGUE — sem esta
    separação ela ficava sem marca de dedup, e o cron de 15 min reclassificava
    e reenviava a MESMA notícia ao usuário. Este UPDATE só acontece depois que
    o dedup já está garantido; se ele falhar, o pior caso é a notícia sem
    âncora de texto, nunca um reenvio.

    Só manda os campos não-None: `conteudo`/`conteudo_fonte`/`url_final` ausentes
    juntos (captura vazia) não fazem requisição nenhuma — nem tocam em `_client()`,
    que exigiria SUPABASE_URL/SUPABASE_KEY à toa. `id` vai CRU na query string
    (não passa por `_f()`): vem sempre do próprio `log_sent_news`, nunca de
    texto externo, mas `int()` é defesa contra um chamador futuro que passe
    outra coisa (mesmo cuidado de `clamp_int`).

    Nunca estoura para o chamador: a notícia já foi entregue e logada quando
    isto roda — mesma garantia do irmão `log_sent_news`.
    """
    payload: dict = {}
    if conteudo is not None:
        payload["conteudo"] = conteudo
    if conteudo_fonte is not None:
        payload["conteudo_fonte"] = conteudo_fonte
    if url_final is not None:
        payload["url_final"] = url_final
    if not payload:
        return
    try:
        with _client() as c:
            r = c.patch(f"/news_log?id=eq.{int(news_log_id)}", json=payload)
            r.raise_for_status()
    except Exception as e:
        logger.warning("news_log conteudo update failed: %s", e)


def log_alert_messages(news_log_id: int, pares: list[tuple[str, str | None]]) -> None:
    """Grava o id da mensagem ENVIADA, por destinatário (Parte B,
    'noticias-ancoradas', 18/08/2026) — cada destinatário recebe uma mensagem
    DIFERENTE da Evolution, com um id diferente; não cabe numa coluna só de
    `news_log`. É o que o webhook usa depois para casar `contextInfo.stanzaId`
    (a resposta citada) com a notícia exata, sem o modelo escolher entre uma
    lista.

    Entrada sem `message_id` (extração falhou ou a Evolution não devolveu
    `key.id`) é descartada — a coluna é NOT NULL. Nunca estoura para o
    chamador: a notícia já foi entregue e logada quando isto roda.
    """
    linhas = [
        {"news_log_id": news_log_id, "phone": phone, "message_id": message_id}
        for phone, message_id in pares
        if message_id
    ]
    if not news_log_id or not linhas:
        return
    try:
        with _client() as c:
            r = c.post("/news_log_messages", json=linhas)
            r.raise_for_status()
    except Exception as e:
        logger.warning("news_log_messages write failed: %s", e)


def get_news_by_message_id(message_id: str) -> dict | None:
    """Casa o id EXATO de uma mensagem enviada com a notícia que ela carregava
    (Parte C, 'noticias-ancoradas', 18/08/2026). Determinístico — comparação
    de string contra `news_log_messages.message_id`, não o modelo escolhendo
    entre candidatas. Id desconhecido (mensagem não é uma notícia, ou o
    registro já foi limpo) devolve None; o webhook segue sem ancorar nada.

    Duas consultas (não `select=news_log(*)` embutido do PostgREST) de
    propósito: mais fácil de simular em teste sem depender da FK ser
    reconhecida como relacionamento pelo PostgREST, e o caminho é raro o
    bastante (só quando alguém responde citando) para o round-trip extra não
    importar.
    """
    if not message_id or not str(message_id).strip():
        return None
    try:
        with _client() as c:
            r = c.get(
                f"/news_log_messages?message_id=eq.{_f(message_id)}"
                f"&select=news_log_id&limit=1"
            )
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return None
            news_log_id = rows[0]["news_log_id"]
            r2 = c.get(
                f"/news_log?id=eq.{_f(news_log_id)}"
                f"&select=titulo_pt,titulo_original,fonte,url,url_publisher,url_final,"
                f"categoria,resumo,resumo_fonte,direcao,score,ativos,"
                f"publicado_em,conteudo,conteudo_fonte,sent_at&limit=1"
            )
            r2.raise_for_status()
            rows2 = r2.json()
            return rows2[0] if rows2 else None
    except Exception as e:
        logger.warning("get_news_by_message_id failed: %s", e)
        return None


def clamp_int(value, minimo: int, maximo: int, default: int) -> int:
    """Trava genérica para inteiros que entram CRUS numa query PostgREST
    (`limit=`/`hours=` não passam por `_f()`, ao contrário de `cutoff`). Na
    Story 2 esses valores vêm de texto de WhatsApp interpretado pelo modelo —
    `limit="5&titulo_pt=eq.x"` é injeção de filtro, não um número grande."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimo, min(v, maximo))


def get_news_log(hours: int = 72, limit: int = 20, phone: str | None = None) -> dict:
    """Notícias entregues na janela, mais recentes primeiro.

    `phone` restringe ao que foi entregue ÀQUELE destinatário. Sem ele a
    resposta é a lista de alertas inteira, que não é a mesma coisa: só parte
    dos usuários autorizados tem `alerts_enabled`, e dizer "te mandei isto em
    19/08 às 13h05" para quem nunca recebeu é falso positivo autoritário — o
    espelho exato do A5 (achado 3 do Apolo, 20/08/2026).

    Devolve {"itens": [...]}; em falha, {"itens": [], "aviso": "..."} — a lista
    vazia sozinha não distingue "não houve notícia" de "o registro não
    respondeu", e a Story 2 usa isto como ferramenta do Claude: lista vazia
    lida como fato confirmado ("conferi, não enviei nada sobre X") é negativa
    autoritária e errada — pior que o incidente que esta tabela existe para
    corrigir (achado A5, revisão 18/08/2026).
    """
    hours = clamp_int(hours, 1, 24 * 90, 72)  # 90 dias = janela de retenção sugerida na migration
    limit = clamp_int(limit, 1, 100, 20)
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    try:
        with _client() as c:
            filtro_destinatario = ""
            if phone is not None:
                # Quem recebeu o quê mora em `news_log_messages` (uma linha por
                # destinatário); `news_log` não tem essa coluna. DUAS consultas
                # simples em vez de um embed PostgREST: é a mesma forma que
                # `get_news_by_message_id` já roda em produção, sem sintaxe nova
                # para falhar calada e derrubar a ferramenta inteira para todo
                # mundo de uma vez.
                r0 = c.get(
                    f"/news_log_messages?phone=eq.{_f(phone)}"
                    f"&sent_at=gte.{_f(cutoff)}&select=news_log_id"
                    f"&order=sent_at.desc&limit={limit}"
                )
                r0.raise_for_status()
                ids = {row["news_log_id"] for row in r0.json()}
                if not ids:
                    return {"itens": []}
                lista = ",".join(str(int(i)) for i in sorted(ids))
                filtro_destinatario = f"&id=in.({lista})"
            r = c.get(
                f"/news_log?select=news_id,titulo_pt,titulo_original,fonte,feed,url,"
                f"url_publisher,url_final,categoria,resumo,resumo_fonte,direcao,score,ativos,"
                f"publicado_em,sent_at"
                f"{filtro_destinatario}"
                f"&sent_at=gte.{_f(cutoff)}&order=sent_at.desc&limit={limit}"
            )
            r.raise_for_status()
            return {"itens": r.json()}
    except Exception as e:
        # sem isto, uma leitura falhando ficava invisível para sempre — o irmão
        # `log_sent_news` já loga a própria falha; este ficava mudo (achado A6,
        # revisão 18/08/2026).
        logger.warning("get_news_log failed: %s", e)
        return {"itens": [], "aviso": "registro indisponível"}


def count_recent_broadcasts(hours: int = 24) -> int:
    """Nº de notícias efetivamente enviadas (title não-nulo) na janela — sinal de vida."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    with _client() as c:
        r = c.get(
            f"/sent_news?select=news_id&title=not.is.null"
            f"&sent_at=gte.{_f(cutoff)}&limit=1",
            headers={"Prefer": "count=exact"},
        )
        r.raise_for_status()
        content_range = r.headers.get("content-range", "*/0")
        try:
            return int(content_range.split("/")[1])
        except (IndexError, ValueError):
            return 0


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


def get_all_config() -> list[dict]:
    """Lê todas as linhas da tabela agent_config (key/value)."""
    with _client() as c:
        r = c.get("/agent_config?select=key,value")
        r.raise_for_status()
        return r.json()


def list_authorized() -> list[dict]:
    """Lista todos os usuários autorizados (phone + name)."""
    with _client() as c:
        r = c.get("/authorized_users?select=phone,name&order=phone.asc")
        r.raise_for_status()
        return r.json()


def set_selflink_token(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"selflink_token": token})
        r.raise_for_status()
    return token


def clear_selflink_token(phone: str) -> None:
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"selflink_token": None})
        r.raise_for_status()


def get_by_selflink_token(token: str) -> dict | None:
    if not token or not str(token).strip():
        return None
    with _client() as c:
        r = c.get(f"/authorized_users?selflink_token=eq.{_f(token)}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def upsert_config(key: str, value) -> None:
    with _client() as c:
        r = c.post(
            "/agent_config",
            json={"key": key, "value": value},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def delete_config(key: str) -> None:
    with _client() as c:
        r = c.delete(f"/agent_config?key=eq.{_f(key)}")
        r.raise_for_status()
