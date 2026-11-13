# BeatStore: tienda en línea de licencias de beats

Prototipo funcional desarrollado para la Evaluación 3 de **Ingeniería de Software** (INACAP).
Continúa el análisis y diseño de la EV2: un productor musical independiente (MH Beats) vende
licencias de sus beats sin depender de Instagram, WhatsApp, transferencias ni enlaces de Drive.

## Qué hace el prototipo

| Requerimiento (EV2) | Implementación |
|---|---|
| RF01 Registro e inicio de sesión | Cuenta con correo y contraseña (hash scrypt), bloqueo tras 5 intentos |
| RF02 Catálogo con filtros | Género, BPM, tonalidad, mood, precio y búsqueda por nombre |
| RF03 Preview con tag | Preview completo con tag sonoro generado con FFmpeg; sin botón de descarga |
| RF04 Tipos de licencia | Básica, Premium, Stems y Exclusiva, con precio editable por beat |
| RF05 / RF06 Carrito y pago en línea | Carrito y pasarela simulada que reproduce el flujo de Webpay Plus |
| RF07 Contrato PDF | Generado automáticamente, con código único y huella SHA-256 |
| RF08 / RF09 Entrega segura | ZIP con archivos y contrato; enlaces de 7 días o 5 descargas; "Mis compras" |
| RF10 Exclusivas | Al venderse, el beat se retira solo; no se puede vender dos veces |
| RF11 Subida de beats | Validación del WAV, MP3 y preview con tag automáticos |
| RF13 Reportes | Ventas por beat y por licencia; exportación CSV para Excel |
| RF16 Notificación de venta | Correo al artista (comprobante) y al productor |

Quedaron fuera del prototipo (prioridad *Could*): cupones, solicitudes de beats personalizados y favoritos.

## Tecnologías

- **Backend:** Python 3.13 + Flask 3, plantillas Jinja2 (HTML y CSS propios, sin JavaScript en línea).
- **Datos:** SQLite en el prototipo (el modelo está listo para migrar a PostgreSQL gestionado).
- **Audio:** FFmpeg. **PDF:** ReportLab.
- **Nube:** contenedor Docker, despliegue en Render (PaaS) con `render.yaml`, integración continua en
  GitHub Actions y Dependabot.

## Ejecutar en tu computador

Requisitos: Python 3.11 o superior. FFmpeg es opcional para la demo (sin FFmpeg los beats de ejemplo
se generan en WAV), pero es necesario para subir beats nuevos desde el panel.

```bash
# 1. Crear y activar un entorno virtual
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt -r requirements-dev.txt

# 3. Cargar cuentas y beats de ejemplo
flask --app app cargar-demo

# 4. Levantar el servidor
flask --app app run
```

Abre <http://127.0.0.1:5000>.

| Rol | Correo | Contraseña |
|---|---|---|
| Productor (panel) | productor@beatstore.cl | MHbeats2026 |
| Artista | valentina@demo.cl | BeatsDemo2026 |
| Artista | benjamin@demo.cl | BeatsDemo2026 |

Estas cuentas son solo para la demo local; el comando `cargar-demo` se niega a ejecutarse en producción.

## Guion sugerido para la presentación

1. **Catálogo:** filtrar por género "Trap" y BPM 120 a 145; reproducir un preview (se escucha el tag).
2. **Compra:** entrar como Valentina, agregar la licencia Premium de un beat, pagar y aprobar en la
   pasarela de pruebas. Mostrar el resultado y descargar el ZIP desde "Mis compras" (incluye el contrato PDF).
3. **Exclusiva:** en dos navegadores (Valentina y Benjamín) agregar la licencia Exclusiva del mismo beat
   y llegar ambos a la pasarela. Aprobar primero uno y luego el otro: el segundo pago se anula solo.
4. **Panel del productor:** ventas por beat y licencia, exportar CSV, auditoría (intentos fallidos,
   descargas, pagos) y correos enviados.
5. **Seguridad:** equivocarse 5 veces en el login y mostrar el bloqueo; intentar entrar a `/panel/` como
   artista (403); ejecutar `pytest -q` (41 pruebas).

## Pruebas automatizadas

```bash
pytest -q
```

Cubren el flujo de compra completo, el pago rechazado, el monto manipulado, la doble venta de una
exclusiva, el límite y vencimiento de descargas, el control de acceso, CSRF, inyección SQL, XSS,
política de contraseñas, bloqueo de cuenta y cabeceras de seguridad. Ver `docs/SEGURIDAD.md`.

## Desplegar en la nube (Render)

1. Sube el proyecto a un repositorio de GitHub (ver abajo).
2. En Render: **New → Blueprint**, elige el repositorio. Render lee `render.yaml`, construye la imagen
   Docker, genera la `SECRET_KEY` y monta un disco persistente en `/var/data`.
3. Cuando el servicio esté activo, abre la consola (**Shell**) del servicio y crea la cuenta del productor:
   `flask --app app crear-productor`.

Los discos persistentes de Render requieren un plan pagado (Starter). Para escalar a varias instancias,
la base de datos se mueve a PostgreSQL gestionado y los archivos a un almacenamiento de objetos (S3),
como se diseñó en la EV2; el código ya separa ambos con interfaces (`IAlmacenamiento`, repositorio SQL).

## Subir a GitHub

```bash
git init
git add .
git commit -m "Prototipo BeatStore EV3"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/beatstore.git
git push -u origin main
```

Al subirlo, GitHub Actions ejecuta las pruebas y la auditoría de dependencias en cada push.
El archivo `.gitignore` evita subir la base de datos, los audios y el archivo `.env`.

## Estructura

```
app/
  __init__.py          fábrica de la aplicación, errores y comandos
  config.py            configuración por variables de entorno
  seguridad.py         CSRF, roles, validaciones, limitador, auditoría, cabeceras
  servicios/           lógica de negocio y adaptadores (pagos, correo, almacenamiento, audio, PDF)
  rutas/               catálogo, autenticación, compra, panel y pasarela de pruebas
  templates/ static/   interfaz web
tests/                 pruebas automatizadas (pytest)
docs/SEGURIDAD.md      medidas OWASP y normativa
Dockerfile, render.yaml, .github/   despliegue e integración continua
```
