"""Pastas da biblioteca. Tudo que muda de máquina fica junto, em caminhos relativos."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[1]


def raiz_dados() -> Path:
    bruto = os.environ.get("BIBLIOTECA_DADOS")
    if bruto:
        return Path(bruto)
    return RAIZ_PROJETO / "biblioteca"


def banco() -> Path:
    return raiz_dados() / "banco" / "biblioteca.db"


def garantir_pastas() -> None:
    raiz = raiz_dados()
    for nome in ("banco", "pdf", "texto", "audio", "imagens", "cache", "cache/whisper"):
        (raiz / nome).mkdir(parents=True, exist_ok=True)


def relativo(caminho: Path) -> str:
    return caminho.resolve().relative_to(raiz_dados().resolve()).as_posix()


def absoluto(relativo_ou_vazio: str | None) -> Path | None:
    if not relativo_ou_vazio:
        return None
    raiz = raiz_dados().resolve()
    caminho = (raiz / relativo_ou_vazio).resolve()
    if caminho != raiz and raiz not in caminho.parents:
        raise ValueError("caminho fora da biblioteca")
    return caminho
