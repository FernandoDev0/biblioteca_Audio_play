"""Cores de código no espírito do tema escuro do Obsidian.

O chrome do aplicativo continua preto e ouro. Dentro da caixa, cada tipo de
token tem a cor de estudo: palavra-chave, texto, número, nome e comentário.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

_PALAVRAS = {
    "Java": (
        "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
        "class", "const", "continue", "default", "do", "double", "else", "enum",
        "extends", "final", "finally", "float", "for", "goto", "if", "implements",
        "import", "instanceof", "int", "interface", "long", "native", "new",
        "package", "private", "protected", "public", "return", "short", "static",
        "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
        "transient", "try", "void", "volatile", "while", "true", "false", "null",
        "var", "record", "sealed", "permits", "yield",
    ),
    "Python": (
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "False", "finally", "for", "from",
        "global", "if", "import", "in", "is", "lambda", "None", "nonlocal", "not",
        "or", "pass", "raise", "return", "True", "try", "while", "with", "yield",
    ),
    "JavaScript": (
        "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "export", "extends", "false", "finally",
        "for", "function", "if", "import", "in", "instanceof", "let", "new", "null",
        "return", "static", "super", "switch", "this", "throw", "true", "try",
        "typeof", "undefined", "var", "void", "while", "yield", "await", "async", "of",
    ),
    "SQL": (
        "select", "from", "where", "and", "or", "insert", "into", "values", "update",
        "set", "delete", "create", "table", "drop", "join", "left", "right", "inner",
        "on", "group", "by", "order", "as", "not", "null", "primary", "key", "limit",
    ),
}

_COMUM = (
    "if", "else", "for", "while", "return", "class", "function", "def", "import",
    "public", "private", "void", "new", "true", "false", "null", "var", "let", "const",
)


def detectar_linguagem(texto: str) -> str:
    amostra = texto[:2500]
    if re.search(r"\b(public|private|protected)\b", amostra) and ("{" in amostra or ";" in amostra):
        return "Java"
    if "System.out" in amostra or "org.junit" in amostra:
        return "Java"
    if re.search(r"(?m)^\s*(def |class |elif |async def |from \w+ import )", amostra):
        return "Python"
    if "function " in amostra or "=>" in amostra or "console." in amostra or "const " in amostra:
        return "JavaScript"
    if re.search(r"\b(SELECT|INSERT|UPDATE|CREATE TABLE)\b", amostra, re.IGNORECASE):
        return "SQL"
    if "#include" in amostra or "std::" in amostra:
        return "C++"
    if "namespace " in amostra or "Console." in amostra:
        return "C#"
    return ""


def _formato(cor: str, *, italico: bool = False, peso: QFont.Weight = QFont.Weight.Normal) -> QTextCharFormat:
    formato = QTextCharFormat()
    formato.setForeground(QColor(cor))
    if italico:
        formato.setFontItalic(True)
    if peso != QFont.Weight.Normal:
        formato.setFontWeight(peso)
    return formato


class RealceCodigo(QSyntaxHighlighter):
    def __init__(self, documento) -> None:
        super().__init__(documento)
        self.linguagem = ""
        self.comentario = _formato("#8B939E", italico=True)
        self.texto = _formato("#98C379")
        self.numero = _formato("#D19A66")
        self.chave = _formato("#C678DD")
        self.funcao = _formato("#61AFEF")
        self.tipo = _formato("#E5C07B")
        self.anotacao = _formato("#E06C75")
        self.operador = _formato("#56B6C2")
        self.niveis = (
            _formato("#E5C07B"),
            _formato("#61AFEF"),
            _formato("#C678DD"),
            _formato("#98C379"),
        )
        self._palavras = QRegularExpression()
        self._palavras.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
        self.usar("")

    def usar(self, linguagem: str) -> None:
        self.linguagem = linguagem
        palavras = _PALAVRAS.get(linguagem, _COMUM)
        self._palavras.setPattern(r"\b(?:" + "|".join(palavras) + r")\b")
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        ocupado = self._comentarios_e_textos(text)
        self._aplicar(text, self._palavras, self.chave, ocupado)
        self._aplicar_re(text, r"\b\d+(?:\.\d+)?\b", self.numero, ocupado)
        self._aplicar_re(text, r"@[A-Za-z_][\w.]*", self.anotacao, ocupado)
        self._aplicar_re(text, r"\b[A-Z][A-Za-z0-9_]*\b", self.tipo, ocupado)
        self._aplicar_re(text, r"\b[A-Za-z_][\w]*\s*(?=\()", self.funcao, ocupado)
        self._aplicar_re(text, r"==|!=|<=|>=|&&|\|\||->|=>", self.operador, ocupado)
        self._parenteses(text, ocupado)

    def _comentarios_e_textos(self, text: str) -> list[tuple[int, int]]:
        ocupado: list[tuple[int, int]] = []
        inicio = 0
        if self.previousBlockState() == 1 and self.linguagem != "Python":
            fim = text.find("*/")
            if fim < 0:
                self.setFormat(0, len(text), self.comentario)
                self.setCurrentBlockState(1)
                return [(0, len(text))]
            self.setFormat(0, fim + 2, self.comentario)
            ocupado.append((0, fim + 2))
            inicio = fim + 2
        self.setCurrentBlockState(0)
        i = inicio
        while i < len(text):
            if self._livre(i, ocupado) and text.startswith("//", i) and self.linguagem != "Python":
                self.setFormat(i, len(text) - i, self.comentario)
                ocupado.append((i, len(text)))
                break
            if self._livre(i, ocupado) and text.startswith("--", i) and self.linguagem == "SQL":
                self.setFormat(i, len(text) - i, self.comentario)
                ocupado.append((i, len(text)))
                break
            if self._livre(i, ocupado) and text[i] == "#" and self.linguagem == "Python":
                self.setFormat(i, len(text) - i, self.comentario)
                ocupado.append((i, len(text)))
                break
            if self._livre(i, ocupado) and text.startswith("/*", i) and self.linguagem != "Python":
                fim = text.find("*/", i + 2)
                if fim < 0:
                    self.setFormat(i, len(text) - i, self.comentario)
                    self.setCurrentBlockState(1)
                    ocupado.append((i, len(text)))
                    break
                self.setFormat(i, fim + 2 - i, self.comentario)
                ocupado.append((i, fim + 2))
                i = fim + 2
                continue
            if self._livre(i, ocupado) and text[i] in {'"', "'"}:
                fim = self._fechar_texto(text, i)
                self.setFormat(i, fim - i, self.texto)
                ocupado.append((i, fim))
                i = fim
                continue
            i += 1
        return ocupado

    def _fechar_texto(self, text: str, inicio: int) -> int:
        aspa = text[inicio]
        i = inicio + 1
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == aspa:
                return i + 1
            i += 1
        return len(text)

    def _livre(self, posicao: int, ocupado: list[tuple[int, int]]) -> bool:
        return not any(ini <= posicao < fim for ini, fim in ocupado)

    def _aplicar(self, text: str, regra: QRegularExpression, formato: QTextCharFormat, ocupado: list[tuple[int, int]]) -> None:
        busca = regra.globalMatch(text)
        while busca.hasNext():
            achado = busca.next()
            ini = achado.capturedStart()
            fim = achado.capturedEnd()
            if any(not (fim <= a or ini >= b) for a, b in ocupado):
                continue
            self.setFormat(ini, fim - ini, formato)
            ocupado.append((ini, fim))

    def _aplicar_re(self, text: str, padrao: str, formato: QTextCharFormat, ocupado: list[tuple[int, int]]) -> None:
        for achado in re.finditer(padrao, text):
            ini, fim = achado.span()
            if any(not (fim <= a or ini >= b) for a, b in ocupado):
                continue
            self.setFormat(ini, fim - ini, formato)
            ocupado.append((ini, fim))

    def _parenteses(self, text: str, ocupado: list[tuple[int, int]]) -> None:
        profundidade = 0
        for i, caractere in enumerate(text):
            if not self._livre(i, ocupado):
                continue
            if caractere in "([{":
                self.setFormat(i, 1, self.niveis[profundidade % len(self.niveis)])
                profundidade += 1
            elif caractere in ")]}":
                profundidade = max(0, profundidade - 1)
                self.setFormat(i, 1, self.niveis[profundidade % len(self.niveis)])
