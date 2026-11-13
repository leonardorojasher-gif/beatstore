"""Pruebas del proceso crítico de compra, pago, exclusivas y descargas."""
import io
import zipfile

from app.db import get_db

from .conftest import comprar, crear_beat_prueba, login, post


def _orden(app, token):
    with app.app_context():
        return get_db().execute("SELECT * FROM ordenes WHERE token_pasarela = ?", (token,)).fetchone()


def test_compra_aprobada_genera_contrato_y_correos(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    token, final = comprar(client, licencias["PREMIUM"])
    assert "Pago aprobado".encode() in final.data
    orden = _orden(app, token)
    assert orden["estado"] == "PAGADA" and orden["total"] == 30000
    with app.app_context():
        db = get_db()
        detalle = db.execute("SELECT * FROM detalle_orden WHERE orden_id = ?", (orden["id"],)).fetchone()
        assert detalle["contrato_codigo"].startswith("BS-") and len(detalle["contrato_sha256"]) == 64
        destinatarios = [c["destinatario"] for c in db.execute("SELECT destinatario FROM correos")]
    assert "ana@demo.cl" in destinatarios and "productor@beatstore.cl" in destinatarios


def test_pago_rechazado_no_entrega_nada(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    token, final = comprar(client, licencias["BASICA"], accion="rechazar")
    assert "rechazado".encode() in final.data
    orden = _orden(app, token)
    assert orden["estado"] == "RECHAZADA"
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM enlaces_descarga").fetchone()[0] == 0


def test_precio_lo_define_el_servidor(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    post(client, "/carrito/agregar", {"licencia_id": licencias["STEMS"], "precio": 1})
    r = post(client, "/checkout", {"acepto_licencia": "si", "total": 1})
    token = r.headers["Location"].split("token_ws=")[1]
    assert _orden(app, token)["total"] == 60000


def test_monto_manipulado_anula_la_orden(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    post(client, "/carrito/agregar", {"licencia_id": licencias["BASICA"]})
    r = post(client, "/checkout", {"acepto_licencia": "si"})
    token = r.headers["Location"].split("token_ws=")[1]
    with app.app_context():  # simula una respuesta alterada de la pasarela
        get_db().execute("UPDATE sandbox_transacciones SET monto = 10 WHERE token = ?", (token,))
    retorno = post(client, "/sandbox-webpay/pagar", {"token_ws": token, "accion": "aprobar"})
    client.get(retorno.headers["Location"])
    orden = _orden(app, token)
    assert orden["estado"] == "ANULADA" and "monto" in orden["motivo"]


def test_token_de_pago_no_se_procesa_dos_veces(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    token, _ = comprar(client, licencias["BASICA"])
    client.get(f"/pago/retorno?token_ws={token}")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM enlaces_descarga").fetchone()[0] == 1


def test_exclusiva_retira_el_beat_del_catalogo(app, client):
    beat_id, licencias = crear_beat_prueba(app, titulo="Beat Unico")
    login(client, "ana@demo.cl")
    token, _ = comprar(client, licencias["EXCLUSIVA"])
    assert _orden(app, token)["estado"] == "PAGADA"
    assert f'href="/beat/{beat_id}"'.encode() not in client.get("/").data
    assert client.get(f"/beat/{beat_id}").status_code == 404


def test_exclusiva_no_se_vende_dos_veces(app):
    """Dos artistas pagan la misma exclusiva: solo el primero la obtiene."""
    _, licencias = crear_beat_prueba(app)
    ana, beto = app.test_client(), app.test_client()
    login(ana, "ana@demo.cl")
    login(beto, "beto@demo.cl")
    tokens = []
    for cliente in (ana, beto):  # ambos llegan a la pasarela con el beat disponible
        post(cliente, "/carrito/agregar", {"licencia_id": licencias["EXCLUSIVA"]})
        r = post(cliente, "/checkout", {"acepto_licencia": "si"})
        tokens.append(r.headers["Location"].split("token_ws=")[1])
    for cliente, token in zip((ana, beto), tokens):
        retorno = post(cliente, "/sandbox-webpay/pagar", {"token_ws": token, "accion": "aprobar"})
        cliente.get(retorno.headers["Location"])
    assert _orden(app, tokens[0])["estado"] == "PAGADA"
    segunda = _orden(app, tokens[1])
    assert segunda["estado"] == "ANULADA" and "exclusiva" in segunda["motivo"]
    with app.app_context():
        anulada = get_db().execute("SELECT estado FROM sandbox_transacciones WHERE token = ?", (tokens[1],)).fetchone()
    assert anulada["estado"] == "ANULADA"  # el cobro se revierte


def test_descarga_entrega_zip_con_contrato(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    token, _ = comprar(client, licencias["STEMS"])
    with app.app_context():
        detalle_id = get_db().execute("SELECT id FROM detalle_orden").fetchone()["id"]
    r = post(client, f"/mis-compras/{detalle_id}/descargar")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    nombres = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert "beat.wav" in nombres and "stems.zip" in nombres
    assert any(n.startswith("contrato_") and n.endswith(".pdf") for n in nombres)


def test_limite_de_cinco_descargas(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    comprar(client, licencias["BASICA"])
    with app.app_context():
        detalle_id = get_db().execute("SELECT id FROM detalle_orden").fetchone()["id"]
    codigos = [post(client, f"/mis-compras/{detalle_id}/descargar").status_code for _ in range(6)]
    assert codigos[:5] == [200] * 5 and codigos[5] == 302


def test_enlace_vencido(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    comprar(client, licencias["BASICA"])
    with app.app_context():
        db = get_db()
        detalle_id = db.execute("SELECT id FROM detalle_orden").fetchone()["id"]
        db.execute("UPDATE enlaces_descarga SET expira_en = '2000-01-01T00:00:00+00:00'")
    assert post(client, f"/mis-compras/{detalle_id}/descargar").status_code == 302
    assert post(client, f"/mis-compras/{detalle_id}/renovar").status_code == 302
    assert post(client, f"/mis-compras/{detalle_id}/descargar").status_code == 200


def test_otro_usuario_no_puede_descargar_ni_ver_la_orden(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    token, _ = comprar(client, licencias["BASICA"])
    orden_id = _orden(app, token)["id"]
    with app.app_context():
        detalle_id = get_db().execute("SELECT id FROM detalle_orden").fetchone()["id"]
    intruso = app.test_client()
    login(intruso, "beto@demo.cl")
    assert intruso.get(f"/orden/{orden_id}").status_code == 404
    assert post(intruso, f"/mis-compras/{detalle_id}/descargar").status_code == 404


def test_token_de_descarga_se_guarda_hasheado(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    comprar(client, licencias["BASICA"])
    with app.app_context():
        db = get_db()
        cuerpo = db.execute("SELECT cuerpo FROM correos WHERE destinatario = 'ana@demo.cl'").fetchone()["cuerpo"]
        token = cuerpo.split("/descargar/")[1].split()[0]
        assert db.execute("SELECT COUNT(*) FROM enlaces_descarga WHERE token_hash = ?", (token,)).fetchone()[0] == 0
    assert client.get(f"/descargar/{token}").status_code == 200
    assert client.get("/descargar/token-inventado").status_code == 404


def test_productor_no_ve_enlaces_privados_en_correos(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    comprar(client, licencias["BASICA"])
    productor = app.test_client()
    login(productor, "productor@beatstore.cl")
    r = productor.get("/panel/correos")
    assert "[enlace privado]".encode() in r.data


def test_panel_muestra_ventas_y_exporta_csv(app, client):
    _, licencias = crear_beat_prueba(app)
    login(client, "ana@demo.cl")
    comprar(client, licencias["PREMIUM"])
    productor = app.test_client()
    login(productor, "productor@beatstore.cl")
    assert b"$30.000" in productor.get("/panel/").data
    csv = productor.get("/panel/ventas.csv")
    assert csv.status_code == 200 and "ana@demo.cl".encode() in csv.data
