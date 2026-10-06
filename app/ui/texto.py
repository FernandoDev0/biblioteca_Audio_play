"""Texto do PDF com a palavra falada em âmbar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QSizePolicy, QTextEdit, QWidget

from app.ui.sintaxe import RealceCodigo, detectar_linguagem

_AMBAR = QColor("#E3B23C")
_TINTA = QColor("#1A1408")


class _GuiasIndent(QWidget):
    """Fio vertical a cada quatro espaços, como o guia de indentação do Obsidian."""

    def __init__(self, editor: "TextoMarcado") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _evento) -> None:
        editor = self._editor
        metrica = QFontMetrics(editor.font())
        passo = metrica.horizontalAdvance("    ")
        if passo < 4:
            return
        pintor = QPainter(self)
        cor = QColor("#8A7764")
        cor.setAlpha(70)
        pintor.setPen(QPen(cor, 1))
        margem = editor.document().documentMargin()
        rolagem = editor.verticalScrollBar().value()
        layout = editor.document().documentLayout()
        bloco = editor.document().firstBlock()
        while bloco.isValid():
            rect = layout.blockBoundingRect(bloco)
            espacos = len(bloco.text()) - len(bloco.text().lstrip(" "))
            y = rect.top() - rolagem
            for nivel in range(1, espacos // 4 + 1):
                x = int(margem + nivel * passo)
                pintor.drawLine(x, int(y) + 3, x, int(y + rect.height()) - 3)
            bloco = bloco.next()
        pintor.end()


def mapear(texto: str, palavras: list[dict]) -> list[tuple[int, int] | None]:
    mapas: list[tuple[int, int] | None] = []
    posicao = 0
    for palavra in palavras:
        token = (palavra.get("texto") or "").strip()
        if not token:
            mapas.append(None)
            continue
        indice = texto.find(token, posicao)
        usado = token
        if indice < 0:
            nucleo = token.strip(".,;:!?\"“”()[]«»")
            if nucleo:
                indice = texto.find(nucleo, posicao)
                usado = nucleo
        if indice < 0:
            mapas.append(None)
            continue
        mapas.append((indice, indice + len(usado)))
        posicao = indice + len(usado)
    return mapas


class TextoMarcado(QTextEdit):
    clicado = Signal()

    def __init__(self, *, codigo: bool = False, folha: bool = False, crescer: bool = True) -> None:
        super().__init__()
        self._crescer = crescer
        self._ajustando = False
        self._mapas: list[tuple[int, int] | None] = []
        self._pressao = None
        self.setReadOnly(True)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if crescer else Qt.ScrollBarAsNeeded)
        self.document().setDocumentMargin(2)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._realce: RealceCodigo | None = None
        self._guias: _GuiasIndent | None = None
        if codigo:
            self.setObjectName("Codigo")
            self.document().setDocumentMargin(12)
            fonte = QFont("Consolas")
            fonte.setPixelSize(14)
            fonte.setStyleHint(QFont.StyleHint.Monospace)
            self.setFont(fonte)
            self.setTabStopDistance(QFontMetrics(fonte).horizontalAdvance(" ") * 4)
            self._realce = RealceCodigo(self.document())
            self._guias = _GuiasIndent(self)
        elif folha:
            self.setObjectName("Folha")
        elif not crescer:
            self.setObjectName("FaixaAudio")
        if not crescer:
            self.setFixedHeight(76)

    def definir(self, texto: str, palavras: list[dict] | None = None) -> None:
        self.setPlainText(texto or "")
        if self._realce is not None:
            self._realce.usar(detectar_linguagem(texto or ""))
            self._espacar_codigo()
        self._mapas = mapear(texto or "", palavras or [])
        self.limpar_marca()
        self._ajustar_altura()
        self._posicionar_guias()

    def definir_largura(self, largura: int) -> None:
        if largura > 40 and self.viewport().width() < 40:
            self.document().setTextWidth(largura)
        self._ajustar_altura()

    def minimumSizeHint(self) -> QSize:
        return QSize(80, 28)

    def sizeHint(self) -> QSize:
        return QSize(120, max(28, self.height()))

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_altura()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self._ajustar_altura()

    def _ajustar_altura(self) -> None:
        if not self._crescer or self._ajustando:
            return
        self._ajustando = True
        try:
            largura = self.viewport().width()
            if largura > 40 and abs(self.document().textWidth() - largura) > 1:
                self.document().setTextWidth(largura)
            documento = self.document()
            ultimo = documento.lastBlock()
            fundo = documento.documentLayout().blockBoundingRect(ultimo).bottom()
            folga = max(0, self.height() - self.viewport().height())
            altura = int(fundo + documento.documentMargin() + folga + 8)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setFixedHeight(max(28, altura))
            sobra = self.verticalScrollBar().maximum()
            if sobra > 0:
                self.setFixedHeight(self.height() + sobra + 8)
            self._posicionar_guias()
        finally:
            self._ajustando = False

    def _espacar_codigo(self) -> None:
        formato = QTextBlockFormat()
        formato.setLineHeight(156.0, 1)
        bloco = self.document().firstBlock()
        while bloco.isValid():
            cursor = QTextCursor(bloco)
            cursor.mergeBlockFormat(formato)
            bloco = bloco.next()

    def _posicionar_guias(self) -> None:
        if self._guias is None:
            return
        self._guias.setGeometry(self.viewport().geometry())
        self._guias.raise_()
        self._guias.update()

    def marcar(self, indice: int | None) -> None:
        if indice is None or indice < 0 or indice >= len(self._mapas):
            self.limpar_marca()
            return
        faixa = self._mapas[indice]
        if faixa is None:
            self.limpar_marca()
            return
        cursor = self.textCursor()
        cursor.setPosition(faixa[0])
        cursor.setPosition(faixa[1], QTextCursor.KeepAnchor)
        formato = QTextCharFormat()
        formato.setBackground(_AMBAR)
        formato.setForeground(_TINTA)
        selecao = QTextEdit.ExtraSelection()
        selecao.cursor = cursor
        selecao.format = formato
        self.setExtraSelections([selecao])
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def limpar_marca(self) -> None:
        self.setExtraSelections([])

    def mousePressEvent(self, evento) -> None:
        self._pressao = evento.position()
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento) -> None:
        super().mouseReleaseEvent(evento)
        if self._pressao is None:
            return
        if (evento.position() - self._pressao).manhattanLength() < 6:
            self.clicado.emit()
        self._pressao = None
