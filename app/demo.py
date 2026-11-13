"""Datos de demostración: cuentas de prueba y beats sintetizados con FFmpeg.

Solo para desarrollo y para la presentación del prototipo.
"""
import subprocess
import tempfile
import zipfile
from pathlib import Path

from flask import current_app
from werkzeug.security import generate_password_hash

from .db import ahora, get_db
from .seguridad import validar_email, validar_password
from .servicios import audio
from .servicios.catalogo import crear_beat

CUENTAS_DEMO = [
    ("Matías Herrera", None, "MHbeats2026", "PRODUCTOR"),
    ("Valentina Soto", "valentina@demo.cl", "BeatsDemo2026", "ARTISTA"),
    ("Benjamín Rojas", "benjamin@demo.cl", "BeatsDemo2026", "ARTISTA"),
]

# titulo, genero, bpm, tonalidad, mood, frecuencia base (Hz), precio exclusiva
BEATS_DEMO = [
    ("Noche en La Florida", "Trap", 140, "La menor", "Oscuro", 220.00, 250000),
    ("Perreo Lunar", "Reggaetón", 95, "Do# menor", "Bailable", 277.18, 280000),
    ("Calle Fría", "Drill", 142, "Fa# menor", "Agresivo", 185.00, 260000),
    ("Luz de Neón", "R&B", 76, "Re menor", "Melódico", 146.83, 250000),
    ("Barrio Viejo", "Boom bap", 90, "Mi menor", "Chill", 164.81, 240000),
    ("Lágrimas de Oro", "Trap", 130, "Sol menor", "Triste", 196.00, 300000),
]


def crear_usuario(nombre, email, password, rol):
    if not validar_email(email):
        raise ValueError("Correo no válido")
    errores = validar_password(password, email)
    if errores:
        raise ValueError(" ".join(errores))
    get_db().execute(
        "INSERT INTO usuarios (nombre, email, password_hash, rol, acepta_terminos_en, creado_en) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (nombre, email.lower(), generate_password_hash(password, method="scrypt"), rol, ahora(), ahora()),
    )


def _sintetizar(destino_drums, destino_melodia, destino_master, bpm, f0, segundos=20):
    p = 60 / bpm
    drums = (
        f"0.9*sin(2*PI*(48+90*exp(-35*mod(t,{2*p})))*mod(t,{2*p}))*exp(-7*mod(t,{2*p}))"
        f"+0.35*(random(1)*2-1)*exp(-20*mod(t+{p},{2*p}))"
        f"+0.12*(random(0)*2-1)*exp(-70*mod(t,{p/2}))"
    )
    # Progresión menor i - VI - III - VII (un acorde por compás)
    ciclo = 16 * p
    frecuencia = (
        f"if(lt(mod(t,{ciclo}),{4*p}),{f0},if(lt(mod(t,{ciclo}),{8*p}),{f0*0.7937:.2f},"
        f"if(lt(mod(t,{ciclo}),{12*p}),{f0*1.1892:.2f},{f0*0.8909:.2f})))"
    )
    melodia = (
        f"0.10*sin(2*PI*{frecuencia}*t)+0.06*sin(2*PI*1.4983*{frecuencia}*t)"
        f"+0.09*sin(2*PI*2*{frecuencia}*t)*exp(-5*mod(t,{p/2}))"
    )
    for expresion, destino in ((drums, destino_drums), (melodia, destino_melodia)):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"aevalsrc='{expresion}':s=44100:c=mono:d={segundos}", "-c:a", "pcm_s16le", str(destino)],
            check=True, timeout=120,
        )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(destino_drums), "-i", str(destino_melodia),
         "-filter_complex", "amix=inputs=2:normalize=0,alimiter=limit=0.9", "-c:a", "pcm_s16le",
         str(destino_master)],
        check=True, timeout=120,
    )


def _sintetizar_python(carpeta, bpm, f0, segundos=20, tasa=22050):
    """Respaldo sin FFmpeg: genera los WAV con Python puro (solo para la demo)."""
    import array
    import math
    import random
    import wave

    rnd = random.Random(bpm)
    p = 60 / bpm
    grados = [1, 0.7937, 1.1892, 0.8909]
    pistas = {"drums": array.array("h"), "melodia": array.array("h"), "master": array.array("h"),
              "preview": array.array("h")}
    for n in range(segundos * tasa):
        t = n / tasa
        tk, ts, th = t % (2 * p), (t + p) % (2 * p), t % (p / 2)
        drums = (0.9 * math.sin(2 * math.pi * (48 + 90 * math.exp(-35 * tk)) * tk) * math.exp(-7 * tk)
                 + 0.35 * (rnd.random() * 2 - 1) * math.exp(-20 * ts)
                 + 0.12 * (rnd.random() * 2 - 1) * math.exp(-70 * th))
        f = f0 * grados[int((t % (16 * p)) // (4 * p))]
        melodia = (0.10 * math.sin(2 * math.pi * f * t) + 0.06 * math.sin(2 * math.pi * 1.4983 * f * t)
                   + 0.09 * math.sin(2 * math.pi * 2 * f * t) * math.exp(-5 * th))
        master = max(-0.9, min(0.9, drums + melodia))
        tag = 0.55 * math.sin(2 * math.pi * 1320 * t) if (t % 8) < 0.35 else 0
        for nombre, valor in (("drums", drums), ("melodia", melodia), ("master", master),
                              ("preview", max(-1, min(1, master + tag)))):
            pistas[nombre].append(int(max(-1, min(1, valor)) * 32000))
    rutas = {}
    for nombre, datos in pistas.items():
        rutas[nombre] = Path(carpeta) / f"{nombre}.wav"
        with wave.open(str(rutas[nombre]), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tasa)
            w.writeframes(datos.tobytes())
    return rutas


def _registrar_beat_sin_ffmpeg(datos, precios, rutas, stems):
    from .db import transaccion
    from .servicios.almacenamiento import obtener_almacenamiento

    almacenamiento = obtener_almacenamiento()
    master = almacenamiento.guardar_archivo(rutas["master"], "masters", "wav")
    preview = almacenamiento.guardar_archivo(rutas["preview"], "previews", "wav")
    claves_stems = almacenamiento.guardar_archivo(stems, "stems", "zip")
    db = get_db()
    with transaccion(db):
        beat_id = db.execute(
            "INSERT INTO beats (titulo, genero, bpm, tonalidad, mood, archivo_master, archivo_mp3, archivo_stems, "
            "archivo_preview, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datos["titulo"], datos["genero"], datos["bpm"], datos["tonalidad"], datos["mood"],
             master, master, claves_stems, preview, ahora()),
        ).lastrowid
        for codigo, precio in precios.items():
            db.execute("INSERT INTO licencias_beat (beat_id, tipo, precio) VALUES (?, ?, ?)", (beat_id, codigo, precio))


def cargar_demo():
    db = get_db()
    mensajes = []
    for nombre, email, password, rol in CUENTAS_DEMO:
        email = email or current_app.config["CORREO_PRODUCTOR"]
        if db.execute("SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone():
            continue
        crear_usuario(nombre, email, password, rol)
        mensajes.append(f"Cuenta {rol.lower()}: {email} / {password}")

    if db.execute("SELECT COUNT(*) FROM beats").fetchone()[0] > 0:
        mensajes.append("El catálogo ya tenía beats; no se agregaron nuevos.")
        return mensajes
    con_ffmpeg = audio.ffmpeg_disponible()
    if not con_ffmpeg:
        mensajes.append("FFmpeg no está instalado: los beats de ejemplo se generan en WAV con Python.")

    for titulo, genero, bpm, tonalidad, mood, f0, exclusiva in BEATS_DEMO:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            precios = {"BASICA": 15000, "PREMIUM": 30000, "STEMS": 60000, "EXCLUSIVA": exclusiva}
            datos = {"titulo": titulo, "genero": genero, "bpm": bpm, "tonalidad": tonalidad, "mood": mood}
            stems = tmp / "stems.zip"
            if con_ffmpeg:
                drums, melodia, master = tmp / "drums.wav", tmp / "melodia.wav", tmp / "master.wav"
                _sintetizar(drums, melodia, master, bpm, f0)
            else:
                rutas = _sintetizar_python(tmp, bpm, f0)
                drums, melodia = rutas["drums"], rutas["melodia"]
            with zipfile.ZipFile(stems, "w") as zz:
                zz.write(drums, "drums.wav")
                zz.write(melodia, "melodia.wav")
            if con_ffmpeg:
                crear_beat(datos, precios, master, stems)
            else:
                _registrar_beat_sin_ffmpeg(datos, precios, rutas, stems)
            mensajes.append(f"Beat creado: {titulo}")
    return mensajes
