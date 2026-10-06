"""O que a Francisca lê e o que fica só na página.

Número solto, código, URL e marcação de folha não entram no lote.
Frase de verdade entra, mesmo quando cita um número no meio.
"""

from __future__ import annotations

import re
import unicodedata

_CODIGO_FONTES = (
    "mono",
    "courier",
    "consolas",
    "sftt",
    "menlo",
    "inconsolata",
    "cascadia",
    "sourcecode",
    "lucidaconsole",
    "liberationmono",
)

_URL = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SO_NUMERO = re.compile(r"^[\d]+(?:[.\-]\d+)*$")
_ISBN = re.compile(r"^(?:isbn[:\s]*)?97[89][-\s\d]{10,}$", re.IGNORECASE)
_FIGURA = re.compile(
    r"^(?:figura|fig\.|tabela|quadro|grafico|gráfico)\s*[\d.]+$",
    re.IGNORECASE,
)
_CODIGO_SINAL = re.compile(
    r"\b(public|private|protected|class|void|return|import|function|def|elif|println)\b"
)


def fonte_e_codigo(nome: str) -> bool:
    compacto = nome.lower().replace(" ", "").replace("-", "")
    return any(chave in compacto for chave in _CODIGO_FONTES)


def sem_acento(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    sem = "".join(c for c in normal if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem).strip().lower()


def eh_cabecalho_de_livro(texto: str) -> bool:
    return sem_acento(texto) in {"casa do codigo"}


def juntar_prosa(linhas: list[str]) -> str:
    partes: list[str] = []
    for bruta in linhas:
        texto = bruta.strip()
        if not texto:
            continue
        if not partes:
            partes.append(texto)
            continue
        anterior = partes[-1]
        if (
            anterior.endswith("-")
            and len(anterior) >= 45
            and texto[:1].islower()
            and len(anterior) >= 2
            and anterior[-2].isalpha()
        ):
            partes[-1] = anterior[:-1] + texto
            continue
        partes[-1] = anterior + " " + texto
    return partes[0] if partes else ""


def juntar_codigo(linhas: list[str]) -> str:
    return "\n".join(linha.rstrip() for linha in linhas if linha.strip())


def indentar_codigo(linhas: list[tuple[str, float]]) -> str:
    """Reconstrói os espaços a partir da margem esquerda de cada linha no PDF.

    Um passo de indentação vira quatro espaços, como num bloco de código.
    """
    uteis = [(texto.strip(), x) for texto, x in linhas if texto.strip()]
    if not uteis:
        return ""
    xs = sorted({round(x, 1) for _, x in uteis})
    base = xs[0]
    diffs = [b - a for a, b in zip(xs, xs[1:]) if b - a > 4]
    passo = sorted(diffs)[len(diffs) // 2] if diffs else 0
    saida: list[str] = []
    for texto, x in uteis:
        nivel = int(round((x - base) / passo)) if passo >= 4 else 0
        saida.append("    " * max(0, nivel) + texto)
    return "\n".join(saida)


def _letras(texto: str) -> int:
    return sum(1 for c in texto if c.isalpha())


def _parece_codigo(texto: str) -> bool:
    simbolos = sum(texto.count(c) for c in "{}[]();=<>")
    letras = _letras(texto)
    if simbolos >= 3 and letras > 0 and simbolos >= letras * 0.08:
        return True
    return bool(_CODIGO_SINAL.search(texto) and any(c in texto for c in "{};()"))


def classificar(
    texto: str,
    *,
    code: bool = False,
    tamanho: float = 11,
    negrito: bool = False,
) -> tuple[str, bool]:
    limpo = re.sub(r"\s+", " ", texto).strip()
    if not limpo:
        return "folha", False
    if code or _parece_codigo(limpo):
        return "codigo", False
    if _URL.match(limpo) or _EMAIL.match(limpo) or _ISBN.match(limpo):
        return "codigo", False
    if _SO_NUMERO.match(limpo) or _FIGURA.match(limpo):
        return "numero", False
    letras = _letras(limpo)
    if letras < 4:
        if any(c.isdigit() for c in limpo):
            return "numero", False
        return "folha", False
    digitos = sum(1 for c in limpo if c.isdigit())
    if digitos and letras / max(len(limpo), 1) < 0.35 and len(limpo) < 40:
        return "numero", False
    curto = len(limpo) <= 90
    if curto and (negrito or tamanho >= 13 or limpo[:1].isdigit()):
        return "titulo", True
    return "prosa", True


def fatiar_prosa(texto: str, limite: int = 900) -> list[str]:
    limpo = texto.strip()
    if len(limpo) <= limite:
        return [limpo] if limpo else []
    frases = re.split(r"(?<=[.!?])\s+", limpo)
    grupos: list[str] = []
    atual = ""
    for frase in frases:
        if not frase:
            continue
        if atual and len(atual) + 1 + len(frase) > limite:
            grupos.append(atual)
            atual = frase
        else:
            atual = f"{atual} {frase}".strip()
        while len(atual) > limite:
            corte = atual.rfind(" ", 0, limite)
            if corte < 40:
                corte = limite
            grupos.append(atual[:corte].strip())
            atual = atual[corte:].strip()
    if atual:
        grupos.append(atual)
    return grupos
