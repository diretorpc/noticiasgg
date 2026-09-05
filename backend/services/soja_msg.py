"""Monta a mensagem diária "Soja Disponível" (spec fechada em 04/09/2026,
ver ESTADO.md) — formato FIXO, montado por CÓDIGO, nunca pelo modelo.

`montar()` é PURA: recebe números já resolvidos e devolve a string exata.
`gerar()` é a orquestração: chama `soja_disponivel.collect()` (Porto/CBOT/
dólar) e `soja_fretes.describe()` (fretes editáveis no painel), nunca levanta.
"""
import math
from decimal import ROUND_HALF_UP, Decimal

from backend.collectors import soja_disponivel
from backend.services import soja_fretes
from backend.services.secrets_mask import sanitize_error

_ROTULO_PORTO = "Porto 🌱🛳️"
_ROTULO_DOLAR = "💵"
_ROTULO_CBOT_INDISPONIVEL = "🇺🇸🌱CBOT"
_INDISPONIVEL = "indisponível"


def formatar_brl(v: float | None, casas: int = 2) -> str | None:
    """Vírgula decimal, sem separador de milhar (os valores aqui são < 1000).

    Arredondamento MEIO PARA CIMA (o que o primo espera), sobre o texto do
    número — não `f"{v:.Nf}"`. `float` não representa exatamente casas
    decimais em base 2 (`12.9425` é armazenado como algo ligeiramente menor),
    e `f"{12.9425:.3f}"` pode arredondar para baixo por causa disso.
    `Decimal(str(v))` parte da representação DECIMAL que o Python já escolheu
    para mostrar o float (a mais curta que reproduz o mesmo valor), então o
    arredondamento subsequente bate com o que um humano leria no número.

    Devolve `None` quando `v` é `None` ou não é finito (`NaN`/`±inf`, achado
    7) — `Decimal(str(float("nan")))` não levanta, mas produz um `Decimal`
    especial que `quantize()` rejeita mais adiante; melhor recusar aqui e
    deixar `montar()` trocar por "indisponível" do que deixar o valor
    corrompido correr mundo.
    """
    if v is None or not math.isfinite(v):
        return None
    quantizador = Decimal(1).scaleb(-casas)
    q = Decimal(str(v)).quantize(quantizador, rounding=ROUND_HALF_UP)
    return f"{q:.{casas}f}".replace(".", ",")


def _praca(porto: float, frete: float) -> float | None:
    """Porto − frete, mas só quando dá um preço de praça plausível (> 0).

    Frete maior ou igual ao Porto (achado 2, 2ª revisão do Apolo: ex.
    Canarana com frete 200 e Porto 159,44 = −40,56) não é uma praça real —
    é erro de cadastro no painel (frete > Porto do dia). Melhor
    "indisponível" do que deixar um preço negativo passar como fato.

    Reaproveitada por `montar()` (texto) e por `gerar()` (diagnóstico —
    achado 2) para não duplicar a regra `<= 0`.
    """
    valor = porto - frete
    return valor if valor > 0 else None


def montar(
    porto: float | None,
    fretes: dict,
    dolar: float | None,
    cbot: dict | None,
) -> str:
    """Monta a mensagem exata. PURA — nunca chama rede nem levanta por conta
    própria. `cbot` = {"rotulo": str, "preco_usd_bushel": float} ou None.

    Porto indisponível (`None`) derruba as 3 praças junto (Porto − frete não
    existe sem Porto). Frete específico faltando na dict derruba só a praça
    dele. Dólar e CBOT falham cada um sozinho.
    """
    linhas = ["Soja Disponível", ""]

    # `porto_fmt` (não `porto is None`) decide: um `porto` corrompido (NaN,
    # achado 7) passa no `is None` mas não é número exibível — `formatar_brl`
    # já recusa os dois casos, então checar o RESULTADO cobre ambos.
    porto_fmt = formatar_brl(porto)
    if porto_fmt is None:
        linhas.append(f"{_ROTULO_PORTO} = {_INDISPONIVEL}")
        for _chave, rotulo, _default in soja_fretes.PRACAS:
            linhas.append(f"{rotulo} = {_INDISPONIVEL}")
    else:
        linhas.append(f"{_ROTULO_PORTO} = {porto_fmt}")
        for chave, rotulo, _default in soja_fretes.PRACAS:
            frete = fretes.get(chave)
            praca_valor = None if frete is None else _praca(porto, frete)
            praca_fmt = None if praca_valor is None else formatar_brl(praca_valor)
            linhas.append(f"{rotulo} = {praca_fmt if praca_fmt is not None else _INDISPONIVEL}")

    linhas.append("")

    dolar_fmt = formatar_brl(dolar, casas=3)
    linhas.append(f"{_ROTULO_DOLAR} = {dolar_fmt if dolar_fmt is not None else _INDISPONIVEL}")

    if cbot is None:
        linhas.append(f"{_ROTULO_CBOT_INDISPONIVEL} = {_INDISPONIVEL}")
    else:
        preco = formatar_brl(cbot["preco_usd_bushel"], casas=3)
        if preco is None:
            linhas.append(f"{_ROTULO_CBOT_INDISPONIVEL} = {_INDISPONIVEL}")
        else:
            linhas.append(f"🇺🇸🌱{cbot['rotulo']} = {preco}/bushel")

    return "\n".join(linhas)


def _avisos_fretes(desc: dict) -> list[str]:
    """Mensagens curtas para o painel a partir de `soja_fretes.describe()` —
    independentes do texto do boletim (`health._check_soja_fretes`): público
    e propósito diferentes (aviso na tela de prévia × linha do boletim
    administrativo). `describe()` já sanitiza qualquer erro de fornecedor."""
    avisos: list[str] = []
    if desc.get("erro"):
        # Corta aqui (achado 5): o fallback de `describe()` em erro também
        # carrega `envelhecido=True`/`is_custom=False` (formato do dict de
        # erro) — sem o `return`, o ramo abaixo somaria "nunca foram salvos"
        # ao lado do aviso de erro, dois avisos que se contradizem.
        avisos.append(f"fretes: {desc['erro']}")
        return avisos
    if desc.get("aviso"):
        avisos.append(f"fretes: {desc['aviso']}")
    if desc.get("envelhecido"):
        if not desc.get("is_custom"):
            avisos.append(
                f"fretes nunca foram salvos no painel — usando padrão "
                f"{soja_fretes.descrever_defaults()}"
            )
        else:
            idade = desc.get("idade_dias")
            sufixo = f" há {idade} dias" if idade is not None else ""
            avisos.append(f"fretes desatualizados{sufixo} (>60 dias)")
    return avisos


def _marcar(indisponiveis: list[str], nome: str) -> None:
    """Acrescenta `nome` a `indisponiveis` sem duplicar — mais de uma causa
    pode apontar pro mesmo bloco ao mesmo tempo (ex.: Porto inválido cascateia
    pras praças E o describe() também veio vazio)."""
    if nome not in indisponiveis:
        indisponiveis.append(nome)


def gerar() -> dict:
    """Orquestra coleta + fretes e monta o texto final. Nunca levanta — cada
    bloco falhando vira `indisponível` na mensagem e entra em `indisponiveis`;
    fretes envelhecidos/inválidos/com erro entram em `avisos`."""
    avisos: list[str] = []
    indisponiveis: list[str] = []

    try:
        dados = soja_disponivel.collect()
    except Exception as e:
        avisos.append(f"coleta: {sanitize_error(e)}")
        dados = {}

    porto_bloco = dados.get("porto") or {"erro": "bloco ausente"}
    cbot_bloco = dados.get("cbot") or {"erro": "bloco ausente"}
    dolar_bloco = dados.get("dolar") or {"erro": "bloco ausente"}

    # achado 1 (2ª revisão do Apolo): os guardas abaixo usam `formatar_brl`
    # — a MESMA função que `montar()` chama pra decidir "indisponível" — em
    # vez de reimplementar a checagem com `.get(...) is None`. Isso cobre
    # `None` E valor corrompido (NaN/±inf, achado 7 da 1ª revisão) com uma
    # única regra: se `montar()` vai mostrar "indisponível", o guarda aqui
    # também vê. Divergência texto × `indisponiveis` fica impossível por
    # construção, não por promessa.
    porto: float | None = None
    porto_data_ref: str | None = None
    porto_valor = porto_bloco.get("preco")
    if "erro" in porto_bloco or formatar_brl(porto_valor) is None:
        _marcar(indisponiveis, "Porto")
        # Porto indisponível derruba as 3 praças em `montar()` (Porto − frete
        # não existe sem Porto) — marca o bloco das praças também, pra não
        # deixar 4 linhas "indisponível" no texto com 1 só entrada explicando.
        _marcar(indisponiveis, "Praças (fretes)")
    else:
        porto = porto_valor
        porto_data_ref = porto_bloco.get("data_ref")

    dolar: float | None = None
    dolar_atualizado_em = None
    dolar_valor = dolar_bloco.get("preco")
    if "erro" in dolar_bloco or formatar_brl(dolar_valor, casas=3) is None:
        _marcar(indisponiveis, "Dólar")
    else:
        dolar = dolar_valor
        dolar_atualizado_em = dolar_bloco.get("atualizado_em")

    cbot: dict | None = None
    cbot_simbolo: str | None = None
    cbot_atualizado_em = None
    cbot_preco = cbot_bloco.get("preco_usd_bushel")
    cbot_rotulo = cbot_bloco.get("rotulo")
    if "erro" in cbot_bloco or formatar_brl(cbot_preco, casas=3) is None or cbot_rotulo is None:
        _marcar(indisponiveis, "CBOT")
    else:
        cbot = {"rotulo": cbot_rotulo, "preco_usd_bushel": cbot_preco}
        cbot_simbolo = cbot_bloco.get("simbolo")
        cbot_atualizado_em = cbot_bloco.get("atualizado_em")

    try:
        fretes_desc = soja_fretes.describe()
    except Exception as e:
        fretes_desc = {"erro": sanitize_error(e)}

    avisos.extend(_avisos_fretes(fretes_desc))

    # achado 1: `describe()` fora do ar (ou com valor salvo corrompido/
    # parcial) devolve `fretes` com DEFAULTS — nunca vazio, é o contrato dela.
    # `gerar()` não pode montar as 3 praças com esses defaults calado (não dá
    # pra saber se são 9/12/27 de verdade ou só o fallback); passa `{}` e
    # deixa `montar()` derrubar as 3 praças como fez para o Porto.
    fretes: dict
    if fretes_desc.get("erro") or fretes_desc.get("aviso"):
        fretes = {}
    else:
        fretes = fretes_desc.get("fretes") or {}

    # achado 1-c (2ª revisão): checagem única após decidir `fretes` — cobre
    # tanto o ramo de erro/aviso acima QUANTO um `describe()` malformado sem
    # a chave "fretes" (sem `erro` nem `aviso`), que antes derrubava as 3
    # praças no texto calado, sem entrar aqui.
    # Completude, não só vazio: dict PARCIAL (sem uma chave) derrubaria a praça
    # no texto sem entrar aqui — 3ª revisão do Apolo, 04/09.
    if any(chave not in fretes for chave, _r, _d in soja_fretes.PRACAS):
        _marcar(indisponiveis, "Praças (fretes)")

    # achado 2 (2ª revisão): fretes numericamente válidos (0 < x <= 200, já
    # passaram por `soja_fretes.validar`/`describe`) ainda podem produzir uma
    # praça <= 0 quando o frete do dia é maior que o Porto (ex.: Canarana com
    # frete 200 e Porto 159,44 = −40,56). `_praca()` é a MESMA regra que
    # `montar()` usa pra render — reaproveitada aqui só pro diagnóstico, sem
    # duplicar o `<= 0`. `break` no primeiro achado: um aviso já basta, o
    # texto mostra qual praça específica caiu.
    if porto is not None and fretes:
        for chave, _rotulo, _default in soja_fretes.PRACAS:
            frete = fretes.get(chave)
            if frete is not None and _praca(porto, frete) is None:
                _marcar(indisponiveis, "Praças (fretes)")
                avisos.append("frete maior que o Porto: confira o painel")
                break

    try:
        texto = montar(porto, fretes, dolar, cbot)
    except Exception as e:
        # Nunca deveria acontecer com os guardas acima, mas `montar()` monta
        # texto pro usuário final — degradar tudo (nunca estourar o webhook
        # nem o painel) vale mais que confiar cegamente nos guardas de cima.
        # Texto de emergência montado NA MÃO (não chamando `montar()` de
        # novo) — se o que quebrou foi a própria `montar()`, chamá-la outra
        # vez com entrada "segura" reproduziria o mesmo estouro.
        avisos.append(f"render: {sanitize_error(e)}")
        linhas_seguras = ["Soja Disponível", "", f"{_ROTULO_PORTO} = {_INDISPONIVEL}"]
        for _chave, rotulo, _default in soja_fretes.PRACAS:
            linhas_seguras.append(f"{rotulo} = {_INDISPONIVEL}")
        linhas_seguras.append("")
        linhas_seguras.append(f"{_ROTULO_DOLAR} = {_INDISPONIVEL}")
        linhas_seguras.append(f"{_ROTULO_CBOT_INDISPONIVEL} = {_INDISPONIVEL}")
        texto = "\n".join(linhas_seguras)
        # achado 1-a (2ª revisão): a montagem em si falhou — não dá pra
        # confiar em NENHUM metadado calculado até aqui (pode ter sido
        # justamente o que quebrou `montar()`, ou os dados podem ter sido
        # bons mas o texto exibido agora é o de emergência, todo
        # "indisponível"). Zera os metadados e declara os 4 blocos, mesmo que
        # algum tivesse passado no guarda acima — os metadados têm que bater
        # com o texto que o usuário REALMENTE vê, não com o que quase foi.
        porto_data_ref = None
        cbot_simbolo = None
        cbot_atualizado_em = None
        dolar_atualizado_em = None
        indisponiveis = ["Porto", "Praças (fretes)", "Dólar", "CBOT"]

    return {
        "texto": texto,
        "porto_data_ref": porto_data_ref,
        "cbot_simbolo": cbot_simbolo,
        "cbot_atualizado_em": cbot_atualizado_em,
        "dolar_atualizado_em": dolar_atualizado_em,
        "avisos": avisos,
        "indisponiveis": indisponiveis,
    }
