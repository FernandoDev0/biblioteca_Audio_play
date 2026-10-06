"""Voz da Francisca, neural, com a fronteira de cada palavra."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import edge_tts

from app.align import alinhar_palavras, estimar_palavras
from app.constantes import PITCH, RATE, VOLUME_VOZ, VOZ
from app.opus import mp3_para_opus
from app.paths import raiz_dados

_TICK_MS = 10_000


async def _falar(texto: str) -> tuple[bytes, list[dict]]:
    comunicacao = edge_tts.Communicate(
        texto,
        VOZ,
        rate=RATE,
        volume=VOLUME_VOZ,
        pitch=PITCH,
        boundary="WordBoundary",
    )
    audio = bytearray()
    palavras: list[dict] = []
    async for pedaco in comunicacao.stream():
        if pedaco["type"] == "audio":
            audio.extend(pedaco["data"])
        elif pedaco["type"] == "WordBoundary":
            inicio = int(pedaco["offset"] / _TICK_MS)
            fim = inicio + int(pedaco["duration"] / _TICK_MS)
            token = (pedaco.get("text") or "").strip()
            if token:
                palavras.append({"texto": token, "inicio_ms": inicio, "fim_ms": fim})
    if not audio:
        raise RuntimeError("a Francisca não devolveu áudio")
    return bytes(audio), palavras


def sintetizar(texto: str) -> tuple[bytes, list[dict]]:
    ultimo: Exception | None = None
    for tentativa in range(2):
        try:
            return asyncio.run(_falar(texto))
        except Exception as erro:
            ultimo = erro
            if tentativa == 0:
                time.sleep(1.0)
    assert ultimo is not None
    raise ultimo


def gravar_clipe(
    texto: str,
    opus_destino: Path,
    cues_destino: Path,
    *,
    permitir_whisper: bool = False,
) -> tuple[int, list[dict]]:
    mp3, palavras = sintetizar(texto)
    duracao = mp3_para_opus(mp3, opus_destino)
    if palavras:
        duracao = max(duracao, palavras[-1]["fim_ms"])
    elif permitir_whisper:
        try:
            palavras = alinhar_palavras(opus_destino, raiz_dados() / "cache" / "whisper")
            if palavras:
                duracao = max(duracao, palavras[-1]["fim_ms"])
        except Exception:
            palavras = []
    if not palavras:
        palavras = estimar_palavras(texto, duracao)
    cues_destino.parent.mkdir(parents=True, exist_ok=True)
    cues_destino.write_text(
        json.dumps(
            {"schema": 1, "voz": VOZ, "duracao_ms": duracao, "palavras": palavras},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return duracao, palavras
