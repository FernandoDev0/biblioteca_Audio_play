"""MP3 da Francisca vira Opus em Ogg. O PyAV já veio com o faster-whisper."""

from __future__ import annotations

import io
from pathlib import Path


def mp3_para_opus(mp3: bytes, destino: Path) -> int:
    import av

    destino.parent.mkdir(parents=True, exist_ok=True)
    entrada = av.open(io.BytesIO(mp3), mode="r")
    try:
        duracao_ms = int(entrada.duration / 1000) if entrada.duration else 0
        saida = av.open(str(destino), mode="w", format="ogg")
        try:
            fluxo = saida.add_stream("libopus", rate=48000)
            fluxo.layout = "mono"
            fluxo.bit_rate = 32000
            resample = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=48000)
            for frame in entrada.decode(audio=0):
                for convertido in _lista(resample.resample(frame)):
                    for pacote in fluxo.encode(convertido):
                        saida.mux(pacote)
            for convertido in _lista(resample.resample(None)):
                for pacote in fluxo.encode(convertido):
                    saida.mux(pacote)
            for pacote in fluxo.encode(None):
                saida.mux(pacote)
        finally:
            saida.close()
    finally:
        entrada.close()
    if destino.stat().st_size < 16:
        raise RuntimeError("Opus vazio")
    return duracao_ms


def _lista(resultado) -> list:
    if resultado is None:
        return []
    if isinstance(resultado, list):
        return resultado
    return [resultado]
