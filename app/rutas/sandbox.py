"""Pasarela de pagos simulada (representa a Webpay Plus en ambiente de pruebas).

En producción esta pantalla no existe en BeatStore: el comprador es enviado al
sitio de la pasarela real, que es quien recibe los datos de la tarjeta.
"""
from flask import Blueprint, abort, redirect, render_template, request

from ..db import get_db
from ..seguridad import login_requerido

bp = Blueprint("sandbox", __name__, url_prefix="/sandbox-webpay")


def _transaccion(token):
    if not token or len(token) > 100:
        abort(400)
    tx = get_db().execute("SELECT * FROM sandbox_transacciones WHERE token = ?", (token,)).fetchone()
    if tx is None:
        abort(404)
    return tx


@bp.get("/pagar")
@login_requerido
def pagar():
    tx = _transaccion(request.args.get("token_ws", ""))
    return render_template("sandbox.html", tx=tx)


@bp.post("/pagar")
@login_requerido
def resolver():
    tx = _transaccion(request.form.get("token_ws", ""))
    if tx["estado"] == "INICIADA":
        nuevo = "AUTORIZADA" if request.form.get("accion") == "aprobar" else "RECHAZADA"
        get_db().execute("UPDATE sandbox_transacciones SET estado = ? WHERE token = ?", (nuevo, tx["token"]))
    return redirect(f"{tx['url_retorno']}?token_ws={tx['token']}")
