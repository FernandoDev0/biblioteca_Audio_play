"""Alinhamento fino só quando a Francisca não devolve a fronteira da palavra.

Não roda no lote. É o reforço do caso 2, e só se a memória deixar.
"""

from __future__ import annotations

from pathlib import Path

_modelo = None


def alinhar_palavras(opus: Path, download_root: Path) -> list[dict]:
    global _modelo
    from faster_whisper import WhisperModel

    if _modelo is None:
        _modelo = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            download_root=str(download_root),
        )
    segmentos, _info = _modelo.transcribe(
        str(opus),
        language="pt",
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
    )
    palavras: list[dict] = []
    for segmento in segmentos:
        for palavra in segmento.words or []:
            token = (palavra.word or "").strip()
            if not token:
                continue
            inicio = int(float(palavra.start) * 1000)
            fim = int(max(float(palavra.end), float(palavra.start)) * 1000)
            palavras.append({"texto": token, "inicio_ms": inicio, "fim_ms": fim})
    return palavras


def estimar_palavras(texto: str, duracao_ms: int) -> list[dict]:
    tokens = [t for t in texto.split() if t]
    if not tokens or duracao_ms <= 0:
        return []
    pesos = [max(len(t), 1) for t in tokens]
    soma = sum(pesos)
    cursor = 0
    saida: list[dict] = []
    for token, peso in zip(tokens, pesos):
        passo = max(int(duracao_ms * peso / soma), 1)
        saida.append({"texto": token, "inicio_ms": cursor, "fim_ms": cursor + passo})
        cursor += passo
    saida[-1]["fim_ms"] = duracao_ms
    return saida
