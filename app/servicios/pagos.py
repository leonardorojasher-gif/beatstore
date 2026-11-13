"""Pasarela de pagos (interfaz IPasarelaPago, patrón Adapter de la EV2).

El prototipo usa una pasarela simulada (sandbox) que reproduce el flujo de
Webpay Plus: crear transacción -> el comprador paga en el sitio de la
pasarela -> la pasarela devuelve un token -> la tienda confirma (commit).

BeatStore nunca recibe ni guarda datos de tarjetas: eso lo hace la pasarela.
Para pasar a producción se agrega un WebpayPlusAdapter o MercadoPagoAdapter
que cumpla esta misma interfaz, sin tocar el resto del sistema.
"""
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass

from flask import current_app, url_for

from ..db import ahora, get_db


@dataclass
class ResultadoPago:
    aprobado: bool
    orden_id: int
    monto: int
    codigo_autorizacion: str | None = None
    mensaje: str = ""


class IPasarelaPago(ABC):
    @abstractmethod
    def iniciar_transaccion(self, orden_id: int, monto: int, url_retorno: str) -> tuple[str, str]:
        """Devuelve (token, url_de_pago)."""

    @abstractmethod
    def confirmar_transaccion(self, token: str) -> ResultadoPago:
        """Confirma (commit) la transacción y devuelve el resultado oficial."""

    @abstractmethod
    def anular(self, token: str) -> bool:
        """Anula o reembolsa una transacción ya confirmada."""


class PasarelaSandbox(IPasarelaPago):
    """Simula el sistema externo de pagos usando su propia tabla."""

    def iniciar_transaccion(self, orden_id, monto, url_retorno):
        token = secrets.token_hex(24)
        get_db().execute(
            "INSERT INTO sandbox_transacciones (token, orden_id, monto, url_retorno, creada_en) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, orden_id, monto, url_retorno, ahora()),
        )
        return token, url_for("sandbox.pagar", token_ws=token)

    def confirmar_transaccion(self, token):
        db = get_db()
        tx = db.execute("SELECT * FROM sandbox_transacciones WHERE token = ?", (token,)).fetchone()
        if tx is None:
            return ResultadoPago(False, 0, 0, mensaje="Transacción inexistente")
        if tx["estado"] == "AUTORIZADA":
            codigo = f"{secrets.randbelow(10**6):06d}"
            db.execute("UPDATE sandbox_transacciones SET estado = 'CONFIRMADA' WHERE token = ?", (token,))
            return ResultadoPago(True, tx["orden_id"], tx["monto"], codigo, "Pago aprobado")
        if tx["estado"] == "CONFIRMADA":
            # Un token solo se puede confirmar una vez (evita reutilizarlo)
            return ResultadoPago(False, tx["orden_id"], tx["monto"], mensaje="Transacción ya confirmada")
        return ResultadoPago(False, tx["orden_id"], tx["monto"], mensaje="Pago rechazado por el emisor")

    def anular(self, token):
        cursor = get_db().execute(
            "UPDATE sandbox_transacciones SET estado = 'ANULADA' WHERE token = ? AND estado = 'CONFIRMADA'",
            (token,),
        )
        return cursor.rowcount == 1


def obtener_pasarela() -> IPasarelaPago:
    proveedor = current_app.config["PASARELA_PAGO"]
    if proveedor == "sandbox":
        return PasarelaSandbox()
    raise RuntimeError(f"Pasarela de pago no configurada: {proveedor}")
