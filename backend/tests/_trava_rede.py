"""Trava que reprova teste marcado `unit` se ele abrir conexão para fora.

Por que este código NÃO mora no conftest.py: o pytest carrega aquele arquivo em
DUAS cópias distintas em memória — `tests.conftest` (a que ele registra como
plugin) e `backend.tests.conftest` (a que os arquivos de teste importam),
consequência de existir `backend/tests/__init__.py` sem `backend/__init__.py`.
Duas cópias significavam trava instalada em dobro e DUAS classes `RedeProibida`
diferentes, então `pytest.raises(RedeProibida)` não reconhecia o erro levantado.
Aqui, importado sempre pelo caminho absoluto, o módulo é um só.

O QUE ESTA TRAVA **NÃO** PEGA (medido em 13/08/2026; tudo latente, zero
ocorrência no portão do CI de hoje — mas não confie nela como garantia total):

- **Exceção engolida por `asyncio.gather(return_exceptions=True)`.** Herdar de
  BaseException protege do `except Exception`, não disto. O padrão existe em
  produção: `collectors/polls_br.py:285` e `:300`.
- **Rede aberta dentro de thread.** A conexão É barrada, mas a exceção não sobe
  para o teste, que segue verde com o caminho degradado. Alvo: `polls_br.py:326`
  (`pool.submit`). O TestClient do FastAPI NÃO cai nisto — foi medido.
- **Conexão já aberta antes do teste.** A trava vigia a ABERTURA, não o uso: um
  cliente httpx guardado em nível de módulo reaproveita conexão viva e atravessa.
- **Consulta de nome (DNS) e envio UDP.** Por isso a promessa aqui é "sem
  conexão externa", não "sem rede": um teste `unit` ainda pode ficar parado
  esperando uma resolução de nome lenta.
"""
import socket

_LOCAL = {"127.0.0.1", "::1", "localhost", ""}


class RedeProibida(BaseException):
    """Herda de BaseException DE PROPÓSITO, não de Exception.

    O backend é construído sobre `except Exception` tolerante
    (`report_engine._safe_collect`, o try/except por ativo do `market.py`). Se
    esta trava sinalizasse com AssertionError, o próprio código de produção
    engoliria o aviso e devolveria `{"erro": "...", "preco": None}` — o teste
    passaria verde, com dado inventado, e a trava viraria enfeite."""


_unit_nodes: set[str] = set()
_teste_atual: dict[str, str | None] = {"nodeid": None}
_instalada = False


def registrar_unit(nodeid: str) -> None:
    _unit_nodes.add(nodeid)


def marcar_inicio(nodeid: str) -> None:
    _teste_atual["nodeid"] = nodeid


def marcar_fim() -> None:
    _teste_atual["nodeid"] = None


def _liberado(sock, address) -> bool:
    if getattr(sock, "family", None) == getattr(socket, "AF_UNIX", object()):
        return True  # soquete de arquivo local (Linux/CI) não é rede
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, (bytes, bytearray)):
        host = host.decode("utf-8", "replace")
    return str(host) in _LOCAL


def _embrulhar(nome: str) -> None:
    original = getattr(socket.socket, nome)

    def _fiscal(self, address, *args, **kwargs):
        if _teste_atual["nodeid"] in _unit_nodes and not _liberado(self, address):
            raise RedeProibida(
                f"teste marcado @pytest.mark.unit tentou acessar a rede ({address}). "
                "Simule a chamada, ou tire o marcador `unit` deste teste."
            )
        return original(self, address, *args, **kwargs)

    setattr(socket.socket, nome, _fiscal)


def _embrulhar_windows_assincrono() -> None:
    """No Windows, conexão assíncrona usa `ConnectEx` do sistema e NÃO passa por
    socket.connect. Sem isto a trava seria mais fraca na máquina do Matheus do
    que no CI (Linux, onde passa) — e `collectors/polls_br.py` é todo assíncrono."""
    try:
        from asyncio.windows_events import IocpProactor
    except ImportError:
        return  # não é Windows: o motor de lá já cai no socket.connect

    original = IocpProactor.connect

    def _fiscal(self, conn, address):
        if _teste_atual["nodeid"] in _unit_nodes and not _liberado(conn, address):
            raise RedeProibida(
                f"teste marcado @pytest.mark.unit tentou acessar a rede de forma "
                f"assíncrona ({address}). Simule a chamada, ou tire o marcador `unit`."
            )
        return original(self, conn, address)

    IocpProactor.connect = _fiscal


def instalar() -> None:
    """Idempotente: chamar duas vezes não empilha dois fiscais."""
    global _instalada
    if _instalada:
        return
    _instalada = True
    _embrulhar("connect")
    _embrulhar("connect_ex")  # devolve código de erro, não levanta — passava batido
    _embrulhar_windows_assincrono()
