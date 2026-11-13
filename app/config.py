"""Configuración de BeatStore.

Toda la configuración sensible se lee desde variables de entorno (principio
12-factor), de modo que el mismo contenedor funcione en local y en la nube
sin cambiar el código ni dejar secretos dentro del repositorio.
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(nombre, defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes"}


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")

    # Directorio de datos: base SQLite, archivos privados y previews.
    # En la nube se monta un disco persistente en esta ruta.
    DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "instance"))
    DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "beatstore.db"))
    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", DATA_DIR / "almacenamiento"))

    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Cookies de sesión (OWASP A07: gestión de sesiones)
    SESSION_COOKIE_NAME = "beatstore_sesion"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", APP_ENV == "production")
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

    # Límite de tamaño de cada petición (evita subir archivos gigantes)
    MAX_CONTENT_LENGTH = 80 * 1024 * 1024

    # Reglas de negocio de la entrega (RNF02 de la EV2)
    DESCARGA_DIAS_VIGENCIA = 7
    DESCARGA_MAX = 5

    # Autenticación: bloqueo tras intentos fallidos
    LOGIN_MAX_INTENTOS = 5
    LOGIN_BLOQUEO_MINUTOS = 15

    # Integraciones externas (adaptadores intercambiables)
    PASARELA_PAGO = os.environ.get("PASARELA_PAGO", "sandbox")
    CORREO_BACKEND = os.environ.get("CORREO_BACKEND", "consola")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USUARIO = os.environ.get("SMTP_USUARIO", "")
    SMTP_CLAVE = os.environ.get("SMTP_CLAVE", "")
    CORREO_REMITENTE = os.environ.get("CORREO_REMITENTE", "BeatStore <no-responder@beatstore.cl>")
    CORREO_PRODUCTOR = os.environ.get("CORREO_PRODUCTOR", "productor@beatstore.cl")

    NOMBRE_PRODUCTOR = os.environ.get("NOMBRE_PRODUCTOR", "Matías Herrera (MH Beats)")

    TESTING = False


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SECRET_KEY = "clave-solo-para-pruebas"
    SESSION_COOKIE_SECURE = False
