import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.db import conectar, fechar, migrar, reconstruir_se_vazio
from app.paths import garantir_pastas
from app.ui.shell import Shell


def carregar_fontes() -> None:
    pasta = Path(__file__).resolve().parent / "ui" / "fonts"
    for arquivo in pasta.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(arquivo))


def preparar_banco() -> None:
    garantir_pastas()
    cx = conectar()
    try:
        migrar(cx)
        reconstruir_se_vazio(cx)
    finally:
        fechar(cx)


def main() -> None:
    preparar_banco()
    app = QApplication(sys.argv)
    carregar_fontes()
    fonte = QFont("Source Sans 3")
    fonte.setPixelSize(17)
    app.setFont(fonte)
    estilo = Path(__file__).resolve().parent / "ui" / "theme.qss"
    app.setStyleSheet(estilo.read_text(encoding="utf-8"))
    janela = Shell()
    janela.show()
    sys.exit(app.exec())
