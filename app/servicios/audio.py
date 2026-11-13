"""Procesamiento de audio con FFmpeg (RF11 de la EV2).

- Valida que el archivo subido sea realmente un WAV (no basta con la extensión).
- Genera el MP3 sin tag para la licencia básica.
- Genera el preview público con un "tag" sonoro cada 8 segundos.

Los comandos se ejecutan con una lista de argumentos (sin shell), así que un
nombre de archivo malicioso no puede inyectar comandos del sistema.
"""
import json
import shutil
import subprocess
from pathlib import Path

DURACION_MAXIMA_SEG = 10 * 60


class ErrorAudio(Exception):
    pass


def ffmpeg_disponible():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def es_wav(ruta: Path) -> bool:
    with open(ruta, "rb") as archivo:
        cabecera = archivo.read(12)
    return len(cabecera) == 12 and cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WAVE"


def duracion_segundos(ruta: Path) -> float:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(ruta)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if salida.returncode != 0:
        raise ErrorAudio("El archivo no es un audio válido.")
    try:
        return float(json.loads(salida.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ErrorAudio("No se pudo leer la duración del audio.") from exc


def validar_master(ruta: Path):
    if not es_wav(ruta):
        raise ErrorAudio("El master debe ser un archivo WAV.")
    if not ffmpeg_disponible():
        raise ErrorAudio("FFmpeg no está instalado en el servidor.")
    duracion = duracion_segundos(ruta)
    if duracion <= 1 or duracion > DURACION_MAXIMA_SEG:
        raise ErrorAudio("El beat debe durar entre 1 segundo y 10 minutos.")
    return duracion


def _ejecutar(argumentos):
    salida = subprocess.run(["ffmpeg", "-y", "-v", "error", *argumentos],
                            capture_output=True, text=True, timeout=180, check=False)
    if salida.returncode != 0:
        raise ErrorAudio("FFmpeg no pudo procesar el audio.")


def generar_mp3(master: Path, destino: Path):
    _ejecutar(["-i", str(master), "-codec:a", "libmp3lame", "-b:a", "192k", str(destino)])


def generar_preview_con_tag(master: Path, destino: Path):
    """Mezcla el beat con un tono de marca (tag) de 0,35 s cada 8 segundos.
    En la versión final se reemplaza por la voz del productor ("MH Beats")."""
    filtro = (
        "aevalsrc='0.55*sin(2*PI*1320*t)*lt(mod(t\\,8)\\,0.35)':s=44100:c=mono[tag];"
        "[0:a]aformat=channel_layouts=mono[beat];"
        "[beat][tag]amix=inputs=2:duration=first:normalize=0[out]"
    )
    _ejecutar(["-i", str(master), "-filter_complex", filtro, "-map", "[out]",
               "-codec:a", "libmp3lame", "-b:a", "128k", str(destino)])
