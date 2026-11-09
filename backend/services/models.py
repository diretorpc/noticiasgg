"""Nome dos modelos da Anthropic — fonte única, vinda do ambiente.

Quem aposenta modelo é a Anthropic, na hora que ela quiser; por isso o nome mora em
variável de ambiente e não no código. Lido a cada chamada (não no import) para a troca
valer sem depender de ordem de import, e para teste poder trocar com `patch.dict`.

Variável vazia cai no padrão: criada na Vercel e deixada em branco, ela não pode virar
`model=""`. Nome errado na variável, ao contrário, quebra tudo que usa o modelo — a
sonda do boletim diário (`anthropic_status.sondar`) testa os dois e diz qual trocar.
"""
import os

_HAIKU_PADRAO = "claude-haiku-4-5-20251001"
_SONNET_PADRAO = "claude-sonnet-4-6"


def _do_ambiente(variavel: str, padrao: str) -> str:
    return (os.getenv(variavel) or "").strip() or padrao


def haiku() -> str:
    """Modelo barato: leitor de preferências, validador, resumo, classificador, sonda."""
    return _do_ambiente("ANTHROPIC_HAIKU_MODEL", _HAIKU_PADRAO)


def sonnet() -> str:
    """Modelo do chat e do relatório."""
    return _do_ambiente("ANTHROPIC_SONNET_MODEL", _SONNET_PADRAO)
