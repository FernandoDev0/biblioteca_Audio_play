from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.acervo import Acervo
from app.ui.estudio import Estudio
from app.ui.leitura import Leitura


class Shell(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Biblioteca")
        self.resize(1280, 860)
        self.setMinimumWidth(960)

        centro = QWidget()
        centro.setObjectName("Shell")
        self.setCentralWidget(centro)
        raiz = QVBoxLayout(centro)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        barra = QFrame()
        barra.setObjectName("Barra")
        barra.setFixedHeight(64)
        linha = QHBoxLayout(barra)
        linha.setContentsMargins(32, 0, 32, 0)
        linha.setSpacing(28)

        selo = QLabel("")
        selo.setObjectName("Selo")
        selo.setFixedSize(8, 8)
        marca = QLabel("Biblioteca")
        marca.setObjectName("Marca")
        marca_caixa = QHBoxLayout()
        marca_caixa.setSpacing(10)
        marca_caixa.addWidget(selo, 0, Qt.AlignmentFlag.AlignVCenter)
        marca_caixa.addWidget(marca)
        linha.addLayout(marca_caixa)
        linha.addStretch(1)

        self.nav_estudio = QPushButton("Estúdio")
        self.nav_acervo = QPushButton("Acervo")
        for botao in (self.nav_estudio, self.nav_acervo):
            botao.setObjectName("Nav")
            botao.setCheckable(True)
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
            linha.addWidget(botao)
        raiz.addWidget(barra)

        self.estudio = Estudio()
        self.acervo = Acervo()
        self.leitura = Leitura()
        self.pilha = QStackedWidget()
        self.pilha.addWidget(self.estudio)
        self.pilha.addWidget(self.acervo)
        self.pilha.addWidget(self.leitura)
        raiz.addWidget(self.pilha, 1)

        self.nav_estudio.clicked.connect(self._mostrar_estudio)
        self.nav_acervo.clicked.connect(self._mostrar_acervo)
        self.estudio.abrir_documento.connect(self.abrir_leitura)
        self.acervo.abrir.connect(self.abrir_leitura)
        self.acervo.ir_estudio.connect(self._mostrar_estudio)
        self._mostrar_estudio()

    def _mostrar_estudio(self) -> None:
        self.nav_estudio.setChecked(True)
        self.nav_acervo.setChecked(False)
        self.pilha.setCurrentWidget(self.estudio)

    def _mostrar_acervo(self) -> None:
        self.nav_acervo.setChecked(True)
        self.nav_estudio.setChecked(False)
        self.acervo.recarregar()
        self.pilha.setCurrentWidget(self.acervo)

    def abrir_leitura(self, doc_id: int) -> None:
        self.nav_estudio.setChecked(False)
        self.nav_acervo.setChecked(False)
        self.leitura.abrir(doc_id)
        self.pilha.setCurrentWidget(self.leitura)

    def closeEvent(self, evento) -> None:
        self.estudio.parar_lote()
        self.leitura.fechar()
        super().closeEvent(evento)
