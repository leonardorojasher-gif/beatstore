"""Acceso a datos con SQLite.

Todas las consultas usan parámetros (?) y nunca concatenan texto del usuario,
lo que evita la inyección SQL (OWASP A05:2025 Injection).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def ahora():
    """Fecha y hora UTC en formato ISO, igual en todos los registros."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db():
    if "db" not in g:
        ruta = Path(current_app.config["DATABASE_PATH"])
        ruta.parent.mkdir(parents=True, exist_ok=True)
        conexion = sqlite3.connect(ruta, timeout=10, isolation_level=None)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("PRAGMA journal_mode = WAL")
        g.db = conexion
    return g.db


def close_db(_error=None):
    conexion = g.pop("db", None)
    if conexion is not None:
        conexion.close()


class transaccion:
    """Bloque transaccional: confirma si todo sale bien y deshace si algo falla.

    Se usa BEGIN IMMEDIATE para tomar el bloqueo de escritura al inicio y
    evitar que dos compras simultáneas vendan la misma licencia exclusiva.
    """

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, tipo, _valor, _traza):
        if tipo is None:
            self.db.execute("COMMIT")
        else:
            self.db.execute("ROLLBACK")
        return False


def init_db():
    db = get_db()
    esquema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    db.executescript(esquema)


def init_app(app):
    app.teardown_appcontext(close_db)
