"""Carrito, pago, resultado de la orden, mis compras y descargas."""
from flask import (Blueprint, abort, flash, redirect, render_template, request, send_file, session,
                   url_for)

from ..db import get_db
from ..seguridad import entero_en_rango, limitar, login_requerido, registrar_evento, rol_requerido, usuario_actual
from ..servicios import entregas
from ..servicios.compras import ErrorCompra, crear_orden, emitir_documentos, items_carrito, procesar_retorno

bp = Blueprint("compra", __name__)
MAX_ITEMS_CARRITO = 10


@bp.get("/carrito")
def carrito():
    ids = session.get("carrito", [])
    items = items_carrito(ids)
    if len(items) != len(ids):
        # Se quitan los beats que dejaron de estar disponibles
        session["carrito"] = [item["licencia_id"] for item in items]
        flash("Quitamos de tu carrito beats que ya no están disponibles.", "aviso")
    total = sum(item["precio"] for item in items)
    return render_template("carrito.html", items=items, total=total)


@bp.post("/carrito/agregar")
def agregar():
    usuario = usuario_actual()
    if usuario and usuario["rol"] != "ARTISTA":
        abort(403)
    licencia_id = entero_en_rango(request.form.get("licencia_id"), 1, 10**9)
    item = items_carrito([licencia_id]) if licencia_id else []
    if not item:
        flash("Esa licencia no está disponible.", "error")
        return redirect(url_for("publico.catalogo"))
    item = item[0]
    actual = items_carrito(session.get("carrito", []))
    # Una sola licencia por beat: si ya había otra del mismo beat, se reemplaza
    nuevo = [i["licencia_id"] for i in actual if i["beat_id"] != item["beat_id"]]
    if len(nuevo) >= MAX_ITEMS_CARRITO:
        flash(f"El carrito admite hasta {MAX_ITEMS_CARRITO} beats.", "error")
        return redirect(url_for("compra.carrito"))
    nuevo.append(item["licencia_id"])
    session["carrito"] = nuevo
    flash(f"Agregaste «{item['titulo']}» con licencia {item['licencia_nombre']}.", "ok")
    return redirect(url_for("compra.carrito"))


@bp.post("/carrito/quitar")
def quitar():
    licencia_id = entero_en_rango(request.form.get("licencia_id"), 1, 10**9)
    session["carrito"] = [i for i in session.get("carrito", []) if i != licencia_id]
    return redirect(url_for("compra.carrito"))


@bp.post("/checkout")
@rol_requerido("ARTISTA")
@limitar(maximo=10, ventana_segundos=600)
def checkout():
    if request.form.get("acepto_licencia") != "si":
        flash("Debes aceptar las condiciones de las licencias para continuar.", "error")
        return redirect(url_for("compra.carrito"))
    try:
        _orden_id, url_pago = crear_orden(usuario_actual()["id"], session.get("carrito", []))
    except ErrorCompra as exc:
        flash(str(exc), "error")
        return redirect(url_for("compra.carrito"))
    return redirect(url_pago)


@bp.get("/pago/retorno")
@login_requerido
def retorno_pago():
    token = request.args.get("token_ws", "")
    if not token or len(token) > 100:
        abort(400)
    try:
        orden_id = procesar_retorno(token)
    except ErrorCompra:
        abort(404)
    orden = _orden_del_usuario(orden_id)
    if orden["estado"] == "PAGADA":
        session["carrito"] = []
    return redirect(url_for("compra.ver_orden", orden_id=orden["id"]))


def _orden_del_usuario(orden_id):
    """Control de acceso a nivel de objeto: solo el dueño ve su orden (evita IDOR)."""
    orden = get_db().execute(
        "SELECT * FROM ordenes WHERE id = ? AND usuario_id = ?", (orden_id, usuario_actual()["id"])
    ).fetchone()
    if orden is None:
        abort(404)
    return orden


@bp.get("/orden/<int:orden_id>")
@login_requerido
def ver_orden(orden_id):
    orden = _orden_del_usuario(orden_id)
    detalles = get_db().execute(
        "SELECT d.*, b.titulo, t.nombre AS licencia FROM detalle_orden d JOIN beats b ON b.id = d.beat_id "
        "JOIN tipos_licencia t ON t.codigo = d.tipo WHERE d.orden_id = ?", (orden_id,),
    ).fetchall()
    return render_template("orden.html", orden=orden, detalles=detalles)


@bp.get("/mis-compras")
@rol_requerido("ARTISTA")
def mis_compras():
    db = get_db()
    usuario_id = usuario_actual()["id"]
    pagadas = db.execute(
        "SELECT * FROM ordenes WHERE usuario_id = ? AND estado = 'PAGADA' ORDER BY id DESC", (usuario_id,)
    ).fetchall()
    compras = []
    for orden in pagadas:
        emitir_documentos(orden["id"])  # reintenta si algún contrato quedó pendiente
        for detalle in db.execute(
            "SELECT d.*, b.titulo, t.nombre AS licencia FROM detalle_orden d JOIN beats b ON b.id = d.beat_id "
            "JOIN tipos_licencia t ON t.codigo = d.tipo WHERE d.orden_id = ?", (orden["id"],),
        ):
            enlace = entregas.enlace_vigente(detalle["id"])
            compras.append({
                "orden": orden, "detalle": detalle, "enlace": enlace,
                "estado": entregas.estado_enlace(enlace),
                "puede_renovar": entregas.cantidad_enlaces(detalle["id"]) <= entregas.MAX_RENOVACIONES,
            })
    otras = db.execute(
        "SELECT * FROM ordenes WHERE usuario_id = ? AND estado != 'PAGADA' ORDER BY id DESC LIMIT 10", (usuario_id,)
    ).fetchall()
    return render_template("mis_compras.html", compras=compras, otras=otras)


def _entregar(detalle):
    paquete = entregas.armar_paquete(detalle)
    nombre = f"BeatStore_{detalle['tipo'].lower()}_{detalle['beat_id']}.zip"
    registrar_evento("DESCARGA", f"detalle={detalle['id']}")
    return send_file(paquete, mimetype="application/zip", as_attachment=True, download_name=nombre)


@bp.post("/mis-compras/<int:detalle_id>/descargar")
@rol_requerido("ARTISTA")
@limitar(maximo=20, ventana_segundos=600)
def descargar(detalle_id):
    try:
        detalle = entregas.descargar_desde_mis_compras(detalle_id, usuario_actual()["id"])
    except entregas.EnlaceInvalido:
        abort(404)
    except (entregas.EnlaceVencido, entregas.EnlaceAgotado):
        flash("El enlace de esta compra venció o llegó al máximo de descargas. Puedes renovarlo.", "aviso")
        return redirect(url_for("compra.mis_compras"))
    return _entregar(detalle)


@bp.post("/mis-compras/<int:detalle_id>/renovar")
@rol_requerido("ARTISTA")
def renovar(detalle_id):
    try:
        renovado = entregas.renovar_enlace(detalle_id, usuario_actual()["id"])
    except entregas.EnlaceInvalido:
        abort(404)
    if renovado:
        registrar_evento("ENLACE_RENOVADO", f"detalle={detalle_id}")
        flash("Enlace renovado: tienes 5 descargas más durante 7 días.", "ok")
    else:
        flash("No se pudo renovar el enlace (sigue vigente o alcanzaste el máximo de renovaciones).", "error")
    return redirect(url_for("compra.mis_compras"))


@bp.get("/descargar/<token>")
@login_requerido
@limitar(maximo=20, ventana_segundos=600)
def descargar_token(token):
    """Enlace enviado por correo. Exige además la sesión del comprador."""
    if len(token) > 100:
        abort(404)
    try:
        detalle = entregas.descargar_por_token(token, usuario_actual()["id"])
    except entregas.EnlaceInvalido:
        registrar_evento("DESCARGA_DENEGADA", "token inválido o ajeno")
        abort(404)
    except entregas.EnlaceVencido:
        return render_template("error.html", codigo=410, mensaje="Este enlace de descarga venció."), 410
    except entregas.EnlaceAgotado:
        return render_template("error.html", codigo=410, mensaje="Este enlace alcanzó el máximo de 5 descargas."), 410
    return _entregar(detalle)
