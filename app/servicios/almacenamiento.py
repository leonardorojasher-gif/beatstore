"""Adaptador de almacenamiento de archivos (interfaz IAlmacenamiento de la EV2).

El prototipo guarda en disco local (o en el disco persistente del servicio en
la nube). Para producción basta con escribir otro adaptador (por ejemplo, un
bucket S3 o Supabase Storage) que cumpla la misma interfaz.
"""
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from flask import current_app

CARPETAS_PERMITIDAS = {"masters", "mp3", "stems", "previews", "contratos"}


class IAlmacenamiento(ABC):
    @abstractmethod
    def guardar_archivo(self, origen: Path, carpeta: str, extension: str) -> str:
        """Copia un archivo y devuelve su clave interna."""

    @abstractmethod
    def guardar_bytes(self, datos: bytes, carpeta: str, extension: str) -> str:
        """Guarda bytes y devuelve su clave interna."""

    @abstractmethod
    def ruta(self, clave: str) -> Path:
        """Devuelve la ruta física de una clave, validando que sea segura."""


class AlmacenamientoLocal(IAlmacenamiento):
    def __init__(self, base: Path):
        self.base = Path(base).resolve()
        for carpeta in CARPETAS_PERMITIDAS:
            (self.base / carpeta).mkdir(parents=True, exist_ok=True)

    def _nueva_clave(self, carpeta, extension):
        if carpeta not in CARPETAS_PERMITIDAS:
            raise ValueError("Carpeta no permitida")
        extension = extension.lower().lstrip(".")
        if not extension.isalnum():
            raise ValueError("Extensión no válida")
        # El nombre lo genera el sistema: nunca se usa el nombre que envía el usuario
        return f"{carpeta}/{uuid.uuid4().hex}.{extension}"

    def guardar_archivo(self, origen, carpeta, extension):
        clave = self._nueva_clave(carpeta, extension)
        shutil.copyfile(origen, self.ruta(clave))
        return clave

    def guardar_bytes(self, datos, carpeta, extension):
        clave = self._nueva_clave(carpeta, extension)
        self.ruta(clave).write_bytes(datos)
        return clave

    def ruta(self, clave):
        destino = (self.base / clave).resolve()
        # Evita path traversal (por ejemplo, claves con "../")
        if self.base not in destino.parents:
            raise ValueError("Ruta fuera del almacenamiento")
        return destino


def obtener_almacenamiento() -> IAlmacenamiento:
    return AlmacenamientoLocal(current_app.config["STORAGE_DIR"])
