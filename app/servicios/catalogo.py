"""Gestión del catálogo: búsqueda con filtros y publicación de beats."""
import tempfile
import zipfile
from pathlib import Path

from ..db import ahora, get_db, transaccion
from ..seguridad import GENEROS, MOODS, TONALIDADES, entero_en_rango, texto_limpio
from . import audio
from .almacenamiento import obtener_almacenamiento

PRECIOS_BASE = {"BASICA": 15000, "PREMIUM": 30000, "STEMS": 60000, "EXCLUSIVA": 250000}


class ErrorCatalogo(Exception):
    pass


def buscar_beats(args):
    """Arma la consulta solo con filtros de una lista blanca y parámetros (?)."""
    condiciones = ["b.estado = 'PUBLICADO'"]
    parametros = []
    filtros = {}

    genero = args.get("genero", "")
    if genero in GENEROS:
        condiciones.append("b.genero = ?")
        parametros.append(genero)
        filtros["genero"] = genero
    tonalidad = args.get("tonalidad", "")
    if tonalidad in TONALIDADES:
        condiciones.append("b.tonalidad = ?")
        parametros.append(tonalidad)
        filtros["tonalidad"] = tonalidad
    mood = args.get("mood", "")
    if mood in MOODS:
        condiciones.append("b.mood = ?")
        parametros.append(mood)
        filtros["mood"] = mood
    bpm_min = entero_en_rango(args.get("bpm_min"), 40, 250)
    if bpm_min is not None:
        condiciones.append("b.bpm >= ?")
        parametros.append(bpm_min)
        filtros["bpm_min"] = bpm_min
    bpm_max = entero_en_rango(args.get("bpm_max"), 40, 250)
    if bpm_max is not None:
        condiciones.append("b.bpm <= ?")
        parametros.append(bpm_max)
        filtros["bpm_max"] = bpm_max
    texto = texto_limpio(args.get("q"), 60)
    if texto:
        condiciones.append("b.titulo LIKE ? ESCAPE '\\'")
        escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        parametros.append(f"%{escapado}%")
        filtros["q"] = texto
    precio_max = entero_en_rango(args.get("precio_max"), 1000, 10_000_000)
    having = ""
    if precio_max is not None:
        having = "HAVING desde <= ?"
        filtros["precio_max"] = precio_max

    sql = (
        "SELECT b.*, MIN(lb.precio) AS desde FROM beats b "
        "JOIN licencias_beat lb ON lb.beat_id = b.id AND lb.activa = 1 "
        f"WHERE {' AND '.join(condiciones)} GROUP BY b.id {having} ORDER BY b.creado_en DESC, b.id DESC"
    )
    if precio_max is not None:
        parametros.append(precio_max)
    return get_db().execute(sql, parametros).fetchall(), filtros


def licencias_de(beat_id, solo_activas=True):
    sql = (
        "SELECT lb.*, t.nombre, t.archivos, t.limite_reproducciones, t.monetizacion, t.es_exclusiva "
        "FROM licencias_beat lb JOIN tipos_licencia t ON t.codigo = lb.tipo WHERE lb.beat_id = ? "
    )
    if solo_activas:
        sql += "AND lb.activa = 1 "
    return get_db().execute(sql + "ORDER BY t.orden", (beat_id,)).fetchall()


def validar_datos_beat(formulario):
    errores = []
    titulo = texto_limpio(formulario.get("titulo"), 80)
    if len(titulo) < 2:
        errores.append("El título debe tener al menos 2 caracteres.")
    genero = formulario.get("genero", "")
    if genero not in GENEROS:
        errores.append("Selecciona un género válido.")
    tonalidad = formulario.get("tonalidad", "")
    if tonalidad not in TONALIDADES:
        errores.append("Selecciona una tonalidad válida.")
    mood = formulario.get("mood", "")
    if mood not in MOODS:
        errores.append("Selecciona un mood válido.")
    bpm = entero_en_rango(formulario.get("bpm"), 40, 250)
    if bpm is None:
        errores.append("El BPM debe ser un número entre 40 y 250.")
    precios = {}
    for codigo in PRECIOS_BASE:
        precio = entero_en_rango(formulario.get(f"precio_{codigo}"), 1000, 10_000_000)
        if precio is None:
            errores.append(f"El precio de la licencia {codigo.lower()} debe estar entre $1.000 y $10.000.000.")
        precios[codigo] = precio
    datos = {"titulo": titulo, "genero": genero, "tonalidad": tonalidad, "mood": mood, "bpm": bpm}
    return datos, precios, errores


def _validar_stems(ruta):
    if not zipfile.is_zipfile(ruta):
        raise ErrorCatalogo("Los stems deben venir en un archivo ZIP.")
    with zipfile.ZipFile(ruta) as zz:
        nombres = zz.namelist()
        if not nombres or len(nombres) > 50:
            raise ErrorCatalogo("El ZIP de stems debe tener entre 1 y 50 archivos.")
        for nombre in nombres:
            if nombre.startswith("/") or ".." in Path(nombre).parts:
                raise ErrorCatalogo("El ZIP de stems contiene rutas no permitidas.")


def crear_beat(datos, precios, ruta_master, ruta_stems=None):
    """Valida el audio, genera MP3 y preview con tag y registra el beat."""
    try:
        audio.validar_master(ruta_master)
    except audio.ErrorAudio as exc:
        raise ErrorCatalogo(str(exc)) from exc
    if ruta_stems:
        _validar_stems(ruta_stems)

    almacenamiento = obtener_almacenamiento()
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "beat.mp3"
        preview = Path(tmp) / "preview.mp3"
        try:
            audio.generar_mp3(ruta_master, mp3)
            audio.generar_preview_con_tag(ruta_master, preview)
        except audio.ErrorAudio as exc:
            raise ErrorCatalogo(str(exc)) from exc
        claves = {
            "master": almacenamiento.guardar_archivo(ruta_master, "masters", "wav"),
            "mp3": almacenamiento.guardar_archivo(mp3, "mp3", "mp3"),
            "preview": almacenamiento.guardar_archivo(preview, "previews", "mp3"),
            "stems": almacenamiento.guardar_archivo(ruta_stems, "stems", "zip") if ruta_stems else None,
        }

    db = get_db()
    with transaccion(db):
        beat_id = db.execute(
            "INSERT INTO beats (titulo, genero, bpm, tonalidad, mood, archivo_master, archivo_mp3, "
            "archivo_stems, archivo_preview, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datos["titulo"], datos["genero"], datos["bpm"], datos["tonalidad"], datos["mood"],
             claves["master"], claves["mp3"], claves["stems"], claves["preview"], ahora()),
        ).lastrowid
        for codigo, precio in precios.items():
            # Sin stems no se ofrecen las licencias que los incluyen
            activa = 0 if (codigo in ("STEMS", "EXCLUSIVA") and not ruta_stems) else 1
            db.execute(
                "INSERT INTO licencias_beat (beat_id, tipo, precio, activa) VALUES (?, ?, ?, ?)",
                (beat_id, codigo, precio, activa),
            )
    return beat_id
