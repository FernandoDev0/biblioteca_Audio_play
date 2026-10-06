"""O socketpair do Python 3.14 recusa o par quando a porta local não volta igual.

Nesta máquina a conexão de loopback passa, mas a porta efêmera vista pelo
accept não é a do cliente. O asyncio precisa do par para existir. Sem ele,
a Francisca não fala.
"""

from __future__ import annotations

import socket
import sys


def garantir_socketpair() -> None:
    if sys.platform != "win32" or getattr(socket, "_biblioteca_socketpair", False):
        return
    original = socket.socketpair

    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        try:
            return original(family, type, proto)
        except ConnectionError as erro:
            if "Unexpected peer" not in str(erro):
                raise
            return _par(family, type, proto)

    socket.socketpair = socketpair
    socket._biblioteca_socketpair = True


def _par(family: int, tipo: int, proto: int):
    if family == socket.AF_INET:
        host = "127.0.0.1"
    elif family == socket.AF_INET6:
        host = "::1"
    else:
        raise ValueError("família de socket não suportada")
    escuta = socket.socket(family, tipo, proto)
    try:
        escuta.bind((host, 0))
        escuta.listen()
        endereco, porta = escuta.getsockname()[:2]
        cliente = socket.socket(family, tipo, proto)
        try:
            cliente.setblocking(False)
            try:
                cliente.connect((endereco, porta))
            except (BlockingIOError, InterruptedError):
                pass
            cliente.setblocking(True)
            servidor, _ = escuta.accept()
        except Exception:
            cliente.close()
            raise
    finally:
        escuta.close()
    return servidor, cliente
