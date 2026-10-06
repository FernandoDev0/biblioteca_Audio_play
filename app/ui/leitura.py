"""Duas páginas do PDF, e embaixo o áudio com play e volume."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.db import (
    bloco_por_id,
    blocos_da_pagina,
    buscar,
    conectar,
    expectativa,
    fechar,
    ler_spread,
    marcar_pagina_lida,
    narracao_desde,
    obter_documento,
    palavras_do_bloco,
    pendentes_na_pagina,
    salvar_spread,
)
from app.machine import decidir
from app.paths import absoluto
from app.pipeline import dublar_bloco
from app.player import Tocador
from app.tempo import duracao, por_volta, relogio
from app.ui.sintaxe import detectar_linguagem
from app.ui.texto import TextoMarcado

# Threads que ainda geram voz quando a janela fecha. Soltá-las no meio
# derruba o processo (QThread destruída enquanto roda).
_THREADS_VIVOS: list[_Sequencia] = []


class _Sequencia(QThread):
    """Gera os trechos em ordem, um depois do outro, sem atropelar a voz que já toca."""

    pronto = Signal(int)
    falhou = Signal(str)

    def __init__(self, ids: list[int]) -> None:
        super().__init__()
        self.ids = ids
        self.cancelar = threading.Event()

    def run(self) -> None:
        from app.pipeline import dublar_bloco

        try:
            for bloco_id in self.ids:
                if self.cancelar.is_set():
                    return
                dublar_bloco(bloco_id, permitir_whisper=False)
                if self.cancelar.is_set():
                    return
                self.pronto.emit(bloco_id)
        except Exception as erro:
            self.falhou.emit(str(erro))


class _Demanda(QThread):
    terminou = Signal(int)
    falhou = Signal(str)

    def __init__(self, bloco_id: int, whisper: bool) -> None:
        super().__init__()
        self.bloco_id = bloco_id
        self.whisper = whisper

    def run(self) -> None:
        try:
            dublar_bloco(self.bloco_id, permitir_whisper=self.whisper)
            self.terminou.emit(self.bloco_id)
        except Exception as erro:
            self.falhou.emit(str(erro))


class _Caixa(QFrame):
    clicado = Signal(int)

    def __init__(self, bloco: dict, palavras: list[dict]) -> None:
        super().__init__()
        self.bloco_id = int(bloco["id"])
        self.tipo = bloco["tipo"]
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        kicker = _rotulo(bloco)
        self._copiar: QPushButton | None = None
        if kicker:
            linha = QHBoxLayout()
            linha.setContentsMargins(0, 0, 0, 0)
            linha.setSpacing(12)
            etiqueta = QLabel(kicker)
            etiqueta.setObjectName("KickerBloco")
            linha.addWidget(etiqueta)
            linha.addStretch(1)
            if bloco["tipo"] == "codigo":
                self._copiar = QPushButton("Copiar")
                self._copiar.setObjectName("Copiar")
                self._copiar.setCursor(Qt.CursorShape.PointingHandCursor)
                self._copiar.clicked.connect(self._copiar_codigo)
                linha.addWidget(self._copiar)
            layout.addLayout(linha)
        self.texto: TextoMarcado | None = None
        self._pix: QPixmap | None = None
        self.figura: QLabel | None = None
        if bloco["tipo"] == "imagem" and bloco.get("imagem_relpath"):
            self.figura = QLabel()
            caminho = absoluto(bloco["imagem_relpath"])
            self._pix = QPixmap(str(caminho)) if caminho and caminho.exists() else QPixmap()
            layout.addWidget(self.figura)
            self.setObjectName("BlocoMudo")
        else:
            self.texto = TextoMarcado(
                codigo=bloco["tipo"] == "codigo",
                folha=bloco["tipo"] in {"folha", "numero"},
            )
            self.texto.definir(bloco["texto"] or "", palavras if bloco.get("audio_relpath") else [])
            self.texto.clicado.connect(lambda: self.clicado.emit(self.bloco_id))
            layout.addWidget(self.texto)
            if bloco.get("audio_relpath"):
                self.setObjectName("BlocoAudio")
            elif bloco["tipo"] == "codigo":
                self.setObjectName("BlocoCodigo")
            else:
                self.setObjectName("BlocoMudo")

    def definir_largura(self, largura: int) -> None:
        if self.texto is not None:
            self.texto.definir_largura(max(80, largura))
        elif self.figura is not None and self._pix is not None and not self._pix.isNull():
            escala = self._pix.scaledToWidth(max(80, largura), Qt.TransformationMode.SmoothTransformation)
            self.figura.setPixmap(escala)
            self.figura.setFixedHeight(escala.height())
            self.figura.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def marcar(self, indice: int | None) -> None:
        if self.texto is not None:
            self.texto.marcar(indice)

    def limpar(self) -> None:
        if self.texto is not None:
            self.texto.limpar_marca()

    def _copiar_codigo(self) -> None:
        if self.texto is None or self._copiar is None:
            return
        QGuiApplication.clipboard().setText(self.texto.toPlainText())
        self._copiar.setText("Copiado")
        QTimer.singleShot(1200, lambda: self._copiar.setText("Copiar") if self._copiar else None)


def _rotulo(bloco: dict) -> str:
    if bloco["tipo"] == "codigo":
        idioma = detectar_linguagem(bloco.get("texto") or "")
        if idioma:
            return f"CÓDIGO  ·  {idioma.upper()}"
        return "CÓDIGO  ·  CLIQUE SE QUISER OUVIR"
    if bloco["dublar"] and not bloco.get("audio_relpath"):
        return "NO LOTE  ·  CLIQUE PARA OUVIR AGORA"
    return ""


class _Coluna(QWidget):
    clicado = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Pagina")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._ajustando = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 32)
        layout.setSpacing(12)
        self.folio = QLabel("")
        self.folio.setObjectName("Folio")
        layout.addWidget(self.folio)
        self._miolo = QVBoxLayout()
        self._miolo.setSpacing(8)
        layout.addLayout(self._miolo)
        layout.addStretch(1)
        self._caixas: list[_Caixa] = []

    def mostrar(self, pagina: dict | None, blocos: list[dict], palavras: dict[int, list[dict]]) -> None:
        self._limpar()
        if pagina is None:
            self.folio.setText("")
            aviso = QLabel("Fim do documento.")
            aviso.setObjectName("Mudo")
            self._miolo.addWidget(aviso)
            return
        self.folio.setText(f"{int(pagina['numero']):02d}")
        if not blocos:
            aviso = QLabel("Página em branco.")
            aviso.setObjectName("Mudo")
            self._miolo.addWidget(aviso)
            return
        for bloco in blocos:
            caixa = _Caixa(bloco, palavras.get(int(bloco["id"]), []))
            caixa.clicado.connect(self.clicado)
            self._miolo.addWidget(caixa)
            self._caixas.append(caixa)
        self.definir_largura(self.width())

    def definir_largura(self, largura: int) -> None:
        util = max(120, largura - 56)
        for caixa in self._caixas:
            caixa.definir_largura(util)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        if self._ajustando or self.width() < 80:
            return
        self._ajustando = True
        self.definir_largura(self.width())
        self._ajustando = False

    def caixa(self, bloco_id: int) -> _Caixa | None:
        for caixa in self._caixas:
            if caixa.bloco_id == bloco_id:
                return caixa
        return None

    def _limpar(self) -> None:
        self._caixas.clear()
        while self._miolo.count():
            item = self._miolo.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class Leitura(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._cx = None
        self._doc: dict | None = None
        self._esquerda = 1
        self._paginas: dict[int, dict] = {}
        self._fila: list[dict] = []
        self._indice_fila = -1
        self._bloco_atual: dict | None = None
        self._palavras: list[dict] = []
        self._arrastando = False
        self._demanda: _Demanda | None = None
        self._ouvidos: set[int] = set()
        self._descontado = 0
        self._base_ms = 0
        self._continuo = False
        self._sequencia: _Sequencia | None = None
        self._sequencias: list[_Sequencia] = []
        self._aguardando_id: int | None = None
        self._passo = 0
        self.tocador = Tocador()
        self.tocador.terminou.connect(self._fim_do_clipe)

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(32, 24, 32, 0)
        raiz.setSpacing(8)

        topo = QHBoxLayout()
        self.titulo = QLabel("")
        self.titulo.setObjectName("TituloLivro")
        self.titulo.setWordWrap(True)
        topo.addWidget(self.titulo, 1)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar no livro")
        self.busca.setFixedWidth(240)
        self.busca.returnPressed.connect(self._buscar)
        topo.addWidget(self.busca, 0, Qt.AlignmentFlag.AlignTop)
        raiz.addLayout(topo)

        self.kicker = QLabel("")
        self.kicker.setObjectName("Kicker")
        self.anterior = QPushButton("Anteriores")
        self.anterior.setObjectName("Secundario")
        self.anterior.clicked.connect(self._anterior)
        self.proxima = QPushButton("Próximas")
        self.proxima.setObjectName("Secundario")
        self.proxima.clicked.connect(self._proxima)
        self._ouvir = QPushButton("Ouvir tudo")
        self._ouvir.setObjectName("Primario")
        self._ouvir.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ouvir.clicked.connect(self._ouvir_tudo)
        linha_paginas = QHBoxLayout()
        linha_paginas.setSpacing(12)
        linha_paginas.addWidget(self.kicker, 1)
        linha_paginas.addWidget(self._ouvir)
        linha_paginas.addWidget(self.anterior)
        linha_paginas.addWidget(self.proxima)
        raiz.addLayout(linha_paginas)

        self.expectativa = QLabel("")
        self.expectativa.setObjectName("Corpo")
        self.expectativa.setWordWrap(True)
        raiz.addWidget(self.expectativa)

        self.nota = QLabel("")
        self.nota.setObjectName("Mudo")
        self.nota.setWordWrap(True)
        raiz.addWidget(self.nota)

        self.progresso = QProgressBar()
        self.progresso.setTextVisible(False)
        self.progresso.setFixedHeight(2)
        self.progresso.setRange(0, 1)
        raiz.addWidget(self.progresso)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.spread = QWidget()
        self.spread.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.miolo = QHBoxLayout(self.spread)
        self.miolo.setContentsMargins(0, 12, 0, 12)
        self.miolo.setSpacing(16)
        self.esquerda = _Coluna()
        self.direita = _Coluna()
        self.fio = QFrame()
        self.fio.setObjectName("Fio")
        self.fio.setFixedWidth(1)
        self.esquerda.clicado.connect(self._clicar_bloco)
        self.direita.clicado.connect(self._clicar_bloco)
        self.miolo.addWidget(self.esquerda, 1)
        self.miolo.addWidget(self.fio)
        self.miolo.addWidget(self.direita, 1)
        self.scroll.setWidget(self.spread)
        raiz.addWidget(self.scroll, 1)

        player = QWidget()
        player.setObjectName("Player")
        caixa = QVBoxLayout(player)
        caixa.setContentsMargins(8, 14, 8, 16)
        caixa.setSpacing(8)
        self.faixa = TextoMarcado(crescer=False)
        self.faixa.definir(
            "Ouvir tudo, no topo, narra daqui até o fim. Ler toca só estas duas páginas.",
            [],
        )
        caixa.addWidget(self.faixa)

        controles = QHBoxLayout()
        controles.setSpacing(16)
        self.ler = QPushButton("Ler")
        self.ler.setObjectName("Secundario")
        self.ler.clicked.connect(self._ler)
        controles.addWidget(self.ler)
        self.tempo = QLabel("00:00 / 00:00")
        self.tempo.setObjectName("Meta")
        controles.addWidget(self.tempo)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(self._segurar)
        self.seek.sliderReleased.connect(self._soltar)
        controles.addWidget(self.seek, 1)
        volume_rotulo = QLabel("VOLUME")
        volume_rotulo.setObjectName("Kicker")
        controles.addWidget(volume_rotulo)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(120)
        guardado = int(QSettings("Biblioteca", "Audio").value("volume", 80))
        self.volume.setValue(max(0, min(100, guardado)))
        self.volume.valueChanged.connect(self._volume)
        controles.addWidget(self.volume)
        caixa.addLayout(controles)

        self.aviso_vlc = QLabel("")
        self.aviso_vlc.setObjectName("Erro")
        self.aviso_vlc.setWordWrap(True)
        if not self.tocador.disponivel():
            self.aviso_vlc.setText("O VLC não abriu. O texto continua na página. " + self.tocador.erro)
        caixa.addWidget(self.aviso_vlc)
        raiz.addWidget(player)

    def abrir(self, doc_id: int) -> None:
        self._parar_fila(salvar=False)
        if self._cx is not None:
            fechar(self._cx)
        self._cx = conectar()
        self._doc = obter_documento(self._cx, doc_id)
        if not self._doc:
            self.titulo.setText("Documento ausente.")
            return
        self.titulo.setText(self._doc["titulo"])
        self._esquerda = ler_spread(self._cx, doc_id)
        if self._esquerda % 2 == 0:
            self._esquerda -= 1
        self._carregar()
        self._atualizar_expectativa(0)
        self._volume(self.volume.value())

    def fechar(self) -> None:
        self._parar_fila(salvar=True)
        for sequencia in list(self._sequencias):
            sequencia.cancelar.set()
            try:
                sequencia.pronto.disconnect(self._audio_da_sequencia)
                sequencia.falhou.disconnect(self._sequencia_falhou)
            except RuntimeError:
                pass
            if not sequencia.wait(1500):
                _THREADS_VIVOS.append(sequencia)
        self._sequencias.clear()
        self._sequencia = None
        if self._cx is not None:
            fechar(self._cx)
            self._cx = None

    def _carregar(self) -> None:
        assert self._cx is not None and self._doc is not None
        total = int(self._doc["paginas"])
        self.kicker.setText(f"PÁGINAS  {self._esquerda}–{min(self._esquerda + 1, total)}  DE  {total}")
        self._paginas.clear()
        for numero in (self._esquerda, self._esquerda + 1):
            if numero > total:
                continue
            pagina = self._cx.execute(
                "SELECT * FROM pagina WHERE documento_id = ? AND numero = ?",
                (self._doc["id"], numero),
            ).fetchone()
            if pagina:
                self._paginas[numero] = dict(pagina)
        self._montar(self.esquerda, self._paginas.get(self._esquerda))
        self._montar(self.direita, self._paginas.get(self._esquerda + 1))
        self.anterior.setEnabled(self._esquerda > 1)
        self.proxima.setEnabled(self._esquerda + 1 < total)
        salvar_spread(self._cx, int(self._doc["id"]), self._esquerda)
        QTimer.singleShot(0, self._altura_do_miolo)

    def _altura_do_miolo(self) -> None:
        altura = max(
            self.esquerda.sizeHint().height(),
            self.direita.sizeHint().height(),
            self.esquerda.minimumSizeHint().height(),
            self.direita.minimumSizeHint().height(),
        )
        self.spread.setMinimumHeight(max(200, altura))

    def _montar(self, coluna: _Coluna, pagina: dict | None) -> None:
        assert self._cx is not None
        if pagina is None:
            coluna.mostrar(None, [], {})
            return
        blocos = blocos_da_pagina(self._cx, int(pagina["id"]))
        palavras = {
            int(bloco["id"]): palavras_do_bloco(self._cx, int(bloco["id"]))
            for bloco in blocos
            if bloco["audio_relpath"]
        }
        coluna.mostrar(pagina, blocos, palavras)

    def _anterior(self) -> None:
        if self._esquerda <= 1:
            return
        self._parar_fila(salvar=True)
        self._esquerda -= 2
        self._carregar()

    def _proxima(self) -> None:
        assert self._doc is not None
        if self._esquerda + 1 >= int(self._doc["paginas"]):
            return
        self._parar_fila(salvar=True)
        self._esquerda += 2
        self._carregar()

    def _buscar(self) -> None:
        if self._cx is None or self._doc is None:
            return
        achado = buscar(self._cx, int(self._doc["id"]), self.busca.text())
        if not achado:
            self.nota.setText("Não encontrei esse trecho.")
            return
        numero = int(achado["pagina_numero"])
        self._parar_fila(salvar=True)
        self._esquerda = numero if numero % 2 else numero - 1
        self._carregar()
        self.nota.setText(f"Trecho na página {numero}.")

    def _ouvir_tudo(self) -> None:
        if self._continuo:
            self._parar_fila(salvar=True)
            self.faixa.definir("Leitura interrompida. Ouvir tudo continua de onde você parou.", [])
            return
        if self._cx is None or self._doc is None or not self.tocador.disponivel():
            return
        blocos = narracao_desde(self._cx, int(self._doc["id"]), self._esquerda)
        if not blocos:
            self.nota.setText("Não há texto para narrar daqui em diante.")
            return
        self._continuo = True
        self._fila = blocos
        self._indice_fila = 0
        self._ouvidos.clear()
        self._descontado = 0
        self._aguardando_id = None
        self._base_ms = int(expectativa(self._cx, int(self._doc["id"]))["restante_ms"])
        self._ouvir.setText("Parar leitura")
        self._iniciar_sequencia([int(bloco["id"]) for bloco in blocos])
        self._tentar_tocar_indice()

    def _audio_da_sequencia(self, bloco_id: int) -> None:
        if not self._continuo or self._cx is None:
            return
        fresco = bloco_por_id(self._cx, bloco_id)
        if fresco is None:
            return
        for indice, bloco in enumerate(self._fila):
            if int(bloco["id"]) == bloco_id:
                self._fila[indice] = fresco
                break
        if self._aguardando_id == bloco_id:
            self._tentar_tocar_indice()

    def _sequencia_falhou(self, mensagem: str) -> None:
        if not self._continuo:
            return
        self.nota.setText(mensagem)

    def _tentar_tocar_indice(self) -> None:
        if not self._continuo or self._cx is None:
            return
        while self._indice_fila < len(self._fila):
            bloco = self._fila[self._indice_fila]
            if not bloco.get("audio_relpath"):
                fresco = bloco_por_id(self._cx, int(bloco["id"]))
                if fresco and fresco.get("audio_relpath"):
                    self._fila[self._indice_fila] = fresco
                    bloco = fresco
                elif fresco and fresco.get("erro") and not fresco.get("audio_relpath"):
                    self._indice_fila += 1
                    continue
                else:
                    self._aguardando_id = int(bloco["id"])
                    if self._bloco_atual is None or not self.tocador.tocando():
                        self.faixa.definir("Gerando a voz deste trecho. A leitura segue em seguida.", [])
                    self.nota.setText("A voz entra em sequência. A frase que já está no ar não é cortada.")
                    return
            self._aguardando_id = None
            numero = int(bloco["pagina_numero"])
            mesmo_par = self._esquerda <= numero <= self._esquerda + 1
            self._tocar_atual()
            if not mesmo_par:
                self._acompanhar_pagina(numero)
                self._revelar(int(bloco["id"]))
            return
        self._encerrar_continuo("A leitura chegou ao fim.")

    def _acompanhar_pagina(self, numero: int) -> None:
        if self._esquerda <= numero <= self._esquerda + 1:
            return
        self._esquerda = numero if numero % 2 else numero - 1
        self._carregar()

    def _iniciar_sequencia(self, ids: list[int]) -> None:
        self._pedir_fim_da_sequencia()
        sequencia = _Sequencia(ids)
        self._sequencias.append(sequencia)
        self._sequencia = sequencia
        sequencia.pronto.connect(self._audio_da_sequencia)
        sequencia.falhou.connect(self._sequencia_falhou)
        sequencia.finished.connect(lambda seq=sequencia: self._soltar_sequencia(seq))
        sequencia.start()

    def _pedir_fim_da_sequencia(self) -> None:
        if self._sequencia is None:
            return
        self._sequencia.cancelar.set()
        self._sequencia = None

    def _soltar_sequencia(self, sequencia: _Sequencia) -> None:
        if sequencia in self._sequencias:
            self._sequencias.remove(sequencia)
        if self._sequencia is sequencia:
            self._sequencia = None
        sequencia.deleteLater()

    def _encerrar_continuo(self, mensagem: str) -> None:
        self._continuo = False
        self._aguardando_id = None
        self._pedir_fim_da_sequencia()
        self._ouvir.setText("Ouvir tudo")
        self._timer.stop()
        self.ler.setText("Ler")
        self._limpar_marcas()
        self._bloco_atual = None
        self._indice_fila = -1
        self._fila = []
        self._concluir_se_der()
        self._atualizar_expectativa(0)
        self.faixa.definir(mensagem, [])

    def _ler(self) -> None:
        if self._continuo and self._aguardando_id is not None and self._bloco_atual is None:
            return
        if self._bloco_atual is not None and self.tocador.tocando():
            self.tocador.pausar()
            self.ler.setText("Ler")
            self._timer.stop()
            return
        if self._bloco_atual is not None and self._indice_fila >= 0:
            self.tocador.retomar()
            self.ler.setText("Pausar")
            self._timer.start()
            return
        if self._cx is None or self._doc is None:
            return
        if not self.tocador.disponivel():
            return
        fila = self._audios_do_spread()
        if not fila:
            self.faixa.definir("Estas páginas ainda não têm áudio. Clique num trecho ou continue o lote no estúdio.", [])
            self._concluir_se_der()
            self._atualizar_expectativa(0)
            return
        self._fila = fila
        self._indice_fila = 0
        self._ouvidos.clear()
        self._descontado = 0
        self._base_ms = int(expectativa(self._cx, int(self._doc["id"]))["restante_ms"])
        self._tocar_atual()

    def _audios_do_spread(self) -> list[dict]:
        assert self._cx is not None
        saida = []
        for numero in (self._esquerda, self._esquerda + 1):
            pagina = self._paginas.get(numero)
            if not pagina:
                continue
            for bloco in blocos_da_pagina(self._cx, int(pagina["id"])):
                if bloco["audio_relpath"]:
                    saida.append(bloco)
        return saida

    def _tocar_atual(self) -> None:
        if self._indice_fila < 0 or self._indice_fila >= len(self._fila):
            return
        bloco = self._fila[self._indice_fila]
        self._preparar_bloco(bloco)
        caminho = absoluto(bloco["audio_relpath"])
        if caminho is None or not caminho.exists():
            self._fim_do_clipe()
            return
        self._passo += 1
        self.tocador.tocar(caminho)
        self.tocador.volume(self.volume.value())
        QTimer.singleShot(120, lambda: self.tocador.volume(self.volume.value()))
        self.ler.setText("Pausar")
        self._timer.start()
        self._revelar(int(bloco["id"]))

    def _preparar_bloco(self, bloco: dict) -> None:
        assert self._cx is not None
        self._limpar_marcas()
        self._bloco_atual = bloco
        self._palavras = palavras_do_bloco(self._cx, int(bloco["id"]))
        self.faixa.definir(bloco["texto"] or "", self._palavras)
        self.seek.setRange(0, max(1, int(bloco["duracao_ms"] or 1)))
        self.seek.setValue(0)

    def _clicar_bloco(self, bloco_id: int) -> None:
        if self._cx is None:
            return
        if self._continuo:
            self._parar_fila(salvar=False)
        bloco = bloco_por_id(self._cx, bloco_id)
        if not bloco:
            return
        if bloco["tipo"] == "imagem":
            return
        if bloco["audio_relpath"]:
            self._fila = [bloco]
            self._indice_fila = 0
            self._ouvidos.clear()
            self._descontado = 0
            self._base_ms = int(expectativa(self._cx, int(bloco["documento_id"]))["restante_ms"])
            self._tocar_atual()
            return
        if self._demanda is not None:
            self.nota.setText("Já estou gerando um trecho.")
            return
        escolha = decidir()
        if not escolha["sob_demanda"]:
            self.nota.setText("Sem folga de memória para gerar este trecho agora. Ele espera o lote.")
            return
        self.nota.setText("Gerando a voz deste trecho.")
        self.ler.setEnabled(False)
        self._demanda = _Demanda(bloco_id, bool(escolha["whisper"]))
        self._demanda.terminou.connect(self._demanda_pronta)
        self._demanda.falhou.connect(self._demanda_falhou)
        self._demanda.finished.connect(self._demanda_fim)
        self._demanda.start()

    def _demanda_pronta(self, bloco_id: int) -> None:
        self.nota.setText("Trecho pronto.")
        self.ler.setEnabled(True)
        self._carregar()
        self._clicar_bloco(bloco_id)

    def _demanda_falhou(self, mensagem: str) -> None:
        self.ler.setEnabled(True)
        self.nota.setText(mensagem)

    def _demanda_fim(self) -> None:
        self._demanda = None

    def _tick(self) -> None:
        if self._bloco_atual is None:
            return
        posicao = self.tocador.tempo()
        total = self.tocador.duracao() or int(self._bloco_atual["duracao_ms"] or 0)
        if not self._arrastando:
            self.seek.setRange(0, max(1, total))
            self.seek.setValue(min(posicao, total))
        self.tempo.setText(f"{relogio(posicao)} / {relogio(total)}")
        indice = _indice_palavra(self._palavras, posicao)
        self.faixa.marcar(indice)
        caixa = self._caixa(int(self._bloco_atual["id"]))
        if caixa is not None:
            caixa.marcar(indice)
        self._atualizar_expectativa(posicao)

    def _fim_do_clipe(self) -> None:
        # O VLC avisa ainda dentro do callback. O próximo play espera um instante.
        passo = self._passo
        QTimer.singleShot(50, lambda: self._avancar_se(passo))

    def _avancar_se(self, passo: int) -> None:
        if passo != self._passo:
            return
        self._avancar()

    def _avancar(self) -> None:
        anterior = self._bloco_atual
        if anterior is not None:
            self._ouvidos.add(int(anterior["id"]))
            self._descontado += int(anterior["duracao_ms"] or 0)
        if self._continuo:
            if anterior is not None and self._indice_fila + 1 < len(self._fila):
                proxima = int(self._fila[self._indice_fila + 1]["pagina_numero"])
                if int(anterior["pagina_numero"]) != proxima:
                    self._marcar_pagina_se_ouvida(int(anterior["pagina_numero"]))
            self._indice_fila += 1
            self._tentar_tocar_indice()
            return
        if self._indice_fila + 1 < len(self._fila):
            self._indice_fila += 1
            self._tocar_atual()
            return
        self._timer.stop()
        self.ler.setText("Ler")
        self._limpar_marcas()
        self._bloco_atual = None
        self._indice_fila = -1
        self._fila = []
        self._concluir_se_der()
        self._atualizar_expectativa(0)
        self.faixa.definir("Estas duas páginas chegaram ao fim do áudio. Ler abre as próximas.", [])

    def _concluir_se_der(self) -> None:
        if self._cx is None or self._doc is None:
            return
        doc_id = int(self._doc["id"])
        for numero, pagina in self._paginas.items():
            if pendentes_na_pagina(self._cx, int(pagina["id"])) > 0:
                continue
            audios = [
                int(bloco["id"])
                for bloco in blocos_da_pagina(self._cx, int(pagina["id"]))
                if bloco["audio_relpath"]
            ]
            if audios and not set(audios).issubset(self._ouvidos):
                continue
            marcar_pagina_lida(self._cx, doc_id, numero)
        self._base_ms = int(expectativa(self._cx, doc_id)["restante_ms"])
        self._descontado = 0

    def _atualizar_expectativa(self, posicao: int) -> None:
        if self._cx is None or self._doc is None:
            return
        dados = expectativa(self._cx, int(self._doc["id"]))
        paginas = int(dados["paginas"] or 0)
        lidas = int(dados["lidas"] or 0)
        restante = max(0, int(dados["restante_ms"] or 0) - self._descontado - max(0, posicao))
        faltam = int(dados["faltam"] or 0)
        self.progresso.setRange(0, max(1, paginas))
        self.progresso.setValue(min(lidas, paginas))
        if int(dados["duracao_ms"] or 0) <= 0:
            self.expectativa.setText(
                "Ainda não há áudio bastante para prever o fim. "
                "O tempo entra conforme as páginas do lote ficam prontas."
            )
            self.nota.setText(f"{lidas} de {paginas} páginas concluídas.")
            return
        self.expectativa.setText(
            f"A leitura termina por volta das {por_volta(restante)}. "
            f"Restam {duracao(restante)}. "
            f"{lidas} de {paginas} páginas concluídas."
        )
        if self._continuo:
            if self._aguardando_id is not None:
                self.nota.setText("Gerando o próximo trecho agora. A frase que está tocando segue até o fim.")
            else:
                self.nota.setText("Leitura contínua. O áudio entra em sequência, sem cortar a narração.")
            return
        if faltam:
            self.nota.setText(
                f"Há {faltam} trechos ainda no lote. A previsão cresce quando esse áudio entra."
            )
        else:
            self.nota.setText("O áudio deste documento já está gerado.")

    def _caixa(self, bloco_id: int) -> _Caixa | None:
        return self.esquerda.caixa(bloco_id) or self.direita.caixa(bloco_id)

    def _revelar(self, bloco_id: int) -> None:
        caixa = self._caixa(bloco_id)
        if caixa is not None:
            self.scroll.ensureWidgetVisible(caixa, 40, 80)

    def _limpar_marcas(self) -> None:
        for caixa in self.esquerda._caixas + self.direita._caixas:
            caixa.limpar()
        self.faixa.limpar_marca()

    def _segurar(self) -> None:
        self._arrastando = True

    def _soltar(self) -> None:
        self._arrastando = False
        self.tocador.buscar_ms(self.seek.value())

    def _volume(self, valor: int) -> None:
        self.tocador.volume(valor)
        QSettings("Biblioteca", "Audio").setValue("volume", int(valor))

    def _marcar_pagina_se_ouvida(self, numero: int) -> None:
        if self._cx is None or self._doc is None:
            return
        pagina = self._cx.execute(
            "SELECT id FROM pagina WHERE documento_id = ? AND numero = ?",
            (int(self._doc["id"]), numero),
        ).fetchone()
        if pagina is None:
            return
        pendentes = [
            int(bloco["id"])
            for bloco in blocos_da_pagina(self._cx, int(pagina["id"]))
            if bloco["dublar"] and bloco["audio_relpath"]
        ]
        if pendentes and not set(pendentes).issubset(self._ouvidos):
            return
        marcar_pagina_lida(self._cx, int(self._doc["id"]), numero)

    def _parar_fila(self, *, salvar: bool) -> None:
        self._continuo = False
        self._aguardando_id = None
        self._passo += 1
        self.tocador._ignorar_fim = True
        self._pedir_fim_da_sequencia()
        self._timer.stop()
        self.tocador.parar()
        self._limpar_marcas()
        self._bloco_atual = None
        self._fila = []
        self._indice_fila = -1
        self.ler.setText("Ler")
        if hasattr(self, "_ouvir"):
            self._ouvir.setText("Ouvir tudo")
        if salvar and self._cx is not None and self._doc is not None:
            salvar_spread(self._cx, int(self._doc["id"]), self._esquerda)

    def showEvent(self, evento) -> None:
        if self._doc is not None and self._bloco_atual is None:
            self._carregar()
            self._atualizar_expectativa(0)
        super().showEvent(evento)


def _indice_palavra(palavras: list[dict], ms: int) -> int | None:
    if not palavras:
        return None
    lo = 0
    hi = len(palavras)
    while lo < hi:
        meio = (lo + hi) // 2
        if int(palavras[meio]["inicio_ms"]) <= ms:
            lo = meio + 1
        else:
            hi = meio
    indice = lo - 1
    if indice < 0:
        return 0
    return indice
