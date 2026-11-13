# Seguridad, normativa y ética en BeatStore

## Medidas según el OWASP Top 10:2025

| Riesgo OWASP | Medida en el prototipo | Dónde está | Prueba |
|---|---|---|---|
| A01 Broken Access Control | Roles ARTISTA / PRODUCTOR; el panel exige PRODUCTOR; cada orden y descarga se filtra por el dueño (evita IDOR); token CSRF en todos los formularios; redirecciones solo internas | `seguridad.py`, `rutas/admin.py`, `rutas/compra.py` | `test_artista_no_entra_al_panel`, `test_otro_usuario_no_puede_descargar_ni_ver_la_orden`, `test_post_sin_csrf_es_rechazado`, `test_redireccion_externa_bloqueada` |
| A02 Security Misconfiguration | Cabeceras CSP, X-Frame-Options, nosniff, HSTS en producción; sin modo debug; la app no inicia en producción sin `SECRET_KEY`; contenedor sin root | `seguridad.py`, `__init__.py`, `Dockerfile` | `test_cabeceras_de_seguridad` |
| A03 Software Supply Chain Failures | Versiones fijas en `requirements.txt`; `pip-audit` en GitHub Actions; Dependabot semanal | `.github/` | CI |
| A04 Cryptographic Failures | Contraseñas con scrypt; tokens de descarga de 256 bits guardados como SHA-256; HTTPS obligatorio en la nube; no se guardan datos de tarjetas | `rutas/auth.py`, `servicios/entregas.py` | `test_contrasena_se_guarda_hasheada`, `test_token_de_descarga_se_guarda_hasheado` |
| A05 Injection | Consultas parametrizadas; filtros con lista blanca; autoescape de Jinja (XSS); neutralización de fórmulas en el CSV; FFmpeg sin shell | `servicios/catalogo.py`, `seguridad.py`, `servicios/audio.py` | `test_inyeccion_sql_en_filtros`, `test_xss_escapado`, `test_csv_sin_inyeccion_de_formulas` |
| A06 Insecure Design | Precio calculado en el servidor; monto del pago verificado; venta de exclusivas en transacción con bloqueo; límites de descargas | `servicios/compras.py` | `test_precio_lo_define_el_servidor`, `test_monto_manipulado_anula_la_orden`, `test_exclusiva_no_se_vende_dos_veces` |
| A07 Authentication Failures | Política de contraseñas; bloqueo de 15 min tras 5 intentos; límite de peticiones por IP; mensaje genérico; sesión nueva al ingresar; cookie HttpOnly, SameSite y Secure; expiración por inactividad | `rutas/auth.py`, `config.py` | `test_bloqueo_tras_cinco_intentos`, `test_limite_de_peticiones_login`, `test_login_mensaje_generico` |
| A08 Software or Data Integrity Failures | El resultado del pago se confirma servidor a servidor y un token se usa una sola vez; huella SHA-256 de cada contrato; validación del WAV por su contenido | `servicios/compras.py`, `servicios/licencias.py` | `test_token_de_pago_no_se_procesa_dos_veces`, `test_subida_rechaza_archivo_que_no_es_wav` |
| A09 Logging & Alerting Failures | Tabla de auditoría (logins, bloqueos, accesos denegados, pagos, descargas) visible en el panel; logs a la salida estándar para la nube; nunca se registran contraseñas | `seguridad.py`, `templates/admin/auditoria.html` | `test_auditoria_registra_login_fallido` |
| A10 Mishandling of Exceptional Conditions | Las transacciones se deshacen si algo falla; si la exclusiva ya no está, el pago se anula; un correo que falla no revierte la venta; errores sin trazas y con código de soporte | `db.py`, `servicios/compras.py`, `__init__.py` | `test_errores_no_muestran_trazas`, `test_pago_rechazado_no_entrega_nada` |

## Normativa chilena considerada

- **Ley N.° 21.459 sobre delitos informáticos:** el sistema protege contra el acceso ilícito (art. 2) con
  autenticación, roles y bloqueo; registra los intentos en la auditoría como evidencia; no permite que
  un usuario acceda a datos de otro. Los términos de uso advierten que eludir las medidas de seguridad
  puede ser delito.
- **Ley N.° 19.628 y Ley N.° 21.719 (protección de datos personales):** se piden solo los datos
  necesarios, se informa su finalidad en la política de privacidad, se pide consentimiento al registrarse
  y el usuario puede descargar sus datos desde "Mi cuenta".
- **Ley N.° 17.336 (propiedad intelectual):** los contratos dejan claro que el productor conserva los
  derechos de autor y qué uso otorga cada licencia.

## Pendiente antes de producción

- Integrar Webpay Plus real con sus credenciales de integración y luego de producción.
- Migrar a PostgreSQL gestionado y almacenamiento de objetos para poder escalar a varias instancias.
- Mover el limitador de peticiones a Redis (hoy vive en la memoria de cada proceso).
- Revisión legal de los textos de contrato, términos y privacidad.
- Prueba de penetración autorizada antes del lanzamiento.
