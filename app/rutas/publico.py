"""Catálogo público, ficha del beat, previews y páginas legales."""
from flask import Blueprint, abort, jsonify, render_template, request, send_file

from ..db import get_db
from ..seguridad import GENEROS, MOODS, TONALIDADES, usuario_actual
from ..servicios.almacenamiento import obtener_almacenamiento
from ..servicios.catalogo import buscar_beats, licencias_de

bp = Blueprint("publico", __name__)


def _beat_visible(beat_id):
    beat = get_db().execute("SELECT * FROM beats WHERE id = ?", (beat_id,)).fetchone()
    usuario = usuario_actual()
    es_productor = usuario is not None and usuario["rol"] == "PRODUCTOR"
    if beat is None or (beat["estado"] != "PUBLICADO" and not es_productor):
        abort(404)
    return beat


@bp.get("/")
def catalogo():
    beats, filtros = buscar_beats(request.args)
    return render_template(
        "catalogo.html", beats=beats, filtros=filtros,
        generos=GENEROS, tonalidades=TONALIDADES, moods=MOODS,
    )


@bp.get("/beat/<int:beat_id>")
def ficha(beat_id):
    beat = _beat_visible(beat_id)
    return render_template("beat.html", beat=beat, licencias=licencias_de(beat_id))


@bp.get("/preview/<int:beat_id>")
def preview(beat_id):
    beat = _beat_visible(beat_id)
    ruta = obtener_almacenamiento().ruta(beat["archivo_preview"])
    # conditional=True permite adelantar la canción (peticiones Range)
    tipo = "audio/wav" if ruta.suffix == ".wav" else "audio/mpeg"
    respuesta = send_file(ruta, mimetype=tipo, conditional=True, max_age=3600)
    respuesta.headers["Content-Disposition"] = "inline"
    return respuesta


@bp.get("/privacidad")
def privacidad():
    return render_template("privacidad.html")


@bp.get("/terminos")
def terminos():
    return render_template("terminos.html")


@bp.get("/salud")
def salud():
    """Endpoint de salud que usa la plataforma en la nube para saber si la
    instancia está viva y reiniciarla si deja de responder."""
    try:
        get_db().execute("SELECT 1").fetchone()
        return jsonify(estado="ok"), 200
    except Exception:
        return jsonify(estado="error"), 503
