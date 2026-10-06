from datetime import datetime, timedelta


def duracao(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos:02d} min"
    if minutos:
        return f"{minutos} min"
    return f"{segundos} s"


def relogio(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    minutos, segundos = divmod(total, 60)
    horas, minutos = divmod(minutos, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segundos:02d}"
    return f"{minutos:02d}:{segundos:02d}"


def por_volta(ms: int) -> str:
    fim = datetime.now() + timedelta(milliseconds=max(0, int(ms)))
    return fim.strftime("%H:%M")
