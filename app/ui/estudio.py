"""Onde o PDF entra e o lote da Francisca trabalha."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.db import conectar, fechar, listar_documentos
from app.extract import tesseract_disponivel
from app.machine import frase_maquina
from app.pipeline import Cancelado, dublar_pendentes, importar_pdf


class _Lote(QThread):
    progresso = Signal(str)
    terminou = Signal(int)
    pausou = Signal(int)
    falhou = Signal(str)

    def __init__(self, pdf: Path | None, doc_id: int | None) -> None:
        super().__init__()
        self.pdf = pdf
        self.doc_id = doc_id
        self.cancelar = threading.Event()

    def run(self) -> None:
        try:
            if self.pdf is not None:
                doc_id = importar_pdf(
                    self.pdf,
                    progresso=self.progresso.emit,
                    cancelar=self.cancelar,
                )
            else:
                assert self.doc_id is not None
                dublar_pendentes(
                    self.doc_id,
                    progresso=self.progresso.emit,
                    cancelar=self.cancelar,
                )
                doc_id = self.doc_id
            self.terminou.emit(int(doc_id))
        except Cancelado:
            self.pausou.emit(int(self.doc_id or 0))
        except Exception as erro:
            self.falhou.emit(str(erro))


class Estudio(QWidget):
    abrir_documento = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self._pdf: Path | None = None
        self._lote: _Lote | None = None
        self._parcial_id: int | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(48, 40, 48, 40)
        raiz.setSpacing(16)

        kicker = QLabel("ESTÚDIO")
        kicker.setObjectName("Kicker")
        raiz.addWidget(kicker)

        titulo = QLabel("O PDF entra aqui.")
        titulo.setObjectName("Display")
        titulo.setWordWrap(True)
        raiz.addWidget(titulo)

        corpo = QLabel(
            "O texto é separado do que não vale ouvir: código, número solto, "
            "endereço e marcação de página. A Francisca dubla o restante em Opus, "
            "página por página. Um livro grande segue em lote e pode parar e continuar."
        )
        corpo.setObjectName("Corpo")
        corpo.setWordWrap(True)
        corpo.setMaximumWidth(640)
        raiz.addWidget(corpo)

        self.maquina = QLabel(frase_maquina())
        self.maquina.setObjectName("Mudo")
        self.maquina.setWordWrap(True)
        self.maquina.setMaximumWidth(640)
        raiz.addWidget(self.maquina)

        if not tesseract_disponivel():
            foto = QLabel(
                "Página que é só foto continua visível. A transcrição dessa foto pede o Tesseract."
            )
            foto.setObjectName("Mudo")
            foto.setWordWrap(True)
            foto.setMaximumWidth(640)
            raiz.addWidget(foto)

        self.arquivo = QLabel("Nenhum PDF escolhido.")
        self.arquivo.setObjectName("Meta")
        self.arquivo.setWordWrap(True)
        raiz.addWidget(self.arquivo)

        acoes = QHBoxLayout()
        acoes.setSpacing(12)
        self.tratar = QPushButton("Tratar PDF")
        self.tratar.setObjectName("Primario")
        self.tratar.clicked.connect(self._escolher)
        self.parar = QPushButton("Parar lote")
        self.parar.setObjectName("Secundario")
        self.parar.setEnabled(False)
        self.parar.clicked.connect(self.parar_lote)
        self.continuar = QPushButton("Continuar lote")
        self.continuar.setObjectName("Secundario")
        self.continuar.setEnabled(False)
        self.continuar.clicked.connect(self._continuar)
        acoes.addWidget(self.tratar)
        acoes.addWidget(self.continuar)
        acoes.addWidget(self.parar)
        acoes.addStretch(1)
        raiz.addLayout(acoes)

        self.estado = QLabel("")
        self.estado.setObjectName("Corpo")
        self.estado.setWordWrap(True)
        self.estado.setMaximumWidth(640)
        raiz.addWidget(self.estado)

        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setVisible(False)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(2)
        raiz.addWidget(self.barra)

        self.erro = QLabel("")
        self.erro.setObjectName("Erro")
        self.erro.setWordWrap(True)
        self.erro.setMaximumWidth(640)
        raiz.addWidget(self.erro)
        raiz.addStretch(1)

    def showEvent(self, evento) -> None:
        self.atualizar()
        super().showEvent(evento)

    def atualizar(self) -> None:
        if self._lote is not None:
            return
        cx = conectar()
        try:
            parciais = [d for d in listar_documentos(cx) if d["status"] in {"parcial", "dublando", "extraindo", "erro"}]
        finally:
            fechar(cx)
        if parciais:
            self._parcial_id = int(parciais[0]["id"])
            self.continuar.setEnabled(True)
            self.continuar.setText("Continuar lote")
        else:
            self._parcial_id = None
            self.continuar.setEnabled(False)

    def dragEnterEvent(self, evento) -> None:
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:
        for url in evento.mimeData().urls():
            caminho = Path(url.toLocalFile())
            if caminho.suffix.lower() == ".pdf":
                self._pdf = caminho
                self.arquivo.setText(caminho.name)
                self._comecar(caminho, None)
                return

    def _escolher(self) -> None:
        nome, _ = QFileDialog.getOpenFileName(self, "Escolher PDF", "", "PDF (*.pdf)")
        if not nome:
            return
        caminho = Path(nome)
        self._pdf = caminho
        self.arquivo.setText(caminho.name)
        self._comecar(caminho, None)

    def _continuar(self) -> None:
        if self._parcial_id is None:
            return
        self._comecar(None, self._parcial_id)

    def _comecar(self, pdf: Path | None, doc_id: int | None) -> None:
        if self._lote is not None:
            return
        self.erro.setText("")
        self.estado.setText("Preparando o documento.")
        self.barra.setVisible(True)
        self.tratar.setEnabled(False)
        self.continuar.setEnabled(False)
        self.parar.setEnabled(True)
        self._lote = _Lote(pdf, doc_id)
        self._lote.progresso.connect(self.estado.setText)
        self._lote.terminou.connect(self._terminou)
        self._lote.pausou.connect(self._pausou)
        self._lote.falhou.connect(self._falhou)
        self._lote.finished.connect(self._limpar_thread)
        self._lote.start()

    def parar_lote(self) -> None:
        if self._lote is not None:
            self._lote.cancelar.set()
            self.estado.setText("Parando ao fim deste trecho.")
            self.parar.setEnabled(False)

    def _limpar_thread(self) -> None:
        self._lote = None

    def _terminou(self, doc_id: int) -> None:
        self._ocioso()
        self.estado.setText("Tratativa encerrada. O documento está no acervo.")
        self.abrir_documento.emit(doc_id)

    def _pausou(self, _doc_id: int) -> None:
        self._ocioso()
        self.estado.setText("Lote pausado. Dá para continuar depois.")
        self.atualizar()

    def _falhou(self, mensagem: str) -> None:
        self._ocioso()
        self.erro.setText(mensagem)
        self.estado.setText("A tratativa parou neste ponto. O que já foi feito continua no acervo.")
        self.atualizar()

    def _ocioso(self) -> None:
        self.barra.setVisible(False)
        self.tratar.setEnabled(True)
        self.parar.setEnabled(False)
        self.atualizar()
