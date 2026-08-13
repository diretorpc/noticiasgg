"""Prova que a trava de rede do conftest funciona.

Uma trava que ninguém testa quebra em silêncio: o dia em que ela parar de
disparar, o marcador `unit` volta a poder mentir e ninguém percebe.
"""
import asyncio
import socket

import pytest

from backend.tests._trava_rede import RedeProibida


@pytest.mark.unit
def test_trava_recusa_conexao_externa_em_teste_unit():
    s = socket.socket()
    try:
        with pytest.raises(RedeProibida, match="tentou acessar a rede"):
            s.connect(("1.1.1.1", 80))
    finally:
        s.close()


@pytest.mark.unit
def test_trava_nao_e_engolida_por_except_exception():
    """O defeito mais perigoso que esta trava já teve: ela sinalizava com
    AssertionError, e o backend é todo `except Exception` tolerante
    (_safe_collect). O aviso era engolido, virava {"erro": ...} e o teste
    passava VERDE com dado inventado. Herdar de BaseException é o conserto —
    este teste é o que impede alguém de 'simplificar' isso de volta."""
    s = socket.socket()
    try:
        with pytest.raises(RedeProibida):
            try:
                s.connect(("1.1.1.1", 80))
            except Exception:  # exatamente o que o código de produção faz
                pytest.fail("a trava foi engolida por `except Exception`")
    finally:
        s.close()


@pytest.mark.unit
def test_trava_cobre_connect_ex():
    """connect_ex devolve código de erro em vez de levantar exceção: sem
    cobri-lo, um teste `unit` sairia para a rede sem a trava piscar."""
    s = socket.socket()
    try:
        with pytest.raises(RedeProibida):
            s.connect_ex(("1.1.1.1", 80))
    finally:
        s.close()


@pytest.mark.unit
async def test_trava_cobre_conexao_assincrona():
    """No Windows o caminho assíncrono não passa por socket.connect — a trava
    ficava mais fraca na máquina do dono do que no CI (Linux). `polls_br.py` é
    todo assíncrono, então era exatamente o coletor desprotegido."""
    with pytest.raises(RedeProibida):
        await asyncio.open_connection("1.1.1.1", 80)


def test_trava_nao_atrapalha_teste_sem_marcador():
    """Contrapeso: sem o marcador `unit`, a rede continua liberada — é assim
    que os testes de contrato contra API real seguem funcionando."""
    s = socket.socket()
    try:
        s.settimeout(5)
        s.connect(("1.1.1.1", 80))
    except OSError as e:  # sem internet na máquina: não é falha do teste
        pytest.skip(f"sem conectividade para exercer o contrapeso: {e}")
    else:
        s.close()
