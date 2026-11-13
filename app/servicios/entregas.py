"""Entrega de archivos con enlaces seguros (RF08, RF09 y RNF02 de la EV2).

- El token del enlace es aleatorio (256 bits) y en la base solo se guarda su hash.
- Cada enlace vence a los 7 días o tras 5 descargas, lo que ocurra primero.
- Para descargar hay que haber iniciado sesión como el comprador (defensa en
  profundidad: aunque el enlace se filtre, otra persona no puede usarlo).
"""
import io
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from ..db import ahora, get_db
from ..seguridad import hash_token
from .almacenamiento import obtener_almacenamiento

MAX_RENOVACIONES = 3


class EnlaceInvalido(Exception):
    """El enlace no existe o no pertenece al usuario (no se distingue el motivo)."""


class EnlaceVencido(Exception):
    pass


class EnlaceAgotado(Exception):
    pass


def crear_enlace(detalle_id):
    token = secrets.token_urlsafe(32)
    vence = datetime.now(timezone.utc) + timedelta(days=current_app.config["DESCARGA_DIAS_VIGENCIA"])
    get_db().execute(
        "INSERT INTO enlaces_descarga (detalle_id, token_hash, expira_en, max_descargas, creado_en) "
        "VALUES (?, ?, ?, ?, ?)",
        (detalle_id, hash_token(token), vence.replace(microsecond=0).isoformat(),
         current_app.config["DESCARGA_MAX"], ahora()),
    )
    return token


def enlace_vigente(detalle_id):
    return get_db().execute(
        "SELECT * FROM enlaces_descarga WHERE detalle_id = ? ORDER BY id DESC LIMIT 1", (detalle_id,)
    ).fetchone()


def estado_enlace(enlace):
    if enlace is None:
        return "SIN_ENLACE"
    if enlace["expira_en"] < ahora():
        return "VENCIDO"
    if enlace["descargas"] >= enlace["max_descargas"]:
        return "AGOTADO"
    return "VIGENTE"


def cantidad_enlaces(detalle_id):
    return get_db().execute(
        "SELECT COUNT(*) FROM enlaces_descarga WHERE detalle_id = ?", (detalle_id,)
    ).fetchone()[0]


def _detalle_del_usuario(detalle_id, usuario_id):
    detalle = get_db().execute(
        "SELECT d.*, o.usuario_id, o.estado AS estado_orden, b.titulo, b.archivo_master, b.archivo_mp3, "
        "b.archivo_stems FROM detalle_orden d JOIN ordenes o ON o.id = d.orden_id "
        "JOIN beats b ON b.id = d.beat_id WHERE d.id = ?", (detalle_id,),
    ).fetchone()
    if detalle is None or detalle["usuario_id"] != usuario_id or detalle["estado_orden"] != "PAGADA":
        raise EnlaceInvalido()
    return detalle


def _consumir(enlace):
    """Suma una descarga de forma atómica (no se puede superar el máximo)."""
    estado = estado_enlace(enlace)
    if estado == "VENCIDO":
        raise EnlaceVencido()
    if estado == "AGOTADO":
        raise EnlaceAgotado()
    cambio = get_db().execute(
        "UPDATE enlaces_descarga SET descargas = descargas + 1 WHERE id = ? AND descargas < max_descargas",
        (enlace["id"],),
    )
    if cambio.rowcount != 1:
        raise EnlaceAgotado()


def descargar_por_token(token, usuario_id):
    enlace = get_db().execute(
        "SELECT * FROM enlaces_descarga WHERE token_hash = ?", (hash_token(token),)
    ).fetchone()
    if enlace is None:
        raise EnlaceInvalido()
    detalle = _detalle_del_usuario(enlace["detalle_id"], usuario_id)
    _consumir(enlace)
    return detalle


def descargar_desde_mis_compras(detalle_id, usuario_id):
    detalle = _detalle_del_usuario(detalle_id, usuario_id)
    enlace = enlace_vigente(detalle_id)
    if enlace is None:
        raise EnlaceVencido()
    _consumir(enlace)
    return detalle


def renovar_enlace(detalle_id, usuario_id):
    _detalle_del_usuario(detalle_id, usuario_id)
    if estado_enlace(enlace_vigente(detalle_id)) == "VIGENTE":
        return False
    if cantidad_enlaces(detalle_id) > MAX_RENOVACIONES:
        return False
    crear_enlace(detalle_id)
    return True


def armar_paquete(detalle):
    """Arma un ZIP con los archivos que corresponden a la licencia y el contrato."""
    almacenamiento = obtener_almacenamiento()
    archivos = {
        "BASICA": [("mp3", "beat.mp3")],
        "PREMIUM": [("master", "beat.wav")],
        "STEMS": [("master", "beat.wav"), ("stems", "stems.zip")],
        "EXCLUSIVA": [("master", "beat.wav"), ("mp3", "beat.mp3"), ("stems", "stems.zip")],
    }[detalle["tipo"]]
    claves = {"master": detalle["archivo_master"], "mp3": detalle["archivo_mp3"], "stems": detalle["archivo_stems"]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as paquete:
        agregados = set()
        for tipo, nombre in archivos:
            clave = claves[tipo]
            if clave and clave not in agregados:
                agregados.add(clave)
                # La extensión se toma del archivo real guardado
                paquete.write(almacenamiento.ruta(clave), Path(nombre).stem + Path(clave).suffix)
        if detalle["contrato_archivo"]:
            paquete.write(almacenamiento.ruta(detalle["contrato_archivo"]), f"contrato_{detalle['contrato_codigo']}.pdf")
        paquete.writestr("LEEME.txt", (
            f"Beat: {detalle['titulo']}\nLicencia: {detalle['tipo']}\n"
            f"Contrato: {detalle['contrato_codigo']}\nHuella SHA-256 del contrato: {detalle['contrato_sha256']}\n"
            "Gracias por comprar en BeatStore.\n"
        ))
    buffer.seek(0)
    return buffer
