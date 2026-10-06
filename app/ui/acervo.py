"""A parte da biblioteca que abre pelo nome do PDF."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.db import conectar, fechar, listar_documentos
from app.tempo import duracao

_STATUS = {
    "extraindo": "Lendo o PDF",
    "dublando": "Dublando",
    "parcial": "Áudio parcial",
    "pronto": "Pronto para ouvir",
    "erro": "Interrompido",
}


class Acervo(QWidget):
    abrir = Signal(int)
    ir_estudio = Signal()

    def __init__(self) -> None:
        super().__init__()
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(48, 40, 48, 24)
        raiz.setSpacing(8)

        kicker = QLabel("ACERVO")
        kicker.setObjectName("Kicker")
        raiz.addWidget(kicker)

        self.titulo = QLabel("Os documentos ficam aqui.")
        self.titulo.setObjectName("Display")
        self.titulo.setWordWrap(True)
        raiz.addWidget(self.titulo)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.miolo = QWidget()
        self.lista = QVBoxLayout(self.miolo)
        self.lista.setContentsMargins(0, 24, 0, 24)
        self.lista.setSpacing(0)
        self.scroll.setWidget(self.miolo)
        raiz.addWidget(self.scroll, 1)

    def showEvent(self, evento) -> None:
        self.recarregar()
        super().showEvent(evento)

    def recarregar(self) -> None:
        while self.lista.count():
            item = self.lista.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        cx = conectar()
        try:
            documentos = listar_documentos(cx)
        finally:
            fechar(cx)
        if not documentos:
            vazio = QLabel("Nenhum documento no acervo.")
            vazio.setObjectName("Corpo")
            self.lista.addWidget(vazio)
            botao = QPushButton("Ir ao estúdio")
            botao.setObjectName("Primario")
            botao.clicked.connect(self.ir_estudio.emit)
            self.lista.addWidget(botao)
            self.lista.addStretch(1)
            return
        for documento in documentos:
            self.lista.addWidget(self._linha(documento))
        self.lista.addStretch(1)

    def _linha(self, documento: dict) -> QWidget:
        linha = QWidget()
        linha.setObjectName("LinhaAcervo")
        layout = QHBoxLayout(linha)
        layout.setContentsMargins(0, 20, 0, 20)
        layout.setSpacing(24)

        textos = QVBoxLayout()
        textos.setSpacing(4)
        nome = QLabel(documento["titulo"])
        nome.setObjectName("NomeLivro")
        nome.setWordWrap(True)
        textos.addWidget(nome)
        audio = int(documento["paginas_com_audio"] or 0)
        lidas = int(documento["lidas"] or 0)
        meta = QLabel(
            f"{documento['paginas']} páginas · áudio em {audio} · "
            f"{lidas} concluídas · {_STATUS.get(documento['status'], documento['status'])} · "
            f"{duracao(int(documento['duracao_ms'] or 0))}"
        )
        meta.setObjectName("Meta")
        meta.setWordWrap(True)
        textos.addWidget(meta)
        layout.addLayout(textos, 1)

        abrir = QPushButton("Abrir")
        abrir.setObjectName("Secundario")
        abrir.clicked.connect(lambda _=False, doc_id=int(documento["id"]): self.abrir.emit(doc_id))
        layout.addWidget(abrir)
        return linha
