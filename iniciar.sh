#!/bin/sh
# Arranque del contenedor.
# Si DEMO_AL_INICIAR=1 (demo pública gratuita), se copian las cuentas y beats de prueba
# generados al construir la imagen, para que el arranque sea inmediato.
set -e
DATA_DIR="${DATA_DIR:-/var/data}"
if [ "$DEMO_AL_INICIAR" = "1" ] && [ ! -f "$DATA_DIR/beatstore.db" ]; then
  mkdir -p "$DATA_DIR"
  if [ -f /srv/beatstore/demo_seed/beatstore.db ]; then
    cp -r /srv/beatstore/demo_seed/. "$DATA_DIR/"
  else
    flask --app app cargar-demo --forzar
  fi
fi
exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_WORKERS:-2}" --threads 4 \
  --timeout 120 --access-logfile - wsgi:app
