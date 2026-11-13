# Imagen de BeatStore para desplegar en la nube (Render, Azure App Service, AWS App Runner, etc.)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATA_DIR=/var/data \
    PORT=8000

# FFmpeg genera el MP3 y el preview con tag de cada beat
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/beatstore
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py iniciar.sh ./

# Datos de demostración pregenerados (solo se usan si DEMO_AL_INICIAR=1)
RUN DATA_DIR=/srv/beatstore/demo_seed SECRET_KEY=solo-para-construir \
    flask --app app cargar-demo --forzar

# La aplicación no se ejecuta como root (mínimo privilegio)
RUN useradd --create-home --uid 10001 beatstore \
    && mkdir -p /var/data \
    && chown -R beatstore:beatstore /var/data
USER beatstore

EXPOSE 8000
CMD ["sh", "iniciar.sh"]
