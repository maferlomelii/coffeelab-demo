"""Reporte mensual en PDF (una página) con reportlab. app.py le pasa los números ya calculados."""
import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import motor


def clean_text(text) -> str:
    """Quita lo que Helvetica no puede dibujar (emojis) y escapa XML."""
    return escape(str(text).encode("cp1252", errors="ignore").decode("cp1252"))


def rich(text) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean_text(text))


def build_pdf(marca: dict, mes_label: str, k: dict, kprev: dict, T, alertas: list) -> bytes:
    C = {n: colors.HexColor(v) for n, v in marca["colores"].items()}
    cfg = marca["kpis"]
    buf = io.BytesIO()
    W, H = A4
    M = 16 * mm

    def banda(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C["oscuro"])
        canvas.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
        canvas.setFillColor(C["claro"])
        canvas.setFont("Times-Bold", 24)
        canvas.drawString(M, H - 18 * mm, clean_text(marca["cliente"]))
        canvas.setFillColor(C["acento_claro"])
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(M, H - 26 * mm, clean_text(f"REPORTE MENSUAL DE OPERACIÓN · {mes_label}"))
        canvas.setFillColor(C["gris"])
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(M, 10 * mm, clean_text(f"{marca['titulo_app']} · Demo con datos ficticios"))
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=42 * mm, bottomMargin=16 * mm)
    base = dict(fontName="Helvetica", textColor=C["oscuro"])
    st_body = ParagraphStyle("b", fontSize=9.5, leading=13.5, **base)
    st_h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=C["acento"], spaceBefore=6, spaceAfter=4)
    st_td = ParagraphStyle("td", fontSize=8.5, leading=11, **base)
    st_th = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=C["claro"])
    st_al_t = ParagraphStyle("at", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=C["oscuro"])

    story = []
    en_meta = sum(motor.estado(kp, k[kp], cfg[kp])[0] == "verde" for kp in motor.ORDEN_KPIS)
    story.append(Paragraph(rich(
        f"En {mes_label}, {marca['cliente']} atendió en **{motor.fmt('tiempo', k['tiempo'], cfg)}** en promedio, "
        f"**{motor.fmt('satisfaccion', k['satisfaccion'], cfg)}** de los clientes salió satisfecho y las ventas "
        f"crecieron **{motor.fmt('ventas', k['ventas'], cfg)}** contra el año anterior. "
        f"**{en_meta} de 7** indicadores están en meta."), st_body))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Los 7 indicadores", st_h))
    filas = [[Paragraph(x, st_th) for x in ["Indicador", "Este mes", "Mes anterior", "Meta", "Estado"]]]
    color_estado = {"verde": C["verde"], "amarillo": C["amarillo"], "rojo": C["rojo"], "gris": C["gris"]}
    estilos = []
    for i, kp in enumerate(motor.ORDEN_KPIS, start=1):
        e, txt = motor.estado(kp, k[kp], cfg[kp])
        meta = motor.fmt(kp, cfg[kp]["meta"], cfg[kp]) if kp != "ventas" else f"+{cfg[kp]['meta']}% o más"
        filas.append([Paragraph(clean_text(cfg[kp]["nombre"]), st_td), motor.fmt(kp, k[kp], cfg[kp]),
                      motor.fmt(kp, kprev.get(kp), cfg[kp]), clean_text(meta), clean_text(txt)])
        estilos.append(("TEXTCOLOR", (4, i), (4, i), color_estado[e]))
    t = Table(filas, colWidths=[62 * mm, 28 * mm, 28 * mm, 30 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C["oscuro"]), ("FONTNAME", (1, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (1, 1), (-1, -1), 9), ("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C["tarjeta"], C["claro"]]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, C["linea"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ] + estilos))
    story.append(t)

    story.append(Paragraph("Sucursales: las que mejor van y las que más apoyo necesitan", st_h))
    top, bottom = T.head(3), T.tail(3).iloc[::-1]
    f2 = [[Paragraph(x, st_th) for x in ["Mejor desempeño", "En meta", "Necesitan apoyo", "En meta"]]]
    for (_, a), (_, b) in zip(top.iterrows(), bottom.iterrows()):
        f2.append([clean_text(a["Sucursal"]), f"{int(a['en_meta'])} de 7", clean_text(b["Sucursal"]), f"{int(b['en_meta'])} de 7"])
    t2 = Table(f2, colWidths=[55 * mm, 24 * mm, 55 * mm, 24 * mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C["oscuro"]), ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (1, -1), C["verde"]), ("TEXTCOLOR", (2, 1), (3, -1), C["rojo"]),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica-Bold"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, C["linea"]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t2)

    story.append(Paragraph("Qué atender primero", st_h))
    etiqueta = {"🔴": "URGENTE", "🟠": "IMPORTANTE", "🟢": "BIEN"}
    for prio, titulo, texto in alertas[:3]:
        story.append(Paragraph(clean_text(f"{etiqueta[motor.nivel(prio)]} · {titulo}"), st_al_t))
        story.append(Paragraph(clean_text(texto), st_body))
        story.append(Spacer(1, 5))

    doc.build(story, onFirstPage=banda, onLaterPages=banda)
    return buf.getvalue()
