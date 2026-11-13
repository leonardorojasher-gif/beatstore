"""Generación del contrato de licencia en PDF (RF07 de la EV2).

Cada contrato recibe un código único y se guarda su huella SHA-256, para poder
comprobar más adelante que el documento no fue alterado.
"""
import hashlib
import io
import uuid
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


def _p(texto, estilo):
    return Paragraph(escape(str(texto)), estilo)


def generar_contrato(productor, comprador, beat, licencia, precio, orden_id):
    codigo = f"BS-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Contrato de licencia {codigo}", author="BeatStore",
    )
    base = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=base["Title"], fontSize=16, spaceAfter=6)
    normal = ParagraphStyle("n", parent=base["BodyText"], fontSize=10, leading=14)
    pequeno = ParagraphStyle("s", parent=normal, fontSize=8, textColor=colors.grey)

    filas = [
        ["Código del contrato", codigo],
        ["Orden de compra", f"N.° {orden_id}"],
        ["Licenciante (productor)", productor],
        ["Licenciatario (artista)", f"{comprador['nombre']} <{comprador['email']}>"],
        ["Beat", f"«{beat['titulo']}» ({beat['genero']}, {beat['bpm']} BPM, {beat['tonalidad']})"],
        ["Tipo de licencia", licencia["nombre"]],
        ["Archivos entregados", licencia["archivos"]],
        ["Límite de reproducciones", licencia["limite_reproducciones"]],
        ["Monetización", licencia["monetizacion"]],
        ["Precio pagado", f"${precio:,.0f} CLP".replace(",", ".")],
        ["Fecha", datetime.now().strftime("%d-%m-%Y %H:%M")],
    ]
    tabla = Table([[_p(a, normal), _p(b, normal)] for a, b in filas], colWidths=[5.2 * cm, 11.4 * cm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F1F4")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBC4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    clausulas = [
        "1. El licenciante declara ser el autor de la composición instrumental y otorga al "
        "licenciatario una licencia de uso según las condiciones indicadas en la tabla anterior.",
        "2. El licenciatario puede grabar una canción sobre el beat y distribuirla dentro del "
        "límite de reproducciones de su licencia. No puede revender ni redistribuir el beat por sí solo.",
        "3. El licenciante conserva los derechos de autor de la composición, conforme a la Ley "
        "N.° 17.336 sobre propiedad intelectual. En la licencia exclusiva, el beat se retira de la "
        "venta y no se vuelve a licenciar a terceros.",
        "4. El licenciatario debe mencionar al productor en los créditos de la canción.",
        "5. Los datos personales del licenciatario se usan solo para emitir este contrato y "
        "gestionar la compra, conforme a la Ley N.° 19.628 sobre protección de datos personales.",
    ]

    contenido = [
        _p("Contrato de licencia de uso de beat", titulo),
        _p("BeatStore: tienda en línea de beats", normal),
        Spacer(1, 0.4 * cm), tabla, Spacer(1, 0.5 * cm),
    ]
    contenido += [_p(c, normal) for c in clausulas]
    contenido += [
        Spacer(1, 0.8 * cm),
        _p("Documento generado automáticamente por BeatStore. Para verificar su autenticidad, "
           "indique el código del contrato al productor.", pequeno),
    ]
    doc.build(contenido)
    pdf = buffer.getvalue()
    return pdf, codigo, hashlib.sha256(pdf).hexdigest()
