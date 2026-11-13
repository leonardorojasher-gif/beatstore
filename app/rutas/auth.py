"""Registro, inicio y cierre de sesión, y datos de la cuenta."""
import json
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, Response, current_app, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import ahora, get_db
from ..seguridad import (destino_seguro, limitar, login_requerido, registrar_evento, texto_limpio,
                         usuario_actual, validar_email, validar_password)

bp = Blueprint("auth", __name__)

# Hash ficticio para que el tiempo de respuesta sea igual exista o no el correo
_HASH_FICTICIO = generate_password_hash("contraseña-inexistente-123", method="scrypt")


@bp.route("/registro", methods=["GET", "POST"])
@limitar(maximo=5, ventana_segundos=600)
def registro():
    if usuario_actual():
        return redirect(url_for("publico.catalogo"))
    errores, datos = [], {}
    if request.method == "POST":
        datos["nombre"] = texto_limpio(request.form.get("nombre"), 80)
        datos["email"] = texto_limpio(request.form.get("email"), 254).lower()
        password = request.form.get("password", "")
        confirmacion = request.form.get("confirmacion", "")
        if len(datos["nombre"]) < 2:
            errores.append("Ingresa tu nombre artístico o nombre real.")
        if not validar_email(datos["email"]):
            errores.append("Ingresa un correo válido.")
        errores += validar_password(password, datos["email"])
        if password != confirmacion:
            errores.append("Las contraseñas no coinciden.")
        if request.form.get("acepto") != "si":
            errores.append("Debes aceptar los términos y la política de privacidad.")
        db = get_db()
        if not errores and db.execute("SELECT 1 FROM usuarios WHERE email = ?", (datos["email"],)).fetchone():
            errores.append("No pudimos crear la cuenta con ese correo. Si ya tienes cuenta, inicia sesión.")
        if not errores:
            usuario_id = db.execute(
                "INSERT INTO usuarios (nombre, email, password_hash, rol, acepta_terminos_en, creado_en) "
                "VALUES (?, ?, ?, 'ARTISTA', ?, ?)",
                (datos["nombre"], datos["email"], generate_password_hash(password, method="scrypt"), ahora(), ahora()),
            ).lastrowid
            registrar_evento("REGISTRO", f"usuario={usuario_id}", usuario_id=usuario_id)
            _iniciar_sesion(usuario_id, "ARTISTA")
            flash("¡Cuenta creada! Ya puedes comprar beats.", "ok")
            return redirect(url_for("publico.catalogo"))
    return render_template("registro.html", errores=errores, datos=datos)


@bp.route("/login", methods=["GET", "POST"])
@limitar(maximo=10, ventana_segundos=300)
def login():
    if usuario_actual():
        return redirect(url_for("publico.catalogo"))
    error = None
    email = ""
    if request.method == "POST":
        email = texto_limpio(request.form.get("email"), 254).lower()
        password = request.form.get("password", "")[:128]
        db = get_db()
        usuario = db.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        ahora_dt = datetime.now(timezone.utc)
        bloqueado = (
            usuario is not None and usuario["bloqueado_hasta"]
            and datetime.fromisoformat(usuario["bloqueado_hasta"]) > ahora_dt
        )
        hash_a_comparar = usuario["password_hash"] if usuario else _HASH_FICTICIO
        clave_ok = check_password_hash(hash_a_comparar, password)

        if usuario and clave_ok and not bloqueado:
            db.execute("UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?", (usuario["id"],))
            registrar_evento("LOGIN_OK", usuario_id=usuario["id"])
            _iniciar_sesion(usuario["id"], usuario["rol"])
            siguiente = destino_seguro(request.args.get("next"))
            if usuario["rol"] == "PRODUCTOR":
                return redirect(siguiente or url_for("admin.panel"))
            return redirect(siguiente or url_for("publico.catalogo"))

        if usuario and not bloqueado:
            intentos = usuario["intentos_fallidos"] + 1
            hasta = None
            if intentos >= current_app.config["LOGIN_MAX_INTENTOS"]:
                minutos = current_app.config["LOGIN_BLOQUEO_MINUTOS"]
                hasta = (ahora_dt + timedelta(minutes=minutos)).replace(microsecond=0).isoformat()
                intentos = 0
                registrar_evento("CUENTA_BLOQUEADA", f"email={email}", usuario_id=usuario["id"])
            db.execute("UPDATE usuarios SET intentos_fallidos = ?, bloqueado_hasta = ? WHERE id = ?",
                       (intentos, hasta, usuario["id"]))
        registrar_evento("LOGIN_FALLIDO", f"email={email}", usuario_id=usuario["id"] if usuario else None)
        # Mensaje genérico: no revela si el correo existe ni si la cuenta está bloqueada
        error = "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente."
    return render_template("login.html", error=error, email=email)


def _iniciar_sesion(usuario_id, rol):
    carrito = session.get("carrito", [])
    session.clear()  # nueva sesión: evita la fijación de sesión
    session["usuario_id"] = usuario_id
    session["rol"] = rol
    if rol == "ARTISTA":
        session["carrito"] = carrito


@bp.post("/logout")
def logout():
    registrar_evento("LOGOUT")
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("publico.catalogo"))


@bp.get("/cuenta")
@login_requerido
def cuenta():
    return render_template("cuenta.html")


@bp.get("/cuenta/mis-datos.json")
@login_requerido
def exportar_mis_datos():
    """Derecho de acceso y portabilidad: el usuario descarga sus datos."""
    usuario = usuario_actual()
    db = get_db()
    datos = dict(db.execute(
        "SELECT nombre, email, rol, acepta_terminos_en, creado_en FROM usuarios WHERE id = ?", (usuario["id"],)
    ).fetchone())
    datos["ordenes"] = [dict(fila) for fila in db.execute(
        "SELECT id, estado, total, creada_en, pagada_en FROM ordenes WHERE usuario_id = ? ORDER BY id",
        (usuario["id"],),
    )]
    registrar_evento("EXPORTAR_DATOS")
    return Response(
        json.dumps(datos, ensure_ascii=False, indent=2), mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=mis-datos-beatstore.json"},
    )
