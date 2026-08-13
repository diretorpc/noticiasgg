"""Mede quantas conexões externas a suíte de testes abre, e quem abre.

Por que existe: em 13/08/2026 a suíte falhava de forma intermitente por bloqueio
de cota (rate limit) das APIs de fornecedor. Ler o código não bastava para saber
quem batia na internet — dois inventários feitos por leitura erraram. Só a
medição resolveu. Este arquivo é essa medição, para não precisar improvisar de novo.

Uso:
    python -m pytest backend/tests/ -q -p backend.tools.medir_rede_testes

Rodar um arquivo isolado é o que revela a verdade sobre AQUELE arquivo: na suíte
inteira, a configuração já vem guardada em memória e a conexão é atribuída a
quem chegou primeiro, não a quem depende dela.

    python -m pytest backend/tests/test_crypto.py -q -p backend.tools.medir_rede_testes
"""
import collections
import socket

_LOCAL = {"127.0.0.1", "::1", "localhost", ""}

_conectar_original = socket.socket.connect
_teste_atual = {"nodeid": None}
_contagem = collections.defaultdict(collections.Counter)


def _espiao(self, address):
    nodeid = _teste_atual["nodeid"]
    host = address[0] if isinstance(address, tuple) else str(address)
    if nodeid and host not in _LOCAL:
        _contagem[nodeid][host] += 1
    return _conectar_original(self, address)


socket.socket.connect = _espiao


def pytest_runtest_logstart(nodeid, location):
    _teste_atual["nodeid"] = nodeid


def pytest_runtest_logfinish(nodeid, location):
    _teste_atual["nodeid"] = None


def pytest_sessionfinish(session, exitstatus):
    total = 0
    print("\n\n===== CONEXOES EXTERNAS POR TESTE =====")
    for nodeid in sorted(_contagem):
        hosts = _contagem[nodeid]
        n = sum(hosts.values())
        total += n
        detalhe = ", ".join(f"{h} x{v}" for h, v in hosts.most_common(6))
        print(f"{n:4d}  {nodeid}\n      -> {detalhe}")
    print(f"\nTOTAL de conexoes externas: {total}")
    print(f"TOTAL de testes que tocam a rede: {len(_contagem)}")
