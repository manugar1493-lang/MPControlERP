"""
pdf_export.py — FactuPro · Generador de PDFs
Requiere: pip install reportlab pillow

Exporta:
  generar_pdf_factura(data)    → bytes
  generar_pdf_cotizacion(data) → bytes
  generar_pdf_orden(data)      → bytes
"""

from io import BytesIO
import uuid

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table,
        TableStyle, HRFlowable, Image as RLImage,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# DIMENSIONES
# letter = 612 x 792 pt | márgenes 15 mm ≈ 42.5 pt c/lado
# ancho útil = 612 - 85 = 527 pt
# ─────────────────────────────────────────────────────────────────────────────
LM = RM = 15 * mm
TM = BM = 15 * mm
UW = 527          # ancho útil en puntos

# Cabecera: empresa (izq) | título documento (der)
HDR_L = 300
HDR_R = UW - HDR_L          # 227

# Banda info: cliente (izq) | detalles (der)
INFO_L = 290
INFO_R = UW - INFO_L         # 237

# Columnas tabla ítems FACTURA: suma debe = UW = 527
# Código | Descripción | Cant. | Precio Unit. | ITBIS% | Total
COLS_FAC = [62, 210, 38, 90, 40, 87]

# Columnas tabla ítems COTIZACIÓN: + Desc.%  → suma = 527
# Código | Descripción | Cant. | Precio Unit. | Desc.% | ITBIS% | Total
COLS_COT = [58, 178, 35, 86, 36, 40, 94]

# Columnas tabla ítems ORDEN: Solicitado + Recibido + Pendiente → suma = 527
# Código | Descripción | Solic. | Recib. | Pend. | P.Unit | Total
COLS_OC = [58, 174, 45, 45, 45, 80, 80]

# ─────────────────────────────────────────────────────────────────────────────
# COLORES
# ─────────────────────────────────────────────────────────────────────────────
C_NAVY   = colors.HexColor('#0f1c2e')
C_ORANGE = colors.HexColor('#f97316')
C_LGRAY  = colors.HexColor('#f8fafc')
C_BORDER = colors.HexColor('#dde3ec')
C_MUTED  = colors.HexColor('#64748b')
C_GREEN  = colors.HexColor('#059669')
C_RED    = colors.HexColor('#dc2626')
C_WHITE  = colors.white
C_BLACK  = colors.HexColor('#1a2332')


# ─────────────────────────────────────────────────────────────────────────────
# ESTILOS — se crean con nombre único para evitar colisiones ReportLab
# ─────────────────────────────────────────────────────────────────────────────
def _styles():
    ss = getSampleStyleSheet()
    b  = ss['Normal']
    uid = uuid.uuid4().hex[:8]

    def S(suf, **kw):
        return ParagraphStyle(f'fp_{suf}_{uid}', parent=b, **kw)

    return dict(
        emp_name  = S('en', fontSize=16, fontName='Helvetica-Bold', textColor=C_NAVY,   leading=19),
        emp_sub   = S('es', fontSize=8,  textColor=C_MUTED,  leading=11),
        doc_title = S('dt', fontSize=28, fontName='Helvetica-Bold', textColor=C_ORANGE,
                      alignment=TA_RIGHT, leading=32),
        doc_id    = S('di', fontSize=9,  fontName='Helvetica-Bold', textColor=C_NAVY,
                      alignment=TA_RIGHT, leading=12),
        doc_sub   = S('ds', fontSize=8,  textColor=C_MUTED, alignment=TA_RIGHT, leading=11),
        section   = S('sc', fontSize=7.5, fontName='Helvetica-Bold', textColor=C_ORANGE, leading=9),
        cli_lbl   = S('cl', fontSize=7,  textColor=C_MUTED,  leading=9),
        cli_val   = S('cv', fontSize=8.5, fontName='Helvetica-Bold', textColor=C_BLACK, leading=11),
        hdr_ctr   = S('hctr', fontSize=8.5, fontName='Helvetica-Bold', textColor=C_WHITE,
                      alignment=TA_CENTER, leading=11),
        hdr_rgt   = S('hrgt', fontSize=8.5, fontName='Helvetica-Bold', textColor=C_WHITE,
                      alignment=TA_RIGHT,  leading=11),
        cell      = S('ce', fontSize=8.5, textColor=C_BLACK, leading=11),
        cell_r    = S('cr', fontSize=8.5, textColor=C_BLACK, alignment=TA_RIGHT, leading=11),
        tot_lbl   = S('tl', fontSize=8.5, textColor=C_MUTED, alignment=TA_RIGHT, leading=11),
        tot_val   = S('tv', fontSize=8.5, textColor=C_BLACK, alignment=TA_RIGHT, leading=11),
        grand_lbl = S('gl', fontSize=12,  fontName='Helvetica-Bold', textColor=C_NAVY,
                      alignment=TA_RIGHT, leading=15),
        grand_val = S('gv', fontSize=13,  fontName='Helvetica-Bold', textColor=C_ORANGE,
                      alignment=TA_RIGHT, leading=16),
        footer    = S('ft', fontSize=7,   textColor=C_MUTED, alignment=TA_CENTER, leading=10),
        notes     = S('no', fontSize=8.5, textColor=C_MUTED, leading=11),
        field_lbl = S('fl', fontSize=7,   textColor=C_MUTED, leading=9),
    )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _p(text, style):
    return Paragraph(str(text) if (text is not None and str(text).strip()) else '—', style)


def _v(val):
    if val is None or str(val).strip() in ('', 'None', 'null', 'none'):
        return '—'
    return str(val)


def _rd(val):
    try:
        return f"RD$ {float(val):,.2f}"
    except Exception:
        return '—'


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE HEADER (empresa + título documento)
# ─────────────────────────────────────────────────────────────────────────────
def _header(emp: dict, titulo: str, num_id: str,
            sub1: str, sub2: str, s: dict) -> list:
    nombre = emp.get('nombre_comercial') or emp.get('nombre') or 'Mi Empresa'
    rnc    = _v(emp.get('rnc'))
    tel    = _v(emp.get('telefono'))
    email  = emp.get('email') or ''
    dir_   = _v(emp.get('direccion'))
    web    = emp.get('sitio_web') or ''

    # Columna izquierda — logo o nombre empresa
    left_items = []
    # Intentar mostrar logo de la empresa
    logo_path = emp.get('logo_path')
    # También buscar logo.png en la carpeta static como fallback
    import sys, os
    from pathlib import Path as _Path
    _base = _Path(getattr(sys, '_MEIPASS', '')) or _Path(__file__).parent
    _logo_default = _Path(__file__).parent / 'static' / 'logo.png'

    _logo_usado = None
    if logo_path and _Path(logo_path).exists():
        _logo_usado = logo_path
    elif _logo_default.exists():
        _logo_usado = str(_logo_default)

    if _logo_usado:
        try:
            img = RLImage(_logo_usado)
            ratio = min(150 / img.imageWidth, 55 / img.imageHeight)
            img.drawWidth  = img.imageWidth  * ratio
            img.drawHeight = img.imageHeight * ratio
            left_items.append(img)
            left_items.append(Spacer(1, 4))
        except Exception:
            left_items.append(_p(nombre, s['emp_name']))
            left_items.append(Spacer(1, 3))
    else:
        left_items.append(_p(nombre, s['emp_name']))
        left_items.append(Spacer(1, 3))

    left_items.append(_p(f"RNC: {rnc}", s['emp_sub']))
    contacto = '  |  '.join(x for x in [tel, email] if x and x != '—')
    if contacto:
        left_items.append(_p(contacto, s['emp_sub']))
    if dir_ and dir_ != '—':
        left_items.append(_p(dir_, s['emp_sub']))
    if web:
        left_items.append(_p(web, s['emp_sub']))

    # Columna derecha — título
    right_items = [_p(titulo, s['doc_title'])]
    if num_id:
        right_items += [Spacer(1, 2), _p(num_id, s['doc_id'])]
    if sub1:
        right_items.append(_p(sub1, s['doc_sub']))
    if sub2:
        right_items.append(_p(sub2, s['doc_sub']))

    tbl = Table([[left_items, right_items]],
                colWidths=[HDR_L, HDR_R])
    tbl.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
    ]))
    return [tbl,
            HRFlowable(width='100%', thickness=2.5, color=C_ORANGE,
                       spaceBefore=6, spaceAfter=8)]


# ─────────────────────────────────────────────────────────────────────────────
# BANDA INFO (2 columnas label/valor)
# ─────────────────────────────────────────────────────────────────────────────
def _info_band(left_title: str, left_fields: list,
               right_title: str, right_fields: list,
               s: dict) -> Table:
    """
    left/right_fields: lista de (label, valor)
    Cada columna tiene su propio sub-Table de 2 columnas (label | valor).
    """
    def build_col(title, fields, total_w):
        lbl_w = 82
        val_w = total_w - lbl_w - 24  # 12px padding cada lado
        items = [
            _p(title, s['section']),
            Spacer(1, 5),
        ]
        for lbl, val in fields:
            row = Table(
                [[_p(lbl + ':', s['cli_lbl']),
                  _p(_v(val),   s['cli_val'])]],
                colWidths=[lbl_w, val_w]
            )
            row.setStyle(TableStyle([
                ('VALIGN',        (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING',    (0,0), (-1,-1), 1),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ('LEFTPADDING',   (0,0), (-1,-1), 0),
                ('RIGHTPADDING',  (0,0), (-1,-1), 0),
            ]))
            items.append(row)
        return items

    left_col  = build_col(left_title,  left_fields,  INFO_L)
    right_col = build_col(right_title, right_fields, INFO_R)

    band = Table([[left_col, right_col]],
                 colWidths=[INFO_L, INFO_R])
    band.setStyle(TableStyle([
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND',    (0,0), (-1,-1), C_LGRAY),
        ('BOX',           (0,0), (-1,-1), 0.5, C_BORDER),
        ('LINEBEFORE',    (1,0), (1,-1),  0.5, C_BORDER),
        ('LEFTPADDING',   (0,0), (-1,-1), 12),
        ('RIGHTPADDING',  (0,0), (-1,-1), 12),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    return band


# ─────────────────────────────────────────────────────────────────────────────
# TABLA DE ÍTEMS genérica
# ─────────────────────────────────────────────────────────────────────────────
def _items_tbl(headers: list, rows_data: list,
               col_widths: list, s: dict,
               right_cols: list = None) -> Table:
    right_cols = right_cols or []

    def hcell(text, i):
        return _p(text, s['hdr_rgt'] if i in right_cols else s['hdr_ctr'])

    def dcell(text, i):
        sty = s['cell_r'] if i in right_cols else s['cell']
        return Paragraph(str(text) if text else '—', sty)

    tbl_rows = [[hcell(h, i) for i, h in enumerate(headers)]]
    for row in rows_data:
        tbl_rows.append([dcell(c, i) for i, c in enumerate(row)])

    t = Table(tbl_rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',     (0,0),  (-1,0),  C_NAVY),
        ('LINEBELOW',      (0,0),  (-1,0),  1.5, C_NAVY),
        ('ROWBACKGROUNDS', (0,1),  (-1,-1), [C_WHITE, C_LGRAY]),
        ('LINEBELOW',      (0,1),  (-1,-2), 0.3, C_BORDER),
        ('LINEBELOW',      (0,-1), (-1,-1), 0.5, C_BORDER),
        ('TOPPADDING',     (0,0),  (-1,-1), 5),
        ('BOTTOMPADDING',  (0,0),  (-1,-1), 5),
        ('LEFTPADDING',    (0,0),  (-1,-1), 5),
        ('RIGHTPADDING',   (0,0),  (-1,-1), 5),
        ('VALIGN',         (0,0),  (-1,-1), 'MIDDLE'),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE TOTALES
# ─────────────────────────────────────────────────────────────────────────────
def _totals(rows: list, total_idx: int, s: dict,
            extra: list = None) -> Table:
    """
    rows: [(label_str, valor_str), ...]
    total_idx: índice de la fila que se resalta como TOTAL
    """
    sp_w  = UW - 240
    lbl_w = 150
    val_w = 90

    tbl_rows = []
    for lbl, val in rows:
        tbl_rows.append([
            '',
            Paragraph(lbl, s['tot_lbl']),
            Paragraph(val, s['tot_val']),
        ])

    t = Table(tbl_rows, colWidths=[sp_w, lbl_w, val_w])
    ts = [
        ('ALIGN',        (1,0),  (2,-1), 'RIGHT'),
        ('TOPPADDING',   (0,0),  (-1,-1), 3),
        ('BOTTOMPADDING',(0,0),  (-1,-1), 3),
        ('LEFTPADDING',  (0,0),  (-1,-1), 4),
        ('RIGHTPADDING', (0,0),  (-1,-1), 4),
        # Fila TOTAL
        ('FONTNAME',     (1,total_idx), (2,total_idx), 'Helvetica-Bold'),
        ('FONTSIZE',     (1,total_idx), (2,total_idx), 13),
        ('TEXTCOLOR',    (1,total_idx), (2,total_idx), C_NAVY),
        ('TEXTCOLOR',    (2,total_idx), (2,total_idx), C_ORANGE),
        ('LINEABOVE',    (1,total_idx), (2,total_idx), 0.6, C_BORDER),
        ('LINEBELOW',    (1,total_idx), (2,total_idx), 2.5, C_ORANGE),
        ('TOPPADDING',   (0,total_idx), (-1,total_idx), 5),
        ('BOTTOMPADDING',(0,total_idx), (-1,total_idx), 6),
    ]
    if extra:
        ts.extend(extra)
    t.setStyle(TableStyle(ts))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# PIE DE PÁGINA
# ─────────────────────────────────────────────────────────────────────────────
def _footer(emp: dict, s: dict) -> list:
    nombre = emp.get('nombre_comercial') or emp.get('nombre') or 'Mi Empresa'
    rnc  = _v(emp.get('rnc'))
    tel  = _v(emp.get('telefono'))
    mail = emp.get('email') or ''
    return [
        Spacer(1, 18),
        HRFlowable(width='100%', thickness=1.5, color=C_ORANGE, spaceAfter=5),
        _p(f"<b>{nombre}</b>  ·  RNC: {rnc}  ·  Tel: {tel}  ·  {mail}",
           s['footer']),
        _p("Documento generado por FactuPro  ·  Sistema de Facturación para República Dominicana",
           s['footer']),
    ]


def _new_doc(buf, title):
    return SimpleDocTemplate(buf, pagesize=letter,
                              leftMargin=LM, rightMargin=RM,
                              topMargin=TM, bottomMargin=BM,
                              title=title)


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS e-CF
# ═════════════════════════════════════════════════════════════════════════════

# Mapeo tipo NCF → descripción DGII
_NCF_NOMBRE = {
    "B01": "Crédito Fiscal",
    "B02": "Consumo",
    "B14": "Régimen Especial",
    "B15": "Gubernamental",
    "E31": "Crédito Fiscal Electrónico",
    "E32": "Consumo Electrónico",
}

# Tipos e-CF (prefijo E) vs NCF físico (prefijo B)
_TIPO_DGII_NUMERO = {
    "E31": "31", "E32": "32",
    "B01": "01", "B02": "02", "B14": "14", "B15": "15",
}

def _es_ecf(tipo_ncf: str) -> bool:
    return str(tipo_ncf or "").upper().startswith("E")

def _ncf_label(tipo_ncf: str) -> str:
    t = str(tipo_ncf or "").upper()
    nombre = _NCF_NOMBRE.get(t, "Comprobante")
    num    = _TIPO_DGII_NUMERO.get(t, "")
    if _es_ecf(t):
        return f"FACTURA DE {nombre.upper()} · TIPO {num}"
    return f"FACTURA · {nombre.upper()} · TIPO {num}"


def _estatus_color(estatus: str):
    e = str(estatus or "").upper()
    return {
        "PAGADA":   colors.HexColor("#059669"),
        "PARCIAL":  colors.HexColor("#d97706"),
        "ANULADA":  C_RED,
        "VENCIDA":  C_RED,
        "EMITIDA":  colors.HexColor("#2563eb"),
        "BORRADOR": C_MUTED,
    }.get(e, C_MUTED)


# ═════════════════════════════════════════════════════════════════════════════
# FACTURA  (formato e-CF / DGII)
# ═════════════════════════════════════════════════════════════════════════════
def generar_pdf_factura(data: dict) -> bytes:
    if not REPORTLAB_OK:
        raise RuntimeError("Instala: pip install reportlab pillow")

    fac   = data['factura']
    cli   = data['cliente']
    emp   = data['empresa']
    items = data['items']
    pagos = data.get('pagos', [])
    s     = _styles()

    tipo_ncf  = str(fac.get('tipo_ncf') or 'B02').upper()
    itbis_pct = float(emp.get('itbis_pct') or 18)
    es_ecf    = _es_ecf(tipo_ncf)
    ncf       = _v(fac.get('numero_ncf'))
    estatus   = str(fac.get('estatus') or '').upper()
    moneda    = _v(emp.get('moneda') or 'DOP')
    moneda_lbl = "DOP — Peso Dominicano" if moneda == "DOP" else moneda

    buf = BytesIO()
    doc = _new_doc(buf, f"{'e-CF' if es_ecf else 'NCF'} · {ncf}")
    st  = []

    # ── 1. CABECERA empresa + título ─────────────────────────────────────────
    st += _header(emp, 'FACTURA',
                  f"NCF: {ncf}",
                  f"Tipo: {tipo_ncf}",
                  f"Estatus: {estatus}",
                  s)

    # ── 2. BANDA e-CF (franja azul con tipo y estatus) ───────────────────────
    uid = __import__('uuid').uuid4().hex[:8]
    sty_ecf_lbl = ParagraphStyle(
        f'ecf_lbl_{uid}', parent=s['hdr_ctr'],
        fontSize=8, fontName='Helvetica-Bold',
        textColor=C_WHITE, leading=10,
    )
    sty_ecf_ncf = ParagraphStyle(
        f'ecf_ncf_{uid}', parent=s['hdr_ctr'],
        fontSize=9, fontName='Helvetica-Bold',
        textColor=C_WHITE, leading=11, alignment=TA_RIGHT,
    )
    sty_badge = ParagraphStyle(
        f'badge_{uid}', parent=s['hdr_ctr'],
        fontSize=8, fontName='Helvetica-Bold',
        textColor=C_WHITE, leading=10, alignment=TA_RIGHT,
    )

    ecf_tag  = "e-CF" if es_ecf else "NCF"
    tipo_txt = _ncf_label(tipo_ncf)
    fecha_emision = _v(fac.get('created_at') or fac.get('fecha'))

    badge_color = _estatus_color(estatus)
    # Badge de estatus como texto en celda coloreada
    badge_cell = Table([[Paragraph(estatus, sty_badge)]],
                       colWidths=[70])
    badge_cell.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), badge_color),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('ROUNDEDCORNERS',(0,0),(-1,-1), [3,3,3,3]),
    ]))

    banda_row = Table([[
        Paragraph(f"<b>{ecf_tag}</b>  {tipo_txt}", sty_ecf_lbl),
        Paragraph(f"Emitido: {fecha_emision}", sty_ecf_lbl),
        badge_cell,
    ]], colWidths=[260, 160, 107])
    banda_row.setStyle(TableStyle([
        ('BACKGROUND',    (0,0),(-1,-1), colors.HexColor('#1e3a5f')),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0),(-1,-1), 6),
        ('BOTTOMPADDING', (0,0),(-1,-1), 6),
        ('LEFTPADDING',   (0,0),(-1,-1), 8),
        ('RIGHTPADDING',  (0,0),(-1,-1), 8),
    ]))
    st.append(banda_row)
    st.append(Spacer(1, 8))

    # ── 3. BLOQUE EMPRESA + CFE (2 columnas) ─────────────────────────────────
    nombre_emp = emp.get('nombre_comercial') or emp.get('nombre') or 'Mi Empresa'
    rnc_emp    = _v(emp.get('rnc'))
    tel_emp    = _v(emp.get('telefono'))
    email_emp  = emp.get('email') or ''
    dir_emp    = _v(emp.get('direccion'))

    sty_emp_n  = s['emp_name']
    sty_sub    = s['emp_sub']
    sty_ncf_id = ParagraphStyle(f'ncfid_{uid}', parent=s['doc_id'],
                                fontSize=13, fontName='Helvetica-Bold',
                                textColor=C_NAVY, alignment=TA_CENTER, leading=15)
    sty_cfe_t  = ParagraphStyle(f'cfet_{uid}', parent=s['emp_sub'],
                                alignment=TA_CENTER, textColor=C_ORANGE,
                                fontName='Helvetica-Bold', fontSize=8, leading=10)
    sty_cfe_s  = ParagraphStyle(f'cfes_{uid}', parent=s['emp_sub'],
                                alignment=TA_CENTER, fontSize=7.5, leading=10)

    left_emp = [
        Paragraph(nombre_emp, sty_emp_n),
        Spacer(1, 3),
        Paragraph(f"RNC: {rnc_emp}", sty_sub),
        Paragraph(f"Tel: {tel_emp}  |  {email_emp}", sty_sub),
        Paragraph(dir_emp, sty_sub),
    ]

    right_cfe = [
        Paragraph("COMPROBANTE FISCAL ELECTRÓNICO" if es_ecf else "COMPROBANTE FISCAL", sty_cfe_t),
        Paragraph(_NCF_NOMBRE.get(tipo_ncf, "Factura"), sty_cfe_t),
        Spacer(1, 4),
    ]
    # Cuadro NCF
    ncf_box = Table([[Paragraph(ncf, sty_ncf_id)]], colWidths=[170])
    ncf_box.setStyle(TableStyle([
        ('BOX',           (0,0),(-1,-1), 1.5, C_NAVY),
        ('BACKGROUND',    (0,0),(-1,-1), C_LGRAY),
        ('TOPPADDING',    (0,0),(-1,-1), 6),
        ('BOTTOMPADDING', (0,0),(-1,-1), 6),
        ('LEFTPADDING',   (0,0),(-1,-1), 4),
        ('RIGHTPADDING',  (0,0),(-1,-1), 4),
    ]))
    right_cfe.append(ncf_box)
    right_cfe.append(Spacer(1, 3))
    right_cfe.append(Paragraph(f"Tipo {_TIPO_DGII_NUMERO.get(tipo_ncf,'')} · {'e-CF v1.0 DGII' if es_ecf else 'NCF DGII'}", sty_cfe_s))

    emp_cfe = Table([[left_emp, right_cfe]], colWidths=[310, 217])
    emp_cfe.setStyle(TableStyle([
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0),(-1,-1), 0),
        ('BOTTOMPADDING', (0,0),(-1,-1), 0),
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
    ]))
    st.append(emp_cfe)
    st.append(HRFlowable(width='100%', thickness=1, color=C_BORDER, spaceBefore=6, spaceAfter=6))

    # ── 4. COMPRADOR / RECEPTOR + DATOS COMPROBANTE ──────────────────────────
    st.append(_info_band(
        'COMPRADOR / RECEPTOR',
        [('RNC / Cédula', cli.get('rnc_cedula')),
         ('Razón Social', cli.get('nombre')),
         ('Teléfono',     cli.get('telefono')),
         ('Email',        cli.get('email'))],
        'DATOS DEL COMPROBANTE',
        [('Fecha Emisión',    fac.get('fecha')),
         ('Fecha Vence',      fac.get('fecha_vencimiento')),
         ('Condición Pago',   fac.get('condicion_pago')),
         ('Moneda',           moneda_lbl)],
        s))
    st.append(Spacer(1, 10))

    # ── 5. DETALLE DE PRODUCTOS Y SERVICIOS ──────────────────────────────────
    st.append(_p('DETALLE DE PRODUCTOS Y SERVICIOS', s['section']))
    st.append(Spacer(1, 4))

    # Columnas: # | Código | Descripción | Cant. | Precio Unit. | Desc. | Subtotal | ITBIS
    COLS_ECF = [20, 55, 185, 38, 72, 40, 65, 52]
    rows = []
    for idx, it in enumerate(items, 1):
        desc_pct = float(it.get('descuento_pct', 0))
        itbis_i  = float(it.get('itbis_pct', itbis_pct))
        pu       = float(it.get('precio_unitario', 0))
        cant     = float(it.get('cantidad', 0))
        subtl    = pu * cant * (1 - desc_pct / 100)
        itbis_v  = subtl * itbis_i / 100
        desc_str = f"{desc_pct:.0f}%" if desc_pct else "—"
        itbis_badge = f"RD${itbis_v:,.2f}\n{itbis_i:.0f}%"
        rows.append([
            str(idx),
            _v(it.get('producto_codigo')),
            _v(it.get('producto_desc')),
            str(it.get('cantidad', 0)),
            _rd(pu),
            desc_str,
            _rd(subtl),
            _rd(itbis_v),
        ])

    st.append(_items_tbl(
        ['#', 'Código', 'Descripción', 'Cant.', 'Precio Unit.', 'Desc.', 'Subtotal', 'ITBIS'],
        rows, COLS_ECF, s, right_cols=[0, 3, 4, 5, 6, 7]))
    st.append(Spacer(1, 8))

    # ── 6. RESUMEN DE TOTALES ────────────────────────────────────────────────
    subtotal = float(fac.get('subtotal', 0))
    itbis    = float(fac.get('itbis', 0))
    total    = float(fac.get('total', 0))
    pagado   = float(fac.get('total_pagado', 0))
    balance  = float(fac.get('balance', 0))

    tot_rows = [
        ('Subtotal gravado:', _rd(subtotal)),
        (f'ITBIS ({itbis_pct:.0f}%):', _rd(itbis)),
        ('Total Impuestos:', _rd(itbis)),
        ('TOTAL GENERAL:', _rd(total)),
    ]
    extra_ts = [
        ('FONTNAME',  (1,3),(2,3),'Helvetica-Bold'),
        ('FONTSIZE',  (1,3),(2,3), 13),
        ('TEXTCOLOR', (1,3),(2,3), C_WHITE),
        ('BACKGROUND',(0,3),(-1,3), C_NAVY),
    ]
    if pagado > 0:
        tot_rows += [('Pagado:', _rd(pagado)),
                     ('Balance:', _rd(balance))]
        bc = C_RED if balance > 0 else C_GREEN
        extra_ts += [
            ('FONTNAME',  (1,5),(2,5),'Helvetica-Bold'),
            ('TEXTCOLOR', (2,5),(2,5), bc),
        ]

    st.append(_totals(tot_rows, total_idx=3, s=s, extra=extra_ts))

    # ── 7. PAGOS REGISTRADOS ─────────────────────────────────────────────────
    if pagos:
        st += [Spacer(1, 12),
               HRFlowable(width='100%', thickness=0.5, color=C_BORDER, spaceAfter=5),
               _p('PAGOS REGISTRADOS', s['section']),
               Spacer(1, 4)]
        prows = [[_v(p.get('fecha')), _rd(p.get('monto')),
                  _v(p.get('metodo')), _v(p.get('banco')),
                  _v(p.get('referencia'))]
                 for p in pagos]
        st.append(_items_tbl(
            ['Fecha', 'Monto', 'Método', 'Banco', 'Referencia'],
            prows, [70, 90, 85, 130, 152], s, right_cols=[1]))

    # ── 8. FIRMA DIGITAL y CUFE (solo e-CF) ──────────────────────────────────
    if es_ecf:
        st.append(Spacer(1, 10))
        sty_box = ParagraphStyle(f'fdbx_{uid}', parent=s['notes'],
                                 fontSize=7.5, textColor=C_MUTED, leading=10)
        firma_txt = (
            "🔐 <b>FIRMA DIGITAL (RSA-SHA256)</b><br/>"
            "[PENDIENTE — Se genera al transmitir a DGII vía PSC autorizado]"
        )
        cufe_txt = (
            "🔑 <b>CÓDIGO DE SEGURIDAD e-CF (CUFE)</b><br/>"
            "[PENDIENTE — SHA-384 generado al enviar a DGII]"
        )
        for txt in [firma_txt, cufe_txt]:
            box = Table([[Paragraph(txt, sty_box)]], colWidths=[UW])
            box.setStyle(TableStyle([
                ('BOX',           (0,0),(-1,-1), 0.5, C_BORDER),
                ('BACKGROUND',    (0,0),(-1,-1), C_LGRAY),
                ('TOPPADDING',    (0,0),(-1,-1), 5),
                ('BOTTOMPADDING', (0,0),(-1,-1), 5),
                ('LEFTPADDING',   (0,0),(-1,-1), 8),
                ('RIGHTPADDING',  (0,0),(-1,-1), 8),
            ]))
            st.append(box)
            st.append(Spacer(1, 4))

    # ── 9. BLOQUE VERIFICACIÓN + EMISOR ──────────────────────────────────────
    st.append(Spacer(1, 8))
    sty_verify = ParagraphStyle(f'vfy_{uid}', parent=s['notes'],
                                fontSize=7.5, textColor=C_MUTED, leading=10)
    sty_norm   = ParagraphStyle(f'nrm_{uid}', parent=s['notes'],
                                fontSize=7, textColor=C_MUTED, leading=9)

    verify_txt = (
        f"<b>Verificación en línea:</b><br/>"
        f"Compruebe la autenticidad en <i>ecf.dgii.gov.do</i> · "
        f"{'e-CF' if es_ecf else 'NCF'}: <b>{ncf}</b>"
    )
    legal_txt = (
        f"Este comprobante es un {'e-CF emitido conforme a la' if es_ecf else 'NCF conforme a la'} "
        f"<b>Norma General 06-18 de la DGII</b> y el <b>Decreto 254-06</b>.<br/>"
        f"· Consérvelo por 10 años (Art. 60 Código Tributario)."
    )
    emisor_txt = (
        f"<b>Emisor Autorizado DGII:</b><br/>"
        f"RNC: {rnc_emp}<br/>"
        f"{'e-NCF' if es_ecf else 'NCF'}: {ncf}"
    )
    gen_txt = (
        f"<b>Generado por:</b><br/>"
        f"FactuPro v2.0<br/>"
        f"— Sistema de Facturación Electrónica"
    )

    ver_table = Table([
        [Paragraph(verify_txt, sty_verify),
         Paragraph(emisor_txt, sty_verify)],
        [Paragraph(legal_txt, sty_norm),
         Paragraph(gen_txt, sty_verify)],
    ], colWidths=[UW * 0.58, UW * 0.42])
    ver_table.setStyle(TableStyle([
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
    ]))
    st.append(ver_table)

    if fac.get('notas'):
        st += [Spacer(1,6), _p(f"<b>Notas:</b> {fac['notas']}", s['notes'])]

    st += _footer(emp, s)
    doc.build(st)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# COTIZACIÓN
# ═════════════════════════════════════════════════════════════════════════════
def generar_pdf_cotizacion(data: dict) -> bytes:
    if not REPORTLAB_OK:
        raise RuntimeError("Instala: pip install reportlab pillow")

    cot   = data['cotizacion']
    cli   = data['cliente']
    emp   = data['empresa']
    items = data['items']
    s     = _styles()

    itbis_pct = float(emp.get('itbis_pct') or 18)
    nombre_emp = emp.get('nombre_comercial') or emp.get('nombre') or 'Mi Empresa'

    buf = BytesIO()
    doc = _new_doc(buf, f"Cotización {cot.get('numero','')}")
    st  = []

    st += _header(emp, 'COTIZACIÓN',
                  f"No. {_v(cot.get('numero'))}",
                  f"Válida hasta: {_v(cot.get('fecha_vencimiento'))}",
                  f"Estatus: {_v(cot.get('estatus'))}",
                  s)

    st.append(_info_band(
        'COTIZACIÓN PARA',
        [('Cliente',    cli.get('nombre')),
         ('RNC/Cédula', cli.get('rnc_cedula')),
         ('Teléfono',   cli.get('telefono')),
         ('Email',      cli.get('email')),
         ('Dirección',  cli.get('direccion'))],
        'DETALLES',
        [('Fecha',       cot.get('fecha')),
         ('Vence',       cot.get('fecha_vencimiento')),
         ('Condiciones', cot.get('condiciones')),
         ('Estatus',     cot.get('estatus'))],
        s))
    st.append(Spacer(1, 10))

    # Ítems
    st.append(_p('PRODUCTOS / SERVICIOS COTIZADOS', s['section']))
    st.append(Spacer(1, 4))
    rows = [[_v(it.get('producto_codigo')),
             _v(it.get('producto_desc')),
             str(it.get('cantidad', 0)),
             _rd(it.get('precio_unitario')),
             f"{float(it.get('descuento_pct', 0)):.0f}%",
             f"{float(it.get('itbis_pct', itbis_pct)):.0f}%",
             _rd(it.get('total_linea'))]
            for it in items]

    st.append(_items_tbl(
        ['Código','Descripción','Cant.','Precio Unit.','Desc.%','ITBIS%','Total'],
        rows, COLS_COT, s, right_cols=[2,3,4,5,6]))
    st.append(Spacer(1, 8))

    subtotal  = float(cot.get('subtotal', 0))
    descuento = float(cot.get('descuento', 0))
    itbis     = float(cot.get('itbis', 0))
    total     = float(cot.get('total', 0))

    tot_rows = [('Subtotal:', _rd(subtotal))]
    if descuento > 0:
        tot_rows.append(('Descuento:', f"− {_rd(descuento)}"))
    tot_rows += [(f'ITBIS ({itbis_pct:.0f}%):', _rd(itbis)),
                 ('TOTAL:', _rd(total))]
    st.append(_totals(tot_rows, total_idx=len(tot_rows)-1, s=s))

    if cot.get('condiciones'):
        st += [Spacer(1,10), _p(f"<b>Condiciones:</b> {cot['condiciones']}", s['notes'])]
    if cot.get('notas'):
        st += [Spacer(1,4), _p(f"<b>Notas:</b> {cot['notas']}", s['notes'])]

    # Líneas de firma
    st.append(Spacer(1, 28))
    fw = (UW - 40) // 2
    firma = Table([[' ' * 50, '  ', ' ' * 50]],
                  colWidths=[fw, 40, fw])
    firma.setStyle(TableStyle([
        ('LINEABOVE',    (0,0),(0,0), 0.5, C_MUTED),
        ('LINEABOVE',    (2,0),(2,0), 0.5, C_MUTED),
        ('TOPPADDING',   (0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    st.append(firma)
    st.append(Spacer(1,4))
    st.append(Table(
        [[_p(nombre_emp, s['field_lbl']), '', _p('Firma del cliente', s['field_lbl'])]],
        colWidths=[fw, 40, fw]
    ))

    st += _footer(emp, s)
    doc.build(st)
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════════════════
# ORDEN DE COMPRA
# ═════════════════════════════════════════════════════════════════════════════
def generar_pdf_orden(data: dict) -> bytes:
    if not REPORTLAB_OK:
        raise RuntimeError("Instala: pip install reportlab pillow")

    oc    = data['orden']
    prov  = data['proveedor']
    emp   = data['empresa']
    items = data['items']
    s     = _styles()

    itbis_pct  = float(emp.get('itbis_pct') or 18)
    nombre_emp = emp.get('nombre_comercial') or emp.get('nombre') or 'Mi Empresa'

    buf = BytesIO()
    doc = _new_doc(buf, f"Orden de Compra {oc.get('numero','')}")
    st  = []

    st += _header(emp, 'ORDEN DE COMPRA',
                  f"No. {_v(oc.get('numero'))}",
                  f"Fecha: {_v(oc.get('fecha'))}",
                  f"Estatus: {_v(oc.get('estatus'))}",
                  s)

    st.append(_info_band(
        'PROVEEDOR',
        [('Nombre',    prov.get('nombre')),
         ('RNC',       prov.get('rnc')),
         ('Contacto',  prov.get('contacto')),
         ('Teléfono',  prov.get('telefono')),
         ('Email',     prov.get('email'))],
        'DETALLES DE ORDEN',
        [('Fecha',        oc.get('fecha')),
         ('Entrega est.', oc.get('fecha_entrega_est')),
         ('Días de pago', f"{prov.get('dias_pago', 30)} días"),
         ('Estatus',      oc.get('estatus'))],
        s))
    st.append(Spacer(1, 10))

    st.append(_p('PRODUCTOS SOLICITADOS', s['section']))
    st.append(Spacer(1, 4))

    rows = []
    for it in items:
        sol  = float(it.get('cantidad_solicitada', 0))
        rec  = float(it.get('cantidad_recibida', 0))
        pend = sol - rec
        rows.append([
            _v(it.get('producto_codigo')),
            _v(it.get('producto_desc')),
            str(int(sol)),
            str(int(rec)),
            str(int(pend)),
            _rd(it.get('precio_unitario')),
            _rd(it.get('total_linea')),
        ])

    st.append(_items_tbl(
        ['Código','Descripción','Solic.','Recib.','Pend.','Precio Unit.','Total'],
        rows, COLS_OC, s, right_cols=[2,3,4,5,6]))
    st.append(Spacer(1, 8))

    subtotal = float(oc.get('subtotal', 0))
    itbis    = float(oc.get('itbis', 0))
    total    = float(oc.get('total', 0))
    st.append(_totals([
        ('Subtotal:', _rd(subtotal)),
        (f'ITBIS ({itbis_pct:.0f}%):', _rd(itbis)),
        ('TOTAL:', _rd(total)),
    ], total_idx=2, s=s))

    if oc.get('notas'):
        st += [Spacer(1,8), _p(f"<b>Notas:</b> {oc['notas']}", s['notes'])]

    # Firmas de aprobación
    st.append(Spacer(1, 26))
    fw3 = (UW - 60) // 3
    aprov = Table([[' '*35, '  ', ' '*35, '  ', ' '*35]],
                  colWidths=[fw3, 30, fw3, 30, fw3])
    aprov.setStyle(TableStyle([
        ('LINEABOVE',    (0,0),(0,0), 0.5, C_MUTED),
        ('LINEABOVE',    (2,0),(2,0), 0.5, C_MUTED),
        ('LINEABOVE',    (4,0),(4,0), 0.5, C_MUTED),
        ('TOPPADDING',   (0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    st.append(aprov)
    st.append(Spacer(1,4))
    st.append(Table(
        [[_p('Elaborado por', s['field_lbl']), '',
          _p('Autorizado por', s['field_lbl']), '',
          _p('Recibido por', s['field_lbl'])]],
        colWidths=[fw3, 30, fw3, 30, fw3]
    ))

    st += _footer(emp, s)
    doc.build(st)
    return buf.getvalue()
