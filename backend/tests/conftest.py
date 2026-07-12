import pytest


@pytest.fixture(autouse=True)
def _admin_allowlist(monkeypatch):
    """Allowlist de admin padrão para os testes que exercem rotas /api/admin.
    Testes que precisam do estado 'sem allowlist' sobrescrevem localmente."""
    monkeypatch.setenv("ADMIN_EMAILS", "matheusmouro@hotmail.com")
