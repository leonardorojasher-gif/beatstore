"""Pruebas de los controles de seguridad (OWASP Top 10:2025)."""
from app.seguridad import celda_csv_segura, validar_password

from .conftest import CLAVE, crear_beat_prueba, login, post


def test_cabeceras_de_seguridad(client):
    r = client.get("/")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_cookie_de_sesion_httponly(client):
    r = login(client, "ana@demo.cl")
    cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_post_sin_csrf_es_rechazado(client):
    r = client.post("/login", data={"email": "ana@demo.cl", "password": CLAVE})
    assert r.status_code == 400


def test_politica_de_contrasenas():
    assert validar_password("corta1")
    assert validar_password("soloLetrasLargas")
    assert validar_password("anita2026xyz", "anita@demo.cl")
    assert validar_password("ClaveSegura2026") == []


def test_registro_rechaza_contrasena_debil(client):
    r = post(client, "/registro", {"nombre": "Pepe", "email": "pepe@demo.cl", "password": "123",
                                   "confirmacion": "123", "acepto": "si"})
    assert r.status_code == 200
    assert "al menos 10 caracteres".encode() in r.data


def test_registro_exige_aceptar_privacidad(client):
    r = post(client, "/registro", {"nombre": "Pepe", "email": "pepe@demo.cl", "password": CLAVE,
                                   "confirmacion": CLAVE})
    assert "política de privacidad".encode() in r.data


def test_contrasena_se_guarda_hasheada(app, client):
    from app.db import get_db
    with app.app_context():
        fila = get_db().execute("SELECT password_hash FROM usuarios WHERE email = 'ana@demo.cl'").fetchone()
    assert fila["password_hash"].startswith("scrypt:")
    assert CLAVE not in fila["password_hash"]


def test_login_mensaje_generico(client):
    r1 = login(client, "ana@demo.cl", "ClaveIncorrecta99")
    r2 = login(client, "noexiste@demo.cl", "ClaveIncorrecta99")
    assert b"Correo o contrase" in r1.data and b"Correo o contrase" in r2.data


def test_bloqueo_tras_cinco_intentos(client):
    for _ in range(5):
        login(client, "ana@demo.cl", "ClaveIncorrecta99")
    r = login(client, "ana@demo.cl")  # contraseña correcta, pero la cuenta está bloqueada
    assert r.status_code == 200 and b"bloqueada" in r.data


def test_limite_de_peticiones_login(client):
    codigos = [login(client, "x@demo.cl", "ClaveIncorrecta99").status_code for _ in range(11)]
    assert codigos[-1] == 429


def test_artista_no_entra_al_panel(client):
    login(client, "ana@demo.cl")
    assert client.get("/panel/").status_code == 403


def test_anonimo_es_redirigido_al_login(client):
    r = client.get("/panel/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_redireccion_externa_bloqueada(client):
    r = post(client, "/login?next=//sitio-malicioso.com", {"email": "ana@demo.cl", "password": CLAVE})
    assert "sitio-malicioso" not in r.headers["Location"]


def test_inyeccion_sql_en_filtros(app, client):
    crear_beat_prueba(app)
    r = client.get("/?genero=Trap' OR 1=1 --&bpm_min=1;DROP TABLE beats&q=%' OR '1'='1")
    assert r.status_code == 200
    assert client.get("/").status_code == 200  # la tabla sigue existiendo


def test_xss_escapado(app, client):
    crear_beat_prueba(app, titulo="<script>alert(1)</script>")
    r = client.get("/")
    assert b"<script>alert(1)</script>" not in r.data
    assert b"&lt;script&gt;" in r.data


def test_csv_sin_inyeccion_de_formulas():
    assert celda_csv_segura("=HYPERLINK(\"http://x\")").startswith("'=")
    assert celda_csv_segura("Valentina") == "Valentina"


def test_errores_no_muestran_trazas(client):
    r = client.get("/no-existe")
    assert r.status_code == 404 and b"Traceback" not in r.data


def test_auditoria_registra_login_fallido(app, client):
    login(client, "ana@demo.cl", "ClaveIncorrecta99")
    from app.db import get_db
    with app.app_context():
        eventos = [f["evento"] for f in get_db().execute("SELECT evento FROM auditoria")]
    assert "LOGIN_FALLIDO" in eventos


def test_exportar_mis_datos(client):
    login(client, "ana@demo.cl")
    r = client.get("/cuenta/mis-datos.json")
    assert r.status_code == 200 and r.json["email"] == "ana@demo.cl"
    assert "password_hash" not in r.json
