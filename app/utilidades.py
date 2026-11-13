from datetime import datetime


def clp(monto):
    """Formatea un monto en pesos chilenos: 30000 -> $30.000"""
    try:
        return "$" + f"{int(monto):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "$0"


def fecha_local(iso):
    """Muestra una fecha ISO en formato dd-mm-aaaa hh:mm (UTC)."""
    try:
        return datetime.fromisoformat(iso).strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return iso or ""
