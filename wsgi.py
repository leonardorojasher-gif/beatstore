"""Punto de entrada para el servidor de producción (gunicorn wsgi:app)."""
from app import create_app

app = create_app()
