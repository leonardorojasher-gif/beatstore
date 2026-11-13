"""Panel del productor: beats, licencias, reportes, auditoría y correos."""
import csv
import io
import re
import tempfile
from pathlib import Path

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from ..db import get_db, transaccion
from ..seguridad import (GENEROS, MOODS, TONALIDADES, celda_csv_segura, registrar_evento,
                         rol_requerido)
from ..servicios.catalogo import PRECIOS_BASE, ErrorCatalogo, crear_beat, licencias_de, validar_datos_beat

bp = Blueprint("admin", __name__, url_prefix="/panel")


@bp.before_request
@rol_requerido("PRODUCTOR")
def solo_productor():
    """Todas las rutas del panel exigen el rol PRODUCTOR (control centralizado)."""
    return None


def _resumen():
    db = get_db()
    return {
        "total": db.execute("SELECT COALESCE(SUM(total), 0) FROM ordenes WHERE estado = 'PAGADA'").fetchone()[0],
        "ordenes": db.execute("SELECT COUNT(*) FROM ordenes WHERE estado = 'PAGADA'").fetchone()[0],
        "publicados": db.execute("SELECT COUNT(*) FROM beats WHERE estado = 'PUBLICADO'").fetchone()[0],
        "exclusivas": db.execute("SELECT COUNT(*) FROM beats WHERE estado = 'VENDIDO_EXCLUSIVO'").fetchone()[0],
        "por_licencia": db.execute(
            "SELECT t.nombre, COUNT(d.id) AS cantidad, COALESCE(SUM(d.precio), 0) AS monto "
            "FROM tipos_licencia t LEFT JOIN detalle_orden d ON d.tipo = t.codigo "
            "AND d.orden_id IN (SELECT id FROM ordenes WHERE estado = 'PAGADA') "
            "GROUP BY t.codigo ORDER BY t.orden"
        ).fetchall(),
        "por_beat": db.execute(
            "SELECT b.titulo, b.estado, COUNT(d.id) AS cantidad, COALESCE(SUM(d.precio), 0) AS monto "
            "FROM beats b LEFT JOIN detalle_orden d ON d.beat_id = b.id "
            "AND d.orden_id IN (SELECT id FROM ordenes WHERE estado = 'PAGADA') "
            "GROUP BY b.id ORDER BY monto DESC, b.titulo"
        ).fetchall(),
        "ultimas": db.execute(
            "SELECT o.*, u.nombre FROM ordenes o JOIN usuarios u ON u.id = o.usuario_id ORDER BY o.id DESC LIMIT 8"
        ).fetchall(),
    }


@bp.get("/")
def panel():
    return render_template("admin/panel.html", r=_resumen())


@bp.get("/ventas.csv")
def exportar_ventas():
    filas = get_db().execute(
        "SELECT o.id, o.pagada_en, u.nombre, u.email, b.titulo, t.nombre AS licencia, d.precio "
        "FROM detalle_orden d JOIN ordenes o ON o.id = d.orden_id JOIN usuarios u ON u.id = o.usuario_id "
        "JOIN beats b ON b.id = d.beat_id JOIN tipos_licencia t ON t.codigo = d.tipo "
        "WHERE o.estado = 'PAGADA' ORDER BY o.id"
    ).fetchall()
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(["Orden", "Fecha de pago", "Artista", "Correo", "Beat", "Licencia", "Precio CLP"])
    for f in filas:
        escritor.writerow([celda_csv_segura(v) for v in (f["id"], f["pagada_en"], f["nombre"], f["email"],
                                                         f["titulo"], f["licencia"], f["precio"])])
    registrar_evento("EXPORTAR_VENTAS", f"filas={len(filas)}")
    return Response(
        "﻿" + salida.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ventas-beatstore.csv"},
    )


@bp.get("/beats")
def beats():
    lista = get_db().execute("SELECT * FROM beats ORDER BY id DESC").fetchall()
    return render_template("admin/beats.html", beats=lista)


@bp.route("/beats/nuevo", methods=["GET", "POST"])
def nuevo_beat():
    errores, datos = [], {}
    if request.method == "POST":
        datos, precios, errores = validar_datos_beat(request.form)
        master = request.files.get("master")
        stems = request.files.get("stems")
        if not master or not master.filename:
            errores.append("Debes subir el master en formato WAV.")
        elif not master.filename.lower().endswith(".wav"):
            errores.append("El master debe tener extensión .wav.")
        if stems and stems.filename and not stems.filename.lower().endswith(".zip"):
            errores.append("Los stems deben venir en un archivo .zip.")
        if not errores:
            with tempfile.TemporaryDirectory() as tmp:
                ruta_master = Path(tmp) / "master.wav"
                master.save(ruta_master)
                ruta_stems = None
                if stems and stems.filename:
                    ruta_stems = Path(tmp) / "stems.zip"
                    stems.save(ruta_stems)
                try:
                    beat_id = crear_beat(datos, precios, ruta_master, ruta_stems)
                except ErrorCatalogo as exc:
                    errores.append(str(exc))
                else:
                    registrar_evento("BEAT_CREADO", f"beat={beat_id}")
                    flash("Beat publicado. El preview con tag se generó automáticamente.", "ok")
                    return redirect(url_for("admin.beats"))
    return render_template(
        "admin/beat_form.html", errores=errores, datos=datos, precios_base=PRECIOS_BASE,
        generos=GENEROS, tonalidades=TONALIDADES, moods=MOODS,
    )


@bp.route("/beats/<int:beat_id>", methods=["GET", "POST"])
def editar_beat(beat_id):
    db = get_db()
    beat = db.execute("SELECT * FROM beats WHERE id = ?", (beat_id,)).fetchone()
    if beat is None:
        abort(404)
    errores = []
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion in ("publicar", "ocultar"):
            if beat["estado"] == "VENDIDO_EXCLUSIVO":
                errores.append("Un beat vendido en exclusiva no se puede volver a publicar.")
            else:
                nuevo = "PUBLICADO" if accion == "publicar" else "OCULTO"
                db.execute("UPDATE beats SET estado = ? WHERE id = ? AND estado != 'VENDIDO_EXCLUSIVO'", (nuevo, beat_id))
                registrar_evento("BEAT_ESTADO", f"beat={beat_id} estado={nuevo}")
                flash(f"Beat {'publicado' if nuevo == 'PUBLICADO' else 'oculto'}.", "ok")
                return redirect(url_for("admin.editar_beat", beat_id=beat_id))
        elif accion == "guardar":
            datos, precios, errores = validar_datos_beat(request.form)
            if not errores:
                with transaccion(db):
                    db.execute(
                        "UPDATE beats SET titulo = ?, genero = ?, bpm = ?, tonalidad = ?, mood = ? WHERE id = ?",
                        (datos["titulo"], datos["genero"], datos["bpm"], datos["tonalidad"], datos["mood"], beat_id),
                    )
                    for codigo, precio in precios.items():
                        activa = 1 if request.form.get(f"activa_{codigo}") == "si" else 0
                        if codigo in ("STEMS", "EXCLUSIVA") and not beat["archivo_stems"]:
                            activa = 0
                        db.execute("UPDATE licencias_beat SET precio = ?, activa = ? WHERE beat_id = ? AND tipo = ?",
                                   (precio, activa, beat_id, codigo))
                registrar_evento("BEAT_EDITADO", f"beat={beat_id}")
                flash("Cambios guardados.", "ok")
                return redirect(url_for("admin.editar_beat", beat_id=beat_id))
        else:
            abort(400)
    return render_template(
        "admin/beat_editar.html", beat=beat, licencias=licencias_de(beat_id, solo_activas=False),
        errores=errores, generos=GENEROS, tonalidades=TONALIDADES, moods=MOODS,
    )


@bp.get("/auditoria")
def auditoria():
    eventos = get_db().execute(
        "SELECT a.*, u.email FROM auditoria a LEFT JOIN usuarios u ON u.id = a.usuario_id ORDER BY a.id DESC LIMIT 150"
    ).fetchall()
    return render_template("admin/auditoria.html", eventos=eventos)


@bp.get("/correos")
def correos():
    lista = []
    for correo in get_db().execute("SELECT * FROM correos ORDER BY id DESC LIMIT 30"):
        correo = dict(correo)
        # El productor ve que el correo salió, pero no los enlaces privados del artista
        correo["cuerpo"] = re.sub(r"/descargar/[\w-]+", "/descargar/[enlace privado]", correo["cuerpo"])
        lista.append(correo)
    return render_template("admin/correos.html", correos=lista)
