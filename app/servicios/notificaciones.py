"""Notificaciones por correo (interfaz INotificacion de la EV2).

En desarrollo los correos quedan en una bandeja de salida visible en el panel
del productor. En la nube se activa el envío por SMTP de un proveedor de
correo transaccional (SaaS) solo con variables de entorno.
"""
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage

from flask import current_app

from ..db import ahora, get_db


class INotificacion(ABC):
    @abstractmethod
    def enviar(self, destinatario: str, asunto: str, cuerpo: str) -> None: ...


class CorreoConsola(INotificacion):
    def enviar(self, destinatario, asunto, cuerpo):
        get_db().execute(
            "INSERT INTO correos (fecha, destinatario, asunto, cuerpo) VALUES (?, ?, ?, ?)",
            (ahora(), destinatario, asunto, cuerpo),
        )
        current_app.logger.info("Correo (demo) a %s: %s", destinatario, asunto)


class CorreoSMTP(INotificacion):
    def enviar(self, destinatario, asunto, cuerpo):
        cfg = current_app.config
        mensaje = EmailMessage()
        mensaje["From"] = cfg["CORREO_REMITENTE"]
        mensaje["To"] = destinatario
        mensaje["Subject"] = asunto
        mensaje.set_content(cuerpo)
        contexto = ssl.create_default_context()  # verifica el certificado del servidor
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as smtp:
            smtp.starttls(context=contexto)
            smtp.login(cfg["SMTP_USUARIO"], cfg["SMTP_CLAVE"])
            smtp.send_message(mensaje)


def obtener_notificador() -> INotificacion:
    if current_app.config["CORREO_BACKEND"] == "smtp":
        return CorreoSMTP()
    return CorreoConsola()


def enviar_seguro(destinatario, asunto, cuerpo):
    """Un correo que falla no debe deshacer una venta ya pagada: se registra el
    error y la compra sigue disponible en "Mis compras"."""
    try:
        obtener_notificador().enviar(destinatario, asunto, cuerpo)
        return True
    except Exception:
        current_app.logger.exception("Falló el envío de correo a %s", destinatario)
        return False
