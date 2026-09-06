"""Constantes compartilhadas entre `conftest.py` e arquivos de teste.

Por que NÃO mora em `conftest.py`: o pytest carrega aquele arquivo em DUAS
cópias distintas em memória (`tests.conftest` e `backend.tests.conftest` —
ver o aviso no topo dele e o mesmo motivo documentado em `_trava_rede.py`).
Um valor definido lá dentro existe em dobro; um módulo à parte, importado
sempre pelo caminho absoluto `backend.tests._constantes`, é um só.
"""

# Placeholder que a fixture autouse `_chave_anthropic_de_teste` (conftest.py)
# injeta em `ANTHROPIC_API_KEY` quando a chave real não existe no ambiente
# (caso do CI). Os smoke tests que chamam o Claude de verdade (ex.:
# `test_alert_checker_smoke.py`) usam esta MESMA constante para pular com uma
# mensagem clara em vez de estourar autenticação — antes de existir este
# módulo, a string vivia hardcoded em dois lugares (item 6, 4ª revisão do
# Apolo, 05/09/2026): uma trocada sem a outra reabriria o buraco calado.
CHAVE_ANTHROPIC_PLACEHOLDER = "chave-de-teste-sem-valor-real"
