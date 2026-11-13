"""Pruebas del catálogo, filtros, previews y carga de beats."""
import io
import shutil
import struct
import wave
import zipfile

import pytest

from .conftest import crear_beat_prueba, login, post


def test_catalogo_filtra_por_genero_y_bpm(app, client):
    crear_beat_prueba(app, titulo="Trap Rapido", genero="Trap", bpm=150)
    crear_beat_prueba(app, titulo="Perreo Lento", genero="Reggaetón", bpm=92)
    r = client.get("/?genero=Trap&bpm_min=140&bpm_max=160")
    assert b"Trap Rapido" in r.data and b"Perreo Lento" not in r.data


def test_catalogo_sin_resultados(app, client):
    crear_beat_prueba(app)
    r = client.get("/?genero=Drill")
    assert "No hay beats con esos filtros".encode() in r.data


def test_preview_se_reproduce_en_linea(app, client):
    beat_id, _ = crear_beat_prueba(app)
    r = client.get(f"/preview/{beat_id}")
    assert r.status_code == 200 and r.mimetype == "audio/mpeg"
    assert r.headers["Content-Disposition"] == "inline"


def test_una_licencia_por_beat_en_el_carrito(app, client):
    _, licencias = crear_beat_prueba(app)
    post(client, "/carrito/agregar", {"licencia_id": licencias["BASICA"]})
    post(client, "/carrito/agregar", {"licencia_id": licencias["PREMIUM"]})
    with client.session_transaction() as sesion:
        assert sesion["carrito"] == [licencias["PREMIUM"]]


def test_checkout_exige_sesion(app, client):
    _, licencias = crear_beat_prueba(app)
    post(client, "/carrito/agregar", {"licencia_id": licencias["BASICA"]})
    r = post(client, "/checkout", {"acepto_licencia": "si"})
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_salud(client):
    r = client.get("/salud")
    assert r.status_code == 200 and r.json["estado"] == "ok"


def _wav_bytes(segundos=3):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(struct.pack("<h", 1000) * 22050 * segundos)
    return buffer.getvalue()


def test_subida_rechaza_archivo_que_no_es_wav(client):
    login(client, "productor@beatstore.cl")
    datos = {"titulo": "Falso", "genero": "Trap", "bpm": "140", "tonalidad": "La menor", "mood": "Oscuro",
             "precio_BASICA": "15000", "precio_PREMIUM": "30000", "precio_STEMS": "60000", "precio_EXCLUSIVA": "250000",
             "master": (io.BytesIO(b"MZ esto es un ejecutable"), "beat.wav")}
    r = post(client, "/panel/beats/nuevo", datos, content_type="multipart/form-data")
    assert "debe ser un archivo WAV".encode() in r.data


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requiere FFmpeg")
def test_subida_de_beat_genera_preview(client):
    login(client, "productor@beatstore.cl")
    stems = io.BytesIO()
    with zipfile.ZipFile(stems, "w") as zz:
        zz.writestr("drums.wav", _wav_bytes(1))
    stems.seek(0)
    datos = {"titulo": "Subido", "genero": "Drill", "bpm": "142", "tonalidad": "Fa# menor", "mood": "Agresivo",
             "precio_BASICA": "15000", "precio_PREMIUM": "30000", "precio_STEMS": "60000", "precio_EXCLUSIVA": "250000",
             "master": (io.BytesIO(_wav_bytes()), "beat.wav"), "stems": (stems, "stems.zip")}
    r = post(client, "/panel/beats/nuevo", datos, content_type="multipart/form-data")
    assert r.status_code == 302
    assert b"Subido" in client.get("/").data
