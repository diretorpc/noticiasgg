import os
from unittest.mock import patch

import httpx

from backend.services import whatsapp

_ENV = {
    "EVOLUTION_API_URL": "http://fake:8080",
    "EVOLUTION_API_KEY": "k",
    "EVOLUTION_INSTANCE": "noticiasgg",
}


def test_connection_state_extrai_state_do_payload():
    def fake_handle(self, request):
        assert "/instance/connectionState/noticiasgg" in str(request.url)
        return httpx.Response(200, json={"instance": {"instanceName": "noticiasgg", "state": "open"}})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        assert whatsapp.connection_state() == "open"


def test_connection_state_payload_plano():
    def fake_handle(self, request):
        return httpx.Response(200, json={"state": "connecting"})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        assert whatsapp.connection_state() == "connecting"
