"""Controles de seguridad transversales (buenas prácticas OWASP).

Cada función indica entre paréntesis el riesgo del OWASP Top 10:2025 que ayuda
a mitigar.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .db import ahora, get_db

# ---------------------------------------------------------------------------
# Validación de datos de entrada (A05 Injection / A06 Insecure Design)
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
GENEROS = ["Trap", "Reggaetón", "Drill", "R&B", "Boom bap"]
TONALIDADES = [
    "Do mayor", "Do menor", "Re mayor", "Re menor", "Mi mayor", "Mi menor",
    "Fa mayor", "Fa menor", "Sol mayor", "Sol menor", "La mayor", "La menor",
    "Si mayor", "Si menor", "Do# menor", "Fa# menor", "Sol# menor", "Si bemol menor",
]
MOODS = ["Oscuro", "Melódico", "Bailable", "Triste", "Agresivo", "Chill"]


def validar_email(email):
    return bool(email) and len(email) <= 254 and EMAIL_RE.match(email) is not None


def validar_password(password, email=""):
    """Política de contraseñas (A07). Devuelve una lista de errores."""
    errores = []
    if len(password) < 10:
        errores.append("La contraseña debe tener al menos 10 caracteres.")
    if len(password) > 128:
        errores.append("La contraseña no puede superar los 128 caracteres.")
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", password) or not re.search(r"\d", password):
        errores.append("La contraseña debe combinar letras y números.")
    usuario = email.split("@")[0].lower() if email else ""
    if usuario and len(usuario) >= 4 and usuario in password.lower():
        errores.append("La contraseña no puede contener tu correo.")
    return errores


def entero_en_rango(valor, minimo, maximo):
    """Convierte a entero solo si está dentro del rango; si no, devuelve None."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if minimo <= numero <= maximo else None


def texto_limpio(valor, maximo):
    valor = (valor or "").strip()
    valor = re.sub(r"[\x00-\x1f\x7f]", "", valor)
    return valor[:maximo]


def celda_csv_segura(valor):
    """Evita la inyección de fórmulas al abrir el CSV en Excel (CWE-1236)."""
    texto = "" if valor is None else str(valor)
    if texto and texto[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


# ---------------------------------------------------------------------------
# Protección CSRF (A01 Broken Access Control)
# ---------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def verificar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("_csrf", "")
        if not esperado or not hmac.compare_digest(enviado, esperado):
            registrar_evento("CSRF_RECHAZADO", f"ruta={request.path}")
            abort(400, description="La sesión del formulario expiró. Recarga la página e inténtalo de nuevo.")


# ---------------------------------------------------------------------------
# Autenticación y control de acceso por roles (A01 / A07)
# ---------------------------------------------------------------------------
def usuario_actual():
    if "usuario" not in g:
        g.usuario = None
        usuario_id = session.get("usuario_id")
        if usuario_id:
            g.usuario = get_db().execute(
                "SELECT id, nombre, email, rol FROM usuarios WHERE id = ?", (usuario_id,)
            ).fetchone()
    return g.usuario


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if usuario_actual() is None:
            return redirect(url_for("auth.login", next=request.path))
        return vista(*args, **kwargs)

    return envoltura


def rol_requerido(rol):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                return redirect(url_for("auth.login", next=request.path))
            if usuario["rol"] != rol:
                registrar_evento("ACCESO_DENEGADO", f"ruta={request.path}")
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


def destino_seguro(destino):
    """Solo permite redirecciones internas (evita open redirect)."""
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return None


# ---------------------------------------------------------------------------
# Limitador de peticiones (A07: fuerza bruta / A06: abuso de funciones)
# ---------------------------------------------------------------------------
class LimitadorPeticiones:
    """Ventana deslizante en memoria. En producción con varias instancias se
    reemplaza por Redis, como se propuso en la arquitectura de la EV2."""

    def __init__(self):
        self._registros = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, clave, maximo, ventana_segundos):
        ahora_s = time.monotonic()
        with self._lock:
            cola = self._registros[clave]
            while cola and ahora_s - cola[0] > ventana_segundos:
                cola.popleft()
            if len(cola) >= maximo:
                return False
            cola.append(ahora_s)
            return True

    def limpiar(self):
        with self._lock:
            self._registros.clear()


limitador = LimitadorPeticiones()


def limitar(maximo, ventana_segundos):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if request.method == "POST":
                clave = f"{request.endpoint}:{ip_cliente()}"
                if not limitador.permitir(clave, maximo, ventana_segundos):
                    registrar_evento("LIMITE_PETICIONES", f"ruta={request.path}")
                    abort(429)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


# ---------------------------------------------------------------------------
# Registro de auditoría (A09 Security Logging & Alerting Failures)
# ---------------------------------------------------------------------------
def ip_cliente():
    return request.remote_addr or "desconocida"


def registrar_evento(evento, detalle="", usuario_id=None):
    """Guarda eventos de seguridad y de negocio. Nunca guarda contraseñas."""
    if usuario_id is None and session.get("usuario_id"):
        usuario_id = session.get("usuario_id")
    try:
        get_db().execute(
            "INSERT INTO auditoria (fecha, usuario_id, evento, detalle, ip) VALUES (?, ?, ?, ?, ?)",
            (ahora(), usuario_id, evento, detalle[:500], ip_cliente()),
        )
    except Exception:  # la auditoría nunca debe botar la aplicación
        current_app.logger.exception("No se pudo registrar el evento de auditoría %s", evento)
    current_app.logger.info("AUDITORIA %s usuario=%s ip=%s %s", evento, usuario_id, ip_cliente(), detalle)


# ---------------------------------------------------------------------------
# Utilidades criptográficas (A04 Cryptographic Failures)
# ---------------------------------------------------------------------------
def hash_token(token):
    """Los tokens de descarga se guardan hasheados: si alguien roba la base de
    datos no obtiene enlaces válidos."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cabeceras de seguridad (A02 Security Misconfiguration)
# ---------------------------------------------------------------------------
CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; "
    "script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)


def aplicar_cabeceras(respuesta):
    respuesta.headers.setdefault("Content-Security-Policy", CSP)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    respuesta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if current_app.config.get("APP_ENV") == "production":
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if session.get("usuario_id") and respuesta.mimetype == "text/html":
        # Las páginas con datos personales no quedan guardadas en caché
        respuesta.headers["Cache-Control"] = "no-store"
    respuesta.headers.pop("Server", None)
    return respuesta
