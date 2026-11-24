"""Vigia externo: o alarme que NÃO viaja pelo WhatsApp.

Incidentes que justificam isto: 04/09/2026 (~35 h mudo) e 19–24/11/2026 (~5 dias
mudo). Nos dois, `/api/health` marcava `evolution: warn` — o sistema SABIA — mas o
boletim e o `notify_admin` saem pelo WhatsApp, que era justamente o que tinha caído.

Regra do alarme (de propósito estreita, para não gritar à toa):
  toca  = backend fora / resposta ilegível / Evolution com estado != "open"
  quieto = qualquer outro `warn`/`error` — esses o boletim diário já conta pelo
           WhatsApp, que nesse caso está funcionando.
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from backend.services import health
from backend.tools import vigia_externo as v

pytestmark = pytest.mark.unit


# Corpo REAL devolvido por produção em 24/11/2026 20:35 UTC, com o bot mudo.
_PRODUCAO_24_11 = json.dumps({
    "status": "warn",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "ok", "titulos_24h": 0},
        "broadcasts": {"status": "ok", "enviados_24h": 0},
        "news_log": {"status": "ok", "broadcasts_24h": 0, "registrado": False,
                     "entregas_registradas": 0},
        "evolution": {"status": "warn", "estado": "close"},
    },
    "checked_at": "2026-11-24T20:35:53.145271+00:00",
})


def _corpo(evolution: dict, status: str = "ok") -> str:
    return json.dumps({"status": status, "checks": {"evolution": evolution}})


# ── avaliar: a regra, sem rede ───────────────────────────────────────────────

def test_incidente_real_de_24_11_toca_o_alarme():
    motivo = v.avaliar(200, _PRODUCAO_24_11)
    assert motivo is not None
    assert "close" in motivo


def test_whatsapp_aberto_fica_quieto():
    assert v.avaliar(200, _corpo({"status": "ok", "estado": "open"})) is None


def test_outro_warn_com_whatsapp_aberto_fica_quieto():
    # Supabase soluçou, fonte morta etc.: o boletim diário avisa pelo WhatsApp,
    # que está de pé. O vigia externo não deve duplicar nem gritar por isso.
    corpo = json.dumps({"status": "warn", "checks": {
        "dedup": {"status": "error", "message": "timeout"},
        "evolution": {"status": "ok", "estado": "open"},
    }})
    assert v.avaliar(200, corpo) is None


def test_evolution_inalcancavel_sem_estado_toca():
    # `connection_state` levantou (VPS fora, porta errada): o health devolve
    # `message` e nenhum `estado`. Foi a forma do incidente de 04/09 (404).
    motivo = v.avaliar(200, _corpo({"status": "warn", "message": "404 Not Found"}))
    assert motivo is not None
    assert "404" in motivo


def test_connecting_persistente_toca():
    assert v.avaliar(200, _corpo({"status": "warn", "estado": "connecting"})) is not None


def test_sem_check_evolution_toca():
    # Se alguém renomear/remover o check, o vigia não pode virar verde calado.
    assert v.avaliar(200, json.dumps({"status": "ok", "checks": {}})) is not None


@pytest.mark.parametrize("codigo", [500, 502, 404, 401])
def test_backend_com_http_ruim_toca(codigo):
    motivo = v.avaliar(codigo, "")
    assert motivo is not None
    assert str(codigo) in motivo


def test_backend_inalcancavel_toca():
    assert v.avaliar(None, "") is not None


@pytest.mark.parametrize("corpo", ["<html>Vercel error</html>", "", "[]", "null"])
def test_corpo_ilegivel_toca(corpo):
    assert v.avaliar(200, corpo) is not None


def test_motivo_nunca_ecoa_corpo_gigante():
    # O motivo vai para o resumo público do GitHub Actions (repo público).
    corpo = _corpo({"status": "warn", "message": "x" * 5000})
    assert len(v.avaliar(200, corpo)) < 400


# ── contrato: produtor (health.collect_status) × consumidor (vigia) ──────────
# Sem isto o teste acima poderia inventar o formato e passar com o health real
# mudado (lição do lote 2, 09/09/2026).

def _health_real(estado=None, erro=None) -> str:
    cs = {"side_effect": erro} if erro else {"return_value": estado}
    with patch("backend.services.health._check_keys",
               return_value={"status": "ok", "faltando": []}), \
         patch.multiple(
             "backend.services.health.supabase",
             get_recent_sent_titles=lambda *a, **k: [],
             count_recent_alert_messages=lambda *a, **k: 0,
             count_recent_broadcasts=lambda *a, **k: 0,
             get_news_log=lambda *a, **k: {"itens": []},
         ), patch("backend.services.health.whatsapp.connection_state", **cs):
        return json.dumps(health.collect_status())


def test_contrato_health_real_aberto_fica_quieto():
    assert v.avaliar(200, _health_real("open")) is None


def test_contrato_health_real_fechado_toca():
    assert v.avaliar(200, _health_real("close")) is not None


def test_contrato_health_real_evolution_explodindo_toca():
    assert v.avaliar(200, _health_real(erro=RuntimeError("Connection refused"))) is not None


# ── checar: repetição antes de tocar (soluço não vira e-mail) ────────────────

def _buscador(respostas):
    chamadas = []

    def buscar(url):
        chamadas.append(url)
        return respostas[min(len(chamadas), len(respostas)) - 1]
    return buscar, chamadas


_OK = (200, _corpo({"status": "ok", "estado": "open"}))
_RUIM = (200, _corpo({"status": "warn", "estado": "close"}))


def test_checar_ok_de_primeira_nao_espera():
    buscar, chamadas = _buscador([_OK])
    esperas = []
    assert v.checar("u", buscar=buscar, dormir=esperas.append) is None
    assert len(chamadas) == 1 and esperas == []


def test_checar_soluco_que_se_recupera_fica_quieto():
    buscar, chamadas = _buscador([_RUIM, _OK])
    esperas = []
    assert v.checar("u", tentativas=3, espera=90, buscar=buscar,
                    dormir=esperas.append) is None
    assert len(chamadas) == 2 and esperas == [90]


def test_checar_falha_persistente_toca_depois_de_todas_as_tentativas():
    buscar, chamadas = _buscador([_RUIM])
    esperas = []
    motivo = v.checar("u", tentativas=3, espera=90, buscar=buscar, dormir=esperas.append)
    assert motivo is not None and "close" in motivo
    assert len(chamadas) == 3 and esperas == [90, 90]


# ── main: código de saída é o que faz o GitHub mandar o e-mail ───────────────

def test_main_sai_1_quando_toca(monkeypatch, tmp_path):
    resumo = tmp_path / "resumo.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))
    monkeypatch.setattr(v, "checar", lambda *a, **k: "WhatsApp do robô: estado 'close'")
    assert v.main([]) == 1
    assert "close" in resumo.read_text(encoding="utf-8")


def test_main_sai_0_quando_saudavel(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(v, "checar", lambda *a, **k: None)
    assert v.main([]) == 0


def test_main_simular_queda_sai_1_sem_tocar_na_rede(monkeypatch):
    # Prova de ponta a ponta do e-mail: rodar à mão com a queda simulada.
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(v, "checar", lambda *a, **k: pytest.fail("não deveria buscar"))
    assert v.main(["--simular-queda"]) == 1


# ── _buscar: rede de verdade, só em 127.0.0.1 (a trava de rede libera loopback) ──
# Sem estes, 3 mutantes do Apolo (24/11) sobreviviam: devolver 200 em erro HTTP,
# devolver "saudável" em falha de rede, e perder o corpo.

def _servidor(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/api/health"


def _handler(status: int, corpo: bytes, content_length: int | None = None):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Length",
                             str(len(corpo) if content_length is None else content_length))
            self.end_headers()
            self.wfile.write(corpo)
            self.close_connection = True

        def log_message(self, *a):
            pass
    return H


def test_buscar_devolve_codigo_e_corpo():
    srv, url = _servidor(_handler(200, b'{"ok": 1}'))
    try:
        assert v._buscar(url) == (200, '{"ok": 1}')
    finally:
        srv.shutdown()
        srv.server_close()


def test_buscar_erro_http_devolve_o_codigo_nao_200():
    srv, url = _servidor(_handler(500, b"boom"))
    try:
        assert v._buscar(url) == (500, "")
    finally:
        srv.shutdown()
        srv.server_close()


def test_buscar_conexao_recusada_devolve_none():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()  # porta livre e ninguém escutando → recusa
    assert v._buscar(f"http://127.0.0.1:{porta}/api/health") == (None, "")


def test_buscar_corpo_cortado_no_meio_nao_escapa():
    # 200 com Content-Length 500 e conexão fechada depois de 3 bytes →
    # http.client.IncompleteRead, que NÃO é OSError. Escapava do `checar` e virava
    # e-mail sem as repetições (achado 4 do Apolo, 24/11/2026).
    srv, url = _servidor(_handler(200, b"abc", content_length=500))
    try:
        assert v._buscar(url) == (None, "")
    finally:
        srv.shutdown()
        srv.server_close()


def test_checar_corpo_cortado_repete_antes_de_tocar():
    srv, url = _servidor(_handler(200, b"abc", content_length=500))
    esperas = []
    try:
        motivo = v.checar(url, tentativas=2, espera=0, dormir=esperas.append)
    finally:
        srv.shutdown()
        srv.server_close()
    assert motivo is not None and esperas == [0]
