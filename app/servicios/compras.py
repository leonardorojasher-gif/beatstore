"""Proceso crítico de compra: orden -> pago -> licencia exclusiva -> contrato.

Es la parte del sistema donde un error cuesta dinero o confianza, por eso:
- Los precios siempre se leen de la base de datos (nunca del navegador).
- El monto confirmado por la pasarela se compara con el total de la orden.
- La venta de una exclusiva se hace dentro de una transacción con bloqueo,
  para que dos artistas no compren el mismo beat exclusivo a la vez.
- Si algo falla después de cobrar, el pago se anula (no se cobra sin entregar).
"""
from flask import current_app, url_for

from ..db import ahora, get_db, transaccion
from ..seguridad import registrar_evento
from ..utilidades import clp
from .almacenamiento import obtener_almacenamiento
from .entregas import crear_enlace
from .licencias import generar_contrato
from .notificaciones import enviar_seguro
from .pagos import obtener_pasarela


class ErrorCompra(Exception):
    pass


class ExclusivaNoDisponible(Exception):
    pass


CONSULTA_ITEMS = """
    SELECT lb.id AS licencia_id, lb.precio, lb.tipo, lb.activa,
           b.id AS beat_id, b.titulo, b.genero, b.bpm, b.tonalidad, b.estado,
           t.nombre AS licencia_nombre, t.es_exclusiva
    FROM licencias_beat lb
    JOIN beats b ON b.id = lb.beat_id
    JOIN tipos_licencia t ON t.codigo = lb.tipo
    WHERE lb.id = ?
"""


def items_carrito(ids):
    """Devuelve los ítems válidos del carrito con precios oficiales."""
    db = get_db()
    items = []
    for licencia_id in ids:
        fila = db.execute(CONSULTA_ITEMS, (licencia_id,)).fetchone()
        if fila and fila["activa"] and fila["estado"] == "PUBLICADO":
            items.append(fila)
    return items


def crear_orden(usuario_id, ids):
    items = items_carrito(ids)
    if not items or len(items) != len(ids):
        raise ErrorCompra("Uno o más beats del carrito ya no están disponibles. Revisa tu carrito.")
    total = sum(item["precio"] for item in items)
    db = get_db()
    with transaccion(db):
        orden_id = db.execute(
            "INSERT INTO ordenes (usuario_id, estado, total, creada_en) VALUES (?, 'PENDIENTE', ?, ?)",
            (usuario_id, total, ahora()),
        ).lastrowid
        for item in items:
            db.execute(
                "INSERT INTO detalle_orden (orden_id, licencia_beat_id, beat_id, tipo, precio) "
                "VALUES (?, ?, ?, ?, ?)",
                (orden_id, item["licencia_id"], item["beat_id"], item["tipo"], item["precio"]),
            )
    url_retorno = url_for("compra.retorno_pago")
    token, url_pago = obtener_pasarela().iniciar_transaccion(orden_id, total, url_retorno)
    db.execute("UPDATE ordenes SET token_pasarela = ? WHERE id = ?", (token, orden_id))
    registrar_evento("ORDEN_CREADA", f"orden={orden_id} total={total}")
    return orden_id, url_pago


def _cerrar_orden(orden_id, estado, motivo):
    get_db().execute("UPDATE ordenes SET estado = ?, motivo = ? WHERE id = ?", (estado, motivo, orden_id))


def procesar_retorno(token):
    """Confirma el pago con la pasarela y cierra la orden. Es idempotente:
    si el usuario recarga la página, la orden no se procesa dos veces."""
    db = get_db()
    orden = db.execute("SELECT * FROM ordenes WHERE token_pasarela = ?", (token,)).fetchone()
    if orden is None:
        raise ErrorCompra("No encontramos la orden asociada a este pago.")
    if orden["estado"] != "PENDIENTE":
        return orden["id"]

    pasarela = obtener_pasarela()
    resultado = pasarela.confirmar_transaccion(token)
    if not resultado.aprobado:
        _cerrar_orden(orden["id"], "RECHAZADA", resultado.mensaje)
        registrar_evento("PAGO_RECHAZADO", f"orden={orden['id']}")
        return orden["id"]

    # Control de integridad: el monto cobrado debe ser exactamente el de la orden
    if resultado.orden_id != orden["id"] or resultado.monto != orden["total"]:
        pasarela.anular(token)
        _cerrar_orden(orden["id"], "ANULADA", "El monto informado por la pasarela no coincide con la orden.")
        registrar_evento("PAGO_INCONSISTENTE", f"orden={orden['id']} monto={resultado.monto}")
        return orden["id"]

    try:
        with transaccion(db):
            actual = db.execute("SELECT estado FROM ordenes WHERE id = ?", (orden["id"],)).fetchone()
            if actual["estado"] != "PENDIENTE":
                return orden["id"]
            detalles = db.execute(
                "SELECT d.*, t.es_exclusiva FROM detalle_orden d "
                "JOIN tipos_licencia t ON t.codigo = d.tipo WHERE d.orden_id = ?",
                (orden["id"],),
            ).fetchall()
            for detalle in detalles:
                estado_beat = db.execute("SELECT estado FROM beats WHERE id = ?", (detalle["beat_id"],)).fetchone()
                if estado_beat["estado"] != "PUBLICADO":
                    raise ExclusivaNoDisponible()
            for detalle in detalles:
                if detalle["es_exclusiva"]:
                    cambio = db.execute(
                        "UPDATE beats SET estado = 'VENDIDO_EXCLUSIVO' WHERE id = ? AND estado = 'PUBLICADO'",
                        (detalle["beat_id"],),
                    )
                    if cambio.rowcount != 1:
                        raise ExclusivaNoDisponible()
            db.execute(
                "UPDATE ordenes SET estado = 'PAGADA', pagada_en = ?, codigo_autorizacion = ? WHERE id = ?",
                (ahora(), resultado.codigo_autorizacion, orden["id"]),
            )
    except ExclusivaNoDisponible:
        pasarela.anular(token)
        _cerrar_orden(orden["id"], "ANULADA",
                      "Uno de los beats se vendió en exclusiva mientras pagabas. El pago fue anulado.")
        registrar_evento("PAGO_ANULADO_EXCLUSIVA", f"orden={orden['id']}")
        return orden["id"]

    registrar_evento("PAGO_APROBADO", f"orden={orden['id']} total={orden['total']}")
    tokens = emitir_documentos(orden["id"])
    _notificar_venta(orden["id"], tokens)
    return orden["id"]


def emitir_documentos(orden_id):
    """Genera contratos y enlaces de descarga que falten. Se puede volver a
    ejecutar sin duplicar nada (si falló, se reintenta al abrir Mis compras)."""
    db = get_db()
    almacenamiento = obtener_almacenamiento()
    orden = db.execute(
        "SELECT o.id, o.estado, u.nombre, u.email FROM ordenes o JOIN usuarios u ON u.id = o.usuario_id "
        "WHERE o.id = ?", (orden_id,),
    ).fetchone()
    if orden is None or orden["estado"] != "PAGADA":
        return {}
    tokens = {}
    detalles = db.execute(
        "SELECT d.*, b.titulo, b.genero, b.bpm, b.tonalidad, t.nombre, t.archivos, "
        "t.limite_reproducciones, t.monetizacion FROM detalle_orden d "
        "JOIN beats b ON b.id = d.beat_id JOIN tipos_licencia t ON t.codigo = d.tipo "
        "WHERE d.orden_id = ?", (orden_id,),
    ).fetchall()
    for detalle in detalles:
        try:
            if not detalle["contrato_archivo"]:
                pdf, codigo, huella = generar_contrato(
                    current_app.config["NOMBRE_PRODUCTOR"], orden, detalle, detalle,
                    detalle["precio"], orden_id,
                )
                clave = almacenamiento.guardar_bytes(pdf, "contratos", "pdf")
                db.execute(
                    "UPDATE detalle_orden SET contrato_archivo = ?, contrato_codigo = ?, contrato_sha256 = ? "
                    "WHERE id = ?", (clave, codigo, huella, detalle["id"]),
                )
            existe = db.execute("SELECT 1 FROM enlaces_descarga WHERE detalle_id = ?", (detalle["id"],)).fetchone()
            if not existe:
                tokens[detalle["id"]] = crear_enlace(detalle["id"])
        except Exception:
            current_app.logger.exception("No se pudieron emitir los documentos del detalle %s", detalle["id"])
    return tokens


def _notificar_venta(orden_id, tokens):
    db = get_db()
    orden = db.execute(
        "SELECT o.*, u.nombre, u.email FROM ordenes o JOIN usuarios u ON u.id = o.usuario_id WHERE o.id = ?",
        (orden_id,),
    ).fetchone()
    lineas, lineas_productor = [], []
    for detalle in db.execute(
        "SELECT d.id, d.precio, b.titulo, t.nombre FROM detalle_orden d JOIN beats b ON b.id = d.beat_id "
        "JOIN tipos_licencia t ON t.codigo = d.tipo WHERE d.orden_id = ?", (orden_id,),
    ):
        linea = f" - {detalle['titulo']} (licencia {detalle['nombre']}): {clp(detalle['precio'])}"
        lineas_productor.append(linea)  # el productor no recibe los enlaces del artista
        if detalle["id"] in tokens:
            linea += "\n   Descarga: " + url_for("compra.descargar_token", token=tokens[detalle["id"]], _external=True)
        lineas.append(linea)
    detalle_txt = "\n".join(lineas)
    detalle_productor = "\n".join(lineas_productor)
    enviar_seguro(
        orden["email"], f"Comprobante de tu compra N.° {orden_id} en BeatStore",
        f"Hola {orden['nombre']}:\n\nTu pago fue aprobado (código de autorización "
        f"{orden['codigo_autorizacion']}).\n\n{detalle_txt}\n\nTotal pagado: {clp(orden['total'])}\n\n"
        "Cada enlace vence en 7 días o tras 5 descargas. También puedes descargar desde 'Mis compras'.",
    )
    enviar_seguro(
        current_app.config["CORREO_PRODUCTOR"], f"Nueva venta N.° {orden_id}",
        f"{orden['nombre']} compró:\n{detalle_productor}\n\nTotal: {clp(orden['total'])}",
    )
