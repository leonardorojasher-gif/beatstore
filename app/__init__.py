"""BeatStore: tienda en línea de licencias de beats (prototipo EV3).

Fábrica de la aplicación Flask: carga la configuración, registra los módulos
(blueprints) y aplica los controles de seguridad comunes a todas las rutas.
"""
import logging
import secrets
import sys
import uuid

from flask import Flask, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from .config import Config
from .seguridad import aplicar_cabeceras, csrf_token, usuario_actual, verificar_csrf
from .utilidades import clp, fecha_local


def create_app(config_obj=Config):
    app = Flask(__name__)
    app.config.from_object(config_obj)

    _configurar_logs(app)
    _configurar_secreto(app)

    if app.config["APP_ENV"] == "production":
        # Detrás del balanceador de la nube: confiar solo en el primer proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    app.config["STORAGE_DIR"].mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db.init_db()

    from .rutas import admin, auth, compra, publico, sandbox

    app.register_blueprint(publico.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(compra.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(sandbox.bp)

    @app.before_request
    def antes_de_cada_peticion():
        session.permanent = True  # la sesión expira tras 30 min sin actividad
        verificar_csrf()

    app.after_request(aplicar_cabeceras)

    @app.context_processor
    def variables_globales():
        return {
            "csrf_token": csrf_token,
            "usuario": usuario_actual(),
            "items_carrito": len(session.get("carrito", [])),
        }

    app.jinja_env.filters["clp"] = clp
    app.jinja_env.filters["fecha"] = fecha_local

    _registrar_errores(app)
    _registrar_comandos(app)
    return app


def _configurar_logs(app):
    # Los logs van a la salida estándar: la plataforma en la nube los recolecta
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app.logger.handlers = [manejador]
    app.logger.setLevel(logging.INFO)


def _configurar_secreto(app):
    if app.config.get("SECRET_KEY"):
        return
    if app.config["APP_ENV"] == "production":
        # Falla de forma segura: no se inicia en producción sin una clave real
        raise RuntimeError("Falta la variable de entorno SECRET_KEY")
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.logger.warning("SECRET_KEY no definida: se generó una temporal (solo para desarrollo).")


def _registrar_errores(app):
    mensajes = {
        400: "La solicitud no es válida.",
        403: "No tienes permiso para ver esta página.",
        404: "La página que buscas no existe.",
        405: "Método no permitido.",
        413: "El archivo supera el tamaño máximo permitido.",
        429: "Demasiados intentos. Espera unos minutos y vuelve a intentarlo.",
    }

    @app.errorhandler(HTTPException)
    def error_http(error):
        mensaje = error.description if error.code == 400 and error.description else mensajes.get(error.code, "Ocurrió un error.")
        return render_template("error.html", codigo=error.code, mensaje=mensaje), error.code

    @app.errorhandler(Exception)
    def error_inesperado(error):
        # No se muestran trazas al usuario: se registra un identificador para soporte
        id_error = uuid.uuid4().hex[:8]
        app.logger.exception("Error no controlado %s en %s", id_error, request.path)
        return render_template(
            "error.html", codigo=500,
            mensaje=f"Ocurrió un error inesperado. Código de soporte: {id_error}.",
        ), 500


def _registrar_comandos(app):
    import click

    from .demo import cargar_demo, crear_usuario

    @app.cli.command("crear-productor")
    @click.option("--nombre", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def crear_productor(nombre, email, password):
        """Crea la cuenta del productor (administrador de la tienda)."""
        crear_usuario(nombre, email, password, "PRODUCTOR")
        click.echo("Cuenta de productor creada.")

    @app.cli.command("cargar-demo")
    @click.option("--forzar", is_flag=True, help="Permite cargar la demo en producción.")
    def cargar_demo_cmd(forzar):
        """Crea cuentas de prueba y beats de ejemplo generados con FFmpeg."""
        if app.config["APP_ENV"] == "production" and not forzar:
            raise click.ClickException("No se cargan datos de demostración en producción.")
        for linea in cargar_demo():
            click.echo(linea)
