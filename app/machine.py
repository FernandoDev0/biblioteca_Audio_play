"""O que esta máquina faz ao vivo e o que fica no lote.

Caso 1, sempre: a marcação amarela acompanha a palavra enquanto o Opus toca.
Isso é só relógio e cues, não carrega modelo.

Caso 2, só com folga de memória: um trecho que ainda não tem áudio, quando a
pessoa clica nele. Gera só aquele clipe. O livro inteiro nunca entra aqui.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = (
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    )


def memoria_livre_mb() -> int:
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.ullAvailPhys / (1024 * 1024))


def decidir() -> dict:
    livre = memoria_livre_mb()
    cpus = os.cpu_count() or 1
    sob_demanda = livre >= 1200 and cpus >= 2
    return {
        "karaoke": True,
        "sob_demanda": sob_demanda,
        "whisper": sob_demanda and livre >= 2500 and cpus >= 4,
        "livre_mb": livre,
        "cpus": cpus,
    }


def frase_maquina() -> str:
    escolha = decidir()
    folga = f"{escolha['livre_mb'] / 1024:.1f} GB livres".replace(".", ",")
    if escolha["sob_demanda"]:
        return (
            f"Nesta máquina ({folga}, {escolha['cpus']} núcleos) o livro inteiro vai em lote. "
            "Ao vivo ficam só duas coisas: a marcação amarela durante a leitura, "
            "e um trecho avulso quando você clica nele."
        )
    return (
        f"Nesta máquina ({folga}) o livro vai em lote. "
        "A marcação amarela continua ao vivo. "
        "Um clique num trecho sem áudio espera o lote: não há folga para gerar na hora."
    )
