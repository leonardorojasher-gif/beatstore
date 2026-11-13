import struct
import wave
from pathlib import Path

import pytest

from app import create_app
from app.config import TestingConfig
from app.db import ahora, get_db
from app.demo import crear_usuario
from app.seguridad import limitador
from app.servicios.almacenamiento import obtener_almacenamiento

CSRF = "token-de-prueba"
CLAVE = "ClaveSegura2026"


def _wav(ruta: Path, segundos=2):
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * 8000 * segundos)


@pytest.fixture()
def app(tmp_path):
    class Config(TestingConfig):
        DATA_DIR = tmp_path
        DATABASE_PATH = tmp_path / "test.db"
        STORAGE_DIR = tmp_path / "almacenamiento"

    aplicacion = create_app(Config)
    limitador.limpiar()
    with aplicacion.app_context():
        crear_usuario("Productor", "productor@beatstore.cl", CLAVE, "PRODUCTOR")
        crear_usuario("Ana", "ana@demo.cl", CLAVE, "ARTISTA")
        crear_usuario("Beto", "beto@demo.cl", CLAVE, "ARTISTA")
    yield aplicacion


@pytest.fixture()
def client(app):
    return app.test_client()


def crear_beat_prueba(app, titulo="Beat de prueba", genero="Trap", bpm=140, con_stems=True):
    """Inserta un beat sin pasar por FFmpeg (para pruebas rápidas)."""
    with app.app_context():
        almacenamiento = obtener_almacenamiento()
        tmp = Path(app.config["DATA_DIR"]) / "tmp.wav"
        _wav(tmp)
        master = almacenamiento.guardar_archivo(tmp, "masters", "wav")
        mp3 = almacenamiento.guardar_bytes(b"ID3 mp3 de prueba", "mp3", "mp3")
        preview = almacenamiento.guardar_bytes(b"ID3 preview", "previews", "mp3")
        stems = almacenamiento.guardar_bytes(b"PK zip", "stems", "zip") if con_stems else None
        db = get_db()
        beat_id = db.execute(
            "INSERT INTO beats (titulo, genero, bpm, tonalidad, mood, archivo_master, archivo_mp3, archivo_stems, "
            "archivo_preview, creado_en) VALUES (?, ?, ?, 'La menor', 'Oscuro', ?, ?, ?, ?, ?)",
            (titulo, genero, bpm, master, mp3, stems, preview, ahora()),
        ).lastrowid
        for tipo, precio in (("BASICA", 15000), ("PREMIUM", 30000), ("STEMS", 60000), ("EXCLUSIVA", 250000)):
            db.execute("INSERT INTO licencias_beat (beat_id, tipo, precio) VALUES (?, ?, ?)", (beat_id, tipo, precio))
        licencias = {
            fila["tipo"]: fila["id"]
            for fila in db.execute("SELECT id, tipo FROM licencias_beat WHERE beat_id = ?", (beat_id,))
        }
    return beat_id, licencias


def post(client, url, data=None, **kwargs):
    with client.session_transaction() as sesion:
        sesion["_csrf"] = CSRF
    datos = {"_csrf": CSRF, **(data or {})}
    return client.post(url, data=datos, **kwargs)


def login(client, email, password=CLAVE):
    return post(client, "/login", {"email": email, "password": password})


def comprar(client, licencia_id, accion="aprobar"):
    """Recorre el flujo completo: carrito -> checkout -> pasarela -> retorno."""
    post(client, "/carrito/agregar", {"licencia_id": licencia_id})
    respuesta = post(client, "/checkout", {"acepto_licencia": "si"})
    assert respuesta.status_code == 302, respuesta.data
    url_pasarela = respuesta.headers["Location"]
    token = url_pasarela.split("token_ws=")[1]
    retorno = post(client, "/sandbox-webpay/pagar", {"token_ws": token, "accion": accion})
    final = client.get(retorno.headers["Location"], follow_redirects=True)
    return token, final
