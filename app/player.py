"""Reprodução do Opus pelo VLC que já está instalado na máquina."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def _carregar_vlc():
    pasta = Path(os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC"))
    biblioteca = pasta / "libvlc.dll"
    if biblioteca.exists():
        os.add_dll_directory(str(pasta))
        os.environ["PATH"] = str(pasta) + os.pathsep + os.environ.get("PATH", "")
    import vlc

    return vlc


class Tocador(QObject):
    terminou = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.erro = ""
        self._ok = False
        self._vlc = None
        self.player = None
        self.instance = None
        self._media = None
        self._ignorar_fim = False
        try:
            vlc = _carregar_vlc()
            self._vlc = vlc
            self.instance = vlc.Instance("--no-video", "--quiet", "--intf", "dummy")
            self.player = self.instance.media_player_new()
            self.player.event_manager().event_attach(
                vlc.EventType.MediaPlayerEndReached,
                self._evento_fim,
            )
            self._ok = True
        except Exception as erro:
            self.erro = str(erro)

    def _evento_fim(self, _evento) -> None:
        # Parar também dispara este aviso. Ignorar, senão a leitura recomeça
        # em cima do stop e o VLC derruba o processo.
        if self._ignorar_fim:
            return
        self.terminou.emit()

    def disponivel(self) -> bool:
        return self._ok

    def tocar(self, caminho: Path) -> None:
        self._ignorar_fim = False
        # A referência precisa ficar viva. Se o Python soltar o media,
        # o próximo stop do VLC encerra o processo.
        self._media = self.instance.media_new(str(caminho))
        self.player.set_media(self._media)
        self.player.play()

    def pausar(self) -> None:
        if self.player:
            self.player.pause()

    def retomar(self) -> None:
        if self.player:
            self.player.play()

    def parar(self) -> None:
        if not self.player:
            return
        self._ignorar_fim = True
        try:
            self.player.pause()
            self.player.stop()
        except Exception:
            return

    def tempo(self) -> int:
        if not self.player:
            return 0
        valor = self.player.get_time()
        return 0 if valor is None or valor < 0 else int(valor)

    def duracao(self) -> int:
        if not self.player:
            return 0
        valor = self.player.get_length()
        return 0 if valor is None or valor < 0 else int(valor)

    def buscar_ms(self, ms: int) -> None:
        if self.player:
            self.player.set_time(int(ms))

    def volume(self, valor: int) -> None:
        if self.player:
            self.player.audio_set_volume(max(0, min(100, int(valor))))

    def tocando(self) -> bool:
        if not self.player or self._vlc is None:
            return False
        return self.player.get_state() == self._vlc.State.Playing
