"""
main.py — FactuPro v2.0
FastAPI + SQLAlchemy — ERP Multi-empresa para RD
Fixes: lifespan en vez de on_event, host 127.0.0.1, puerto 8765
"""

import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header, Body
from fastapi.responses import StreamingResponse
from io import BytesIO
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, timedelta, datetime
from pathlib import Path

# ── Módulos propios ───────────────────────────────────────────────────────────
try:
    from pdf_export import (
        generar_pdf_factura, generar_pdf_cotizacion,
        generar_pdf_orden, REPORTLAB_OK
    )
except ImportError:
    REPORTLAB_OK = False
    def generar_pdf_factura(d):    raise RuntimeError("pip install reportlab pillow")
    def generar_pdf_cotizacion(d): raise RuntimeError("pip install reportlab pillow")
    def generar_pdf_orden(d):      raise RuntimeError("pip install reportlab pillow")

try:
    from excel_export import (
        exportar_contabilidad, exportar_606, exportar_607,
        exportar_reporte_ventas, OPENPYXL_OK
    )
except ImportError:
    OPENPYXL_OK = False
    def exportar_contabilidad(*a, **k): raise RuntimeError("pip install openpyxl")
    def exportar_606(*a, **k):          raise RuntimeError("pip install openpyxl")
    def exportar_607(*a, **k):          raise RuntimeError("pip install openpyxl")
    def exportar_reporte_ventas(*a, **k): raise RuntimeError("pip install openpyxl")

# Licencia — opcional, no bloquea el arranque del servidor
try:
    from licencia import verificar_licencia, ResultadoLicencia
    LICENCIA_OK = True
except ImportError:
    LICENCIA_OK = False
from auth import (
    get_current_user, admin_only, admin_supervisor,
    login_handler, perfil_handler, cambiar_password_handler,
    crear_usuario_handler, listar_usuarios_handler,
    seed_admin, LoginSchema, UsuarioCreateSchema, CambiarPasswordSchema,
)
import nomina as nom_module
import bancos as banco_module

from models import (
    Base, Empresa, Cliente, Proveedor, Producto, Categoria,
    Cotizacion, CotizacionItem, Factura, FacturaItem, Pago,
    OrdenCompra, OrdenCompraItem, MovimientoInventario, Transaccion,
    RecepcionCompra, RecepcionItem, Usuario,
    Empleado, Nomina, NominaDetalle,
    CuentaBancaria, MovimientoBanco, Conciliacion,
    TssPeriodo, TssAporte, ClienteDocumento, gen_uuid
)

# ── Rutas base ────────────────────────────────────────────────────────────────
# ── Resolución de rutas compatible con PyInstaller onefile ──────────────────
def _get_resource_dir() -> Path:
    """Directorio donde están los archivos empaquetados (static, módulos)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()

def _get_data_dir() -> Path:
    """Directorio persistente junto al .exe (BD, licencia, uploads)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()

BASE_DIR     = _get_data_dir()      # Datos persistentes
RESOURCE_DIR = _get_resource_dir()  # Archivos empaquetados

# ── Copiar static/ desde _MEIPASS a carpeta permanente junto al .exe ──────────
# Esto garantiza que FastAPI pueda servir los archivos estáticos correctamente
# incluso cuando el .exe se ejecuta desde el acceso directo del instalador.
def _ensure_static():
    """
    En modo onefile, copia static/ desde _MEIPASS al directorio del .exe
    si no existe ya. Así FastAPI siempre sirve desde una ruta fija.
    """
    src  = RESOURCE_DIR / "static"
    dest = BASE_DIR / "static"
    if not src.exists():
        return dest
    if not dest.exists() or not (dest / "index.html").exists():
        import shutil
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(str(src), str(dest))
        except Exception as e:
            print(f"[FactuPro] No se pudo copiar static/: {e}")
    return dest

STATIC_SERVE_DIR = _ensure_static()

UPLOAD_DIR = BASE_DIR / "uploads" / "logos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Base de datos ─────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'factupro.db'}")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _eid(user: dict) -> str:
    """Extrae empresa_id del token JWT."""
    return user["empresa_id"]


# ── Lifespan (reemplaza on_event, sin deprecation warning) ───────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    with SessionLocal() as db:
        if not db.query(Empresa).first():
            emp = Empresa(
                id=gen_uuid(), nombre="Mi Empresa",
                rnc="000000000", telefono="(809) 000-0000",
                email="info@miempresa.com"
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
            seed_admin(db, emp.id)
        else:
            emp = db.query(Empresa).first()
            if db.query(Usuario).filter_by(empresa_id=emp.id).count() == 0:
                seed_admin(db, emp.id)
    yield
    # Shutdown (aquí se puede cerrar conexiones, etc.)


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FactuPro API v2.0",
    version="2.0.0",
    description="ERP Multi-empresa · República Dominicana",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = STATIC_SERVE_DIR
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

uploads_root = BASE_DIR / "uploads"
uploads_root.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_root)), name="uploads")


# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/api/licencia")
def get_licencia():
    """Estado actual de la licencia."""
    try:
        from licencia import verificar_licencia
        return verificar_licencia(BASE_DIR)
    except Exception as e:
        return {"estado": "VALIDA", "dias_restantes": 30, "mensaje": "OK"}

@app.get("/", response_class=HTMLResponse)
def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>FactuPro API v2.0 — OK</h1>")


# ════════════════════════════════════════════════════════════════════════════
# SCHEMAS PYDANTIC
# ════════════════════════════════════════════════════════════════════════════

class EmpresaSchema(BaseModel):
    nombre:           str
    nombre_comercial: Optional[str] = None
    rnc:              Optional[str] = None
    direccion:        Optional[str] = None
    telefono:         Optional[str] = None
    email:            Optional[str] = None
    sitio_web:        Optional[str] = None
    moneda:           str   = "RD$"
    itbis_pct:        float = 18.0
    ncf_prefix:       str   = "B02"

class ClienteSchema(BaseModel):
    nombre:         str
    tipo:           str   = "FINAL"
    rnc_cedula:     Optional[str] = None
    telefono:       Optional[str] = None
    email:          Optional[str] = None
    direccion:      Optional[str] = None
    limite_credito: float = 0.0
    dias_credito:   int   = 0
    notas:          Optional[str] = None
    activo:         bool  = True

class ProveedorSchema(BaseModel):
    nombre:    str
    rnc:       Optional[str] = None
    contacto:  Optional[str] = None
    telefono:  Optional[str] = None
    email:     Optional[str] = None
    direccion: Optional[str] = None
    dias_pago: int = 30
    notas:     Optional[str] = None

class ProductoSchema(BaseModel):
    codigo:       str
    descripcion:  str
    marca:        Optional[str] = None
    unidad:       str   = "UND"
    categoria_id: Optional[str] = None
    precio_venta: float
    precio_costo: float = 0.0
    itbis_pct:    float = 18.0
    stock_actual: int   = 0
    stock_minimo: int   = 0
    ubicacion:    Optional[str] = None
    notas:        Optional[str] = None

class ItemSchema(BaseModel):
    producto_id:       Optional[str] = None
    descripcion_libre: Optional[str] = None
    cantidad:          float
    precio_unitario:   float
    descuento_pct:     float = 0.0
    itbis_pct:         float = 18.0

class CotizacionSchema(BaseModel):
    cliente_id:        str
    numero:            Optional[str] = None
    fecha:             Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    condiciones:       Optional[str] = None
    notas:             Optional[str] = None
    items:             List[ItemSchema]

class FacturaSchema(BaseModel):
    cliente_id:     str
    cotizacion_id:  Optional[str] = None
    numero_ncf:     Optional[str] = None
    tipo_ncf:       str = "B02"
    fecha:          Optional[str] = None
    condicion_pago: str = "CONTADO"
    notas:          Optional[str] = None
    items:          List[ItemSchema]

class PagoSchema(BaseModel):
    factura_id: str
    monto:      float
    metodo:     str = "EFECTIVO"
    banco:      Optional[str] = None
    referencia: Optional[str] = None
    fecha:      Optional[str] = None
    notas:      Optional[str] = None

class OrdenCompraSchema(BaseModel):
    proveedor_id:      str
    numero:            Optional[str] = None
    fecha:             Optional[str] = None
    fecha_entrega_est: Optional[str] = None
    notas:             Optional[str] = None
    items:             List[ItemSchema]

class TransaccionSchema(BaseModel):
    tipo:        str
    categoria:   Optional[str] = None
    descripcion: str
    monto:       float
    fecha:       Optional[str] = None
    metodo:      str = "EFECTIVO"
    referencia:  Optional[str] = None
    notas:       Optional[str] = None

class CategoriaSchema(BaseModel):
    nombre:      str
    descripcion: Optional[str] = None

class AjusteInventarioSchema(BaseModel):
    producto_id:    str
    tipo:           str   # ENTRADA / SALIDA / AJUSTE
    cantidad:       float
    costo_unitario: float = 0.0
    notas:          Optional[str] = None


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def calcular_items(items_data: List[ItemSchema]):
    subtotal = descuento = itbis = 0.0
    for it in items_data:
        base = it.cantidad * it.precio_unitario
        desc = base * (it.descuento_pct / 100)
        sub  = base - desc
        # Solo calcular impuesto si itbis_pct > 0
        tax  = sub  * (it.itbis_pct  / 100) if it.itbis_pct > 0 else 0.0
        subtotal  += sub
        descuento += desc
        itbis     += tax
    return subtotal, descuento, itbis, subtotal + itbis


def next_ncf(db: Session, empresa_id: str) -> str:
    empresa = db.query(Empresa).get(empresa_id)
    if not empresa:
        return "B02000000001"
    seq = empresa.ncf_sequence or 1
    ncf = f"{empresa.ncf_prefix}{seq:08d}"
    empresa.ncf_sequence = seq + 1
    db.commit()
    return ncf


def next_num(db: Session, prefix: str, model, empresa_id: str) -> str:
    cnt = db.query(func.count(model.id)).filter_by(empresa_id=empresa_id).scalar() or 0
    return f"{prefix}{cnt+1:04d}"


def serialize(obj):
    if obj is None:
        return {}
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, (date, datetime)):
            d[col.name] = str(val)
        elif isinstance(val, float):
            d[col.name] = round(val, 2)
        else:
            d[col.name] = val
    return d


# ════════════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):
    return login_handler(data, db)

@app.get("/api/auth/perfil")
def perfil(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return perfil_handler(user, db)

@app.put("/api/auth/password")
def cambiar_password(data: CambiarPasswordSchema,
                     user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return cambiar_password_handler(data, user, db)

@app.get("/api/auth/usuarios")
def listar_usuarios(user=Depends(admin_only), db: Session = Depends(get_db)):
    return listar_usuarios_handler(user, db)

@app.post("/api/auth/usuarios", status_code=201)
def crear_usuario(data: UsuarioCreateSchema,
                  user=Depends(admin_only),
                  db: Session = Depends(get_db)):
    return crear_usuario_handler(data, user, db)

@app.put("/api/auth/usuarios/{uid}/activo")
def toggle_usuario(uid: str, activo: bool,
                   user=Depends(admin_only),
                   db: Session = Depends(get_db)):
    u = db.query(Usuario).filter_by(id=uid, empresa_id=_eid(user)).first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    u.activo = activo
    db.commit()
    return {"ok": True, "activo": activo}


# ════════════════════════════════════════════════════════════════════════════
# EMPRESA
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/empresa")
def get_empresa(user=Depends(get_current_user), db: Session = Depends(get_db)):
    e = db.query(Empresa).get(_eid(user))
    if not e:
        raise HTTPException(404, "Empresa no configurada")
    return serialize(e)

@app.put("/api/empresa")
def update_empresa(data: EmpresaSchema,
                   user=Depends(admin_only),
                   db: Session = Depends(get_db)):
    e = db.query(Empresa).get(_eid(user))
    if not e:
        raise HTTPException(404)
    for k, v in data.dict(exclude_none=True).items():
        setattr(e, k, v)
    db.commit()
    return {"ok": True}

@app.post("/api/empresa/logo")
async def upload_logo(file: UploadFile = File(...),
                      user=Depends(admin_only),
                      db: Session = Depends(get_db)):
    if file.content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(400, "Solo PNG o JPG")
    contenido = await file.read()
    if len(contenido) > 2 * 1024 * 1024:
        raise HTTPException(400, "El archivo supera los 2 MB")
    ext      = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{_eid(user)}.{ext}"
    path     = UPLOAD_DIR / filename
    path.write_bytes(contenido)
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(contenido))
        img.thumbnail((400, 200))
        img.save(str(path))
    except Exception:
        pass
    e = db.query(Empresa).get(_eid(user))
    e.logo_path = str(path)
    db.commit()
    return {"ok": True, "logo_url": f"/uploads/logos/{filename}"}


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
def dashboard(user=Depends(get_current_user), db: Session = Depends(get_db)):
    eid = _eid(user)
    hoy = date.today()
    mes_inicio = hoy.replace(day=1)

    total_clientes  = db.query(func.count(Cliente.id)).filter_by(empresa_id=eid).scalar() or 0
    total_productos = db.query(func.count(Producto.id)).filter_by(empresa_id=eid).scalar() or 0
    total_facturas  = db.query(func.count(Factura.id)).filter_by(empresa_id=eid).scalar() or 0
    cobrado_total   = db.query(func.sum(Pago.monto)).filter_by(empresa_id=eid).scalar() or 0
    cobrado_mes     = db.query(func.sum(Pago.monto)).filter(
                        Pago.empresa_id==eid, Pago.fecha>=mes_inicio).scalar() or 0
    cobrado_hoy     = db.query(func.sum(Pago.monto)).filter(
                        Pago.empresa_id==eid, Pago.fecha==hoy).scalar() or 0
    pendiente       = db.query(func.sum(Factura.balance)).filter(
                        Factura.empresa_id==eid,
                        Factura.estatus.in_(["EMITIDA","PARCIAL"])).scalar() or 0
    bajo_stock      = db.query(func.count(Producto.id)).filter(
                        Producto.empresa_id==eid,
                        Producto.stock_actual<=Producto.stock_minimo,
                        Producto.stock_minimo>0).scalar() or 0

    facturas_recientes = []
    for f, c in (db.query(Factura, Cliente).join(Cliente)
                 .filter(Factura.empresa_id==eid)
                 .order_by(Factura.created_at.desc()).limit(8).all()):
        facturas_recientes.append({
            "id": f.id, "ncf": f.numero_ncf or "—", "cliente": c.nombre[:28],
            "fecha": str(f.fecha), "total": float(f.total),
            "balance": float(f.balance), "estatus": f.estatus
        })

    ventas_mes = []
    for i in range(5, -1, -1):
        d      = hoy.replace(day=1) - timedelta(days=i*28)
        inicio = d.replace(day=1)
        fin_mes = (inicio + timedelta(days=32)).replace(day=1)
        total  = db.query(func.sum(Factura.total)).filter(
            Factura.empresa_id==eid,
            Factura.fecha>=inicio, Factura.fecha<fin_mes,
            Factura.estatus!="ANULADA").scalar() or 0
        ventas_mes.append({"mes": inicio.strftime("%b %y"), "total": float(total)})

    productos_alerta = []
    for p in db.query(Producto).filter(
        Producto.empresa_id==eid,
        Producto.stock_actual<=Producto.stock_minimo,
        Producto.stock_minimo>0).limit(5).all():
        productos_alerta.append({
            "codigo": p.codigo, "descripcion": p.descripcion[:35],
            "stock_actual": p.stock_actual, "stock_minimo": p.stock_minimo
        })

    return {
        "kpis": {
            "clientes": total_clientes, "productos": total_productos,
            "facturas": total_facturas, "cobrado_total": float(cobrado_total),
            "cobrado_mes": float(cobrado_mes), "cobrado_hoy": float(cobrado_hoy),
            "pendiente": float(pendiente), "bajo_stock": bajo_stock
        },
        "facturas_recientes": facturas_recientes,
        "ventas_mes": ventas_mes,
        "productos_alerta": productos_alerta
    }


# ════════════════════════════════════════════════════════════════════════════
# CLIENTES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/clientes")
def list_clientes(q: Optional[str]=None, activo: Optional[bool]=None,
                  user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(Cliente).filter_by(empresa_id=eid)
    if q:
        query = query.filter(or_(Cliente.nombre.ilike(f"%{q}%"),
                                  Cliente.rnc_cedula.ilike(f"%{q}%")))
    if activo is not None:
        query = query.filter(Cliente.activo==activo)
    return [serialize(c) for c in query.order_by(Cliente.nombre).all()]

@app.post("/api/clientes", status_code=201)
def create_cliente(data: ClienteSchema, user=Depends(get_current_user),
                   db: Session=Depends(get_db)):
    c = Cliente(id=gen_uuid(), empresa_id=_eid(user), **data.dict())
    db.add(c); db.commit(); return serialize(c)

@app.get("/api/clientes/{cid}")
def get_cliente(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    c = db.query(Cliente).filter_by(id=cid, empresa_id=_eid(user)).first()
    if not c: raise HTTPException(404, "Cliente no encontrado")
    return serialize(c)

@app.put("/api/clientes/{cid}")
def update_cliente(cid: str, data: ClienteSchema, user=Depends(get_current_user),
                   db: Session=Depends(get_db)):
    c = db.query(Cliente).filter_by(id=cid, empresa_id=_eid(user)).first()
    if not c: raise HTTPException(404)
    for k, v in data.dict().items(): setattr(c, k, v)
    db.commit(); return serialize(c)

@app.delete("/api/clientes/{cid}")
def delete_cliente(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    c = db.query(Cliente).filter_by(id=cid, empresa_id=_eid(user)).first()
    if not c: raise HTTPException(404)
    c.activo = False; db.commit(); return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS DE CLIENTE (PDFs adjuntos)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/clientes/{cid}/documentos", status_code=201)
async def upload_cliente_documentos(
    cid: str,
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adjuntar uno o varios PDFs a un cliente. Contenido guardado en la BD."""
    eid = _eid(user)
    cliente = db.query(Cliente).filter_by(id=cid, empresa_id=eid).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")

    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    subidos = []
    for file in files:
        if file.content_type not in ("application/pdf", "application/octet-stream"):
            # Aceptar también octet-stream por si el browser no detecta bien el MIME
            ext = (file.filename or "").rsplit(".", 1)[-1].lower()
            if ext != "pdf":
                raise HTTPException(400, f"'{file.filename}' no es un PDF.")

        contenido = await file.read()
        if len(contenido) > MAX_SIZE:
            raise HTTPException(400, f"'{file.filename}' supera los 10 MB.")

        doc = ClienteDocumento(
            id=gen_uuid(),
            empresa_id=eid,
            cliente_id=cid,
            nombre_archivo=file.filename or "documento.pdf",
            tamano_kb=round(len(contenido) / 1024),
            contenido=contenido,
        )
        db.add(doc)
        subidos.append({"nombre_archivo": doc.nombre_archivo, "tamano_kb": doc.tamano_kb})

    db.commit()
    return {"ok": True, "subidos": len(subidos), "archivos": subidos}


@app.get("/api/clientes/{cid}/documentos")
def list_cliente_documentos(
    cid: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lista los documentos adjuntos de un cliente (sin el contenido binario)."""
    eid = _eid(user)
    cliente = db.query(Cliente).filter_by(id=cid, empresa_id=eid).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")

    docs = (db.query(ClienteDocumento)
              .filter_by(cliente_id=cid, empresa_id=eid)
              .order_by(ClienteDocumento.created_at)
              .all())
    return [
        {
            "id":             d.id,
            "nombre_archivo": d.nombre_archivo,
            "tamano_kb":      d.tamano_kb,
            "created_at":     str(d.created_at),
        }
        for d in docs
    ]


@app.get("/api/clientes/documentos/{doc_id}/descargar")
def descargar_documento_cliente(
    doc_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Descarga / visualiza un PDF adjunto."""
    eid = _eid(user)
    doc = db.query(ClienteDocumento).filter_by(id=doc_id, empresa_id=eid).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")

    nombre_safe = doc.nombre_archivo.replace('"', '_')
    return Response(
        content=doc.contenido,
        media_type="application/pdf",
        headers={
            # inline = el browser lo muestra; attachment = lo descarga
            "Content-Disposition": f'inline; filename="{nombre_safe}"'
        },
    )


@app.delete("/api/clientes/documentos/{doc_id}")
def eliminar_documento_cliente(
    doc_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Elimina un documento adjunto."""
    eid = _eid(user)
    doc = db.query(ClienteDocumento).filter_by(id=doc_id, empresa_id=eid).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    db.delete(doc)
    db.commit()
    return {"ok": True, "eliminado": doc_id}


# ════════════════════════════════════════════════════════════════════════════
# PROVEEDORES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/proveedores")
def list_proveedores(q: Optional[str]=None, user=Depends(get_current_user),
                     db: Session=Depends(get_db)):
    query = db.query(Proveedor).filter_by(empresa_id=_eid(user))
    if q: query = query.filter(Proveedor.nombre.ilike(f"%{q}%"))
    return [serialize(p) for p in query.order_by(Proveedor.nombre).all()]

@app.post("/api/proveedores", status_code=201)
def create_proveedor(data: ProveedorSchema, user=Depends(get_current_user),
                     db: Session=Depends(get_db)):
    p = Proveedor(id=gen_uuid(), empresa_id=_eid(user), **data.dict())
    db.add(p); db.commit(); return serialize(p)

@app.get("/api/proveedores/{pid}")
def get_proveedor(pid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    p = db.query(Proveedor).filter_by(id=pid, empresa_id=_eid(user)).first()
    if not p: raise HTTPException(404)
    return serialize(p)

@app.put("/api/proveedores/{pid}")
def update_proveedor(pid: str, data: ProveedorSchema, user=Depends(get_current_user),
                     db: Session=Depends(get_db)):
    p = db.query(Proveedor).filter_by(id=pid, empresa_id=_eid(user)).first()
    if not p: raise HTTPException(404)
    for k, v in data.dict().items(): setattr(p, k, v)
    db.commit(); return serialize(p)

@app.delete("/api/proveedores/{pid}")
def delete_proveedor(pid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    p = db.query(Proveedor).filter_by(id=pid, empresa_id=_eid(user)).first()
    if not p: raise HTTPException(404)
    p.activo = False; db.commit(); return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# CATEGORÍAS & PRODUCTOS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/categorias")
def list_categorias(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return [serialize(c) for c in
            db.query(Categoria).filter_by(empresa_id=_eid(user))
            .order_by(Categoria.nombre).all()]

@app.post("/api/categorias", status_code=201)
def create_categoria(data: CategoriaSchema, user=Depends(get_current_user),
                     db: Session=Depends(get_db)):
    c = Categoria(id=gen_uuid(), empresa_id=_eid(user), **data.dict())
    db.add(c); db.commit(); return serialize(c)

@app.get("/api/productos")
def list_productos(q: Optional[str]=None, bajo_stock: bool=False,
                   user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(Producto).filter_by(empresa_id=eid, activo=True)
    if q:
        query = query.filter(or_(Producto.codigo.ilike(f"%{q}%"),
                                  Producto.descripcion.ilike(f"%{q}%")))
    if bajo_stock:
        query = query.filter(Producto.stock_actual<=Producto.stock_minimo,
                              Producto.stock_minimo>0)
    return [serialize(p) for p in query.order_by(Producto.codigo).all()]

@app.post("/api/productos", status_code=201)
def create_producto(data: ProductoSchema, user=Depends(get_current_user),
                    db: Session=Depends(get_db)):
    eid = _eid(user)
    if db.query(Producto).filter_by(empresa_id=eid, codigo=data.codigo).first():
        raise HTTPException(400, f"Código '{data.codigo}' ya existe")
    p = Producto(id=gen_uuid(), empresa_id=eid, **data.dict())
    db.add(p); db.commit(); return serialize(p)

@app.get("/api/productos/{pid}")
def get_producto(pid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    p = db.query(Producto).filter_by(id=pid, empresa_id=_eid(user)).first()
    if not p: raise HTTPException(404)
    return serialize(p)

@app.put("/api/productos/{pid}")
def update_producto(pid: str, data: ProductoSchema, user=Depends(get_current_user),
                    db: Session=Depends(get_db)):
    eid = _eid(user)
    p = db.query(Producto).filter_by(id=pid, empresa_id=eid).first()
    if not p: raise HTTPException(404)
    if db.query(Producto).filter(Producto.empresa_id==eid,
                                  Producto.codigo==data.codigo,
                                  Producto.id!=pid).first():
        raise HTTPException(400, "Código duplicado")
    for k, v in data.dict().items(): setattr(p, k, v)
    db.commit(); return serialize(p)

@app.delete("/api/productos/{pid}")
def delete_producto(pid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    p = db.query(Producto).filter_by(id=pid, empresa_id=_eid(user)).first()
    if not p: raise HTTPException(404)
    p.activo = False; db.commit(); return {"ok": True}

@app.post("/api/productos/ajuste-inventario")
def ajuste_inventario(data: AjusteInventarioSchema, user=Depends(get_current_user),
                      db: Session=Depends(get_db)):
    eid = _eid(user)
    p = db.query(Producto).filter_by(id=data.producto_id, empresa_id=eid).first()
    if not p: raise HTTPException(404)
    if data.tipo == "ENTRADA":
        p.stock_actual += int(data.cantidad)
    elif data.tipo == "SALIDA":
        p.stock_actual = max(0, p.stock_actual - int(data.cantidad))
    else:
        p.stock_actual = int(data.cantidad)
    db.add(MovimientoInventario(
        id=gen_uuid(), empresa_id=eid, producto_id=p.id,
        tipo=data.tipo, cantidad=data.cantidad,
        costo_unitario=data.costo_unitario,
        origen_tipo="AJUSTE", notas=data.notas
    ))
    db.commit()
    return {"ok": True, "stock_actual": p.stock_actual}


# ════════════════════════════════════════════════════════════════════════════
# COTIZACIONES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/cotizaciones")
def list_cotizaciones(q: Optional[str]=None, estatus: Optional[str]=None,
                      user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(Cotizacion, Cliente).join(Cliente).filter(Cotizacion.empresa_id==eid)
    if q:
        query = query.filter(or_(Cotizacion.numero.ilike(f"%{q}%"),
                                  Cliente.nombre.ilike(f"%{q}%")))
    if estatus: query = query.filter(Cotizacion.estatus==estatus)
    result = []
    for cot, cli in query.order_by(Cotizacion.created_at.desc()).all():
        d = serialize(cot); d["cliente_nombre"] = cli.nombre; result.append(d)
    return result

@app.post("/api/cotizaciones", status_code=201)
def create_cotizacion(data: CotizacionSchema, user=Depends(get_current_user),
                      db: Session=Depends(get_db)):
    eid = _eid(user)
    numero = data.numero or next_num(db, "COT-", Cotizacion, eid)
    subtotal, descuento, itbis, total = calcular_items(data.items)
    cot = Cotizacion(
        id=gen_uuid(), empresa_id=eid, cliente_id=data.cliente_id, numero=numero,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
        fecha_vencimiento=(date.fromisoformat(data.fecha_vencimiento)
                           if data.fecha_vencimiento else date.today()+timedelta(days=15)),
        estatus="ENVIADA", condiciones=data.condiciones, notas=data.notas,
        subtotal=subtotal, descuento=descuento, itbis=itbis, total=total
    )
    db.add(cot); db.flush()
    for it in data.items:
        base = it.cantidad * it.precio_unitario * (1 - it.descuento_pct/100)
        db.add(CotizacionItem(
            id=gen_uuid(), cotizacion_id=cot.id, producto_id=it.producto_id,
            descripcion_libre=it.descripcion_libre,
            cantidad=it.cantidad, precio_unitario=it.precio_unitario,
            descuento_pct=it.descuento_pct, itbis_pct=it.itbis_pct,
            total_linea=base*(1+it.itbis_pct/100)
        ))
    db.commit(); return serialize(cot)

@app.get("/api/cotizaciones/{cid}")
def get_cotizacion(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=eid).first()
    if not cot: raise HTTPException(404)
    cli   = db.query(Cliente).get(cot.cliente_id)
    items = db.query(CotizacionItem).filter_by(cotizacion_id=cid).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    result = serialize(cot)
    result["cliente"] = serialize(cli) if cli else {}
    result["items"] = []
    for it in items:
        p = prods.get(it.producto_id)
        d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else (it.descripcion_libre or "—")
        result["items"].append(d)
    return result

@app.put("/api/cotizaciones/{cid}")
def update_cotizacion(cid: str, data: CotizacionSchema, user=Depends(get_current_user),
                      db: Session=Depends(get_db)):
    eid = _eid(user)
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=eid).first()
    if not cot: raise HTTPException(404)
    if cot.estatus not in ["BORRADOR", "ENVIADA"]:
        raise HTTPException(status_code=400, detail="Solo se pueden editar cotizaciones en BORRADOR o ENVIADA")
    
    db.query(CotizacionItem).filter_by(cotizacion_id=cid).delete()
    subtotal, descuento, itbis, total = calcular_items(data.items)
    
    cot.cliente_id = data.cliente_id
    cot.fecha_vencimiento = date.fromisoformat(data.fecha_vencimiento) if data.fecha_vencimiento else cot.fecha_vencimiento
    cot.condiciones = data.condiciones
    cot.notas = data.notas
    cot.subtotal = subtotal
    cot.descuento = descuento
    cot.itbis = itbis
    cot.total = total
    cot.updated_at = datetime.utcnow()
    db.flush()
    
    for it in data.items:
        base = it.cantidad * it.precio_unitario * (1 - it.descuento_pct/100)
        db.add(CotizacionItem(
            id=gen_uuid(), cotizacion_id=cot.id, producto_id=it.producto_id,
            descripcion_libre=it.descripcion_libre,
            cantidad=it.cantidad, precio_unitario=it.precio_unitario,
            descuento_pct=it.descuento_pct, itbis_pct=it.itbis_pct,
            total_linea=base*(1+it.itbis_pct/100)
        ))
    db.commit()
    return serialize(cot)

@app.delete("/api/cotizaciones/{cid}")
def anular_cotizacion(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=eid).first()
    if not cot: raise HTTPException(404)
    if cot.estatus == "CONVERTIDA":
        raise HTTPException(status_code=400, detail="No se puede anular una cotización convertida a factura")
    
    cot.estatus = "ANULADA"
    db.commit()
    return {"ok": True}

@app.put("/api/cotizaciones/{cid}/estatus")
def update_estatus_cotizacion(cid: str, estatus: str, user=Depends(get_current_user),
                              db: Session=Depends(get_db)):
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=_eid(user)).first()
    if not cot: raise HTTPException(404)
    cot.estatus = estatus; db.commit(); return {"ok": True}

@app.post("/api/cotizaciones/{cid}/convertir")
def convertir_cotizacion(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=eid).first()
    if not cot: raise HTTPException(404)
    items = db.query(CotizacionItem).filter_by(cotizacion_id=cid).all()
    ncf   = next_ncf(db, eid)
    fac   = Factura(
        id=gen_uuid(), empresa_id=eid, cliente_id=cot.cliente_id, cotizacion_id=cot.id,
        numero_ncf=ncf, tipo_ncf="B02", fecha=date.today(),
        fecha_vencimiento=date.today()+timedelta(days=30),
        estatus="EMITIDA", condicion_pago="CONTADO",
        subtotal=cot.subtotal, descuento=cot.descuento,
        itbis=cot.itbis, total=cot.total, balance=cot.total
    )
    db.add(fac); db.flush()
    for it in items:
        db.add(FacturaItem(
            id=gen_uuid(), factura_id=fac.id, producto_id=it.producto_id,
            descripcion_libre=it.descripcion_libre,
            cantidad=it.cantidad, precio_unitario=it.precio_unitario,
            descuento_pct=it.descuento_pct, itbis_pct=it.itbis_pct,
            total_linea=it.total_linea
        ))
        if it.producto_id:
            prod = db.query(Producto).filter_by(id=it.producto_id, empresa_id=eid).first()
            if prod:
                prod.stock_actual = max(0, prod.stock_actual - int(float(it.cantidad)))
                db.add(MovimientoInventario(
                    id=gen_uuid(), empresa_id=eid, producto_id=it.producto_id,
                    tipo="SALIDA", cantidad=it.cantidad,
                    origen_tipo="FACTURA", origen_id=fac.id
                ))
    cot.estatus = "CONVERTIDA"; db.commit()
    return {"factura_id": fac.id, "numero_ncf": fac.numero_ncf}


# ════════════════════════════════════════════════════════════════════════════
# FACTURAS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/facturas")
def list_facturas(q: Optional[str]=None, estatus: Optional[str]=None,
                  cliente_id: Optional[str]=None,
                  user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(Factura, Cliente).join(Cliente).filter(Factura.empresa_id==eid)
    if q: query = query.filter(or_(Factura.numero_ncf.ilike(f"%{q}%"),
                                    Cliente.nombre.ilike(f"%{q}%")))
    if estatus:    query = query.filter(Factura.estatus==estatus)
    if cliente_id: query = query.filter(Factura.cliente_id==cliente_id)
    result = []
    for f, c in query.order_by(Factura.created_at.desc()).all():
        d = serialize(f); d["cliente_nombre"] = c.nombre; result.append(d)
    return result

@app.post("/api/facturas", status_code=201)
def create_factura(data: FacturaSchema, user=Depends(get_current_user),
                   db: Session=Depends(get_db)):
    eid = _eid(user)
    ncf = data.numero_ncf or next_ncf(db, eid)
    subtotal, descuento, itbis, total = calcular_items(data.items)
    fac = Factura(
        id=gen_uuid(), empresa_id=eid, cliente_id=data.cliente_id,
        cotizacion_id=data.cotizacion_id, numero_ncf=ncf, tipo_ncf=data.tipo_ncf,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
        fecha_vencimiento=date.today()+timedelta(days=30),
        estatus="EMITIDA", condicion_pago=data.condicion_pago, notas=data.notas,
        subtotal=subtotal, descuento=descuento, itbis=itbis, total=total, balance=total
    )
    db.add(fac); db.flush()
    for it in data.items:
        base = it.cantidad * it.precio_unitario * (1 - it.descuento_pct/100)
        db.add(FacturaItem(
            id=gen_uuid(), factura_id=fac.id, producto_id=it.producto_id,
            descripcion_libre=it.descripcion_libre,
            cantidad=it.cantidad, precio_unitario=it.precio_unitario,
            descuento_pct=it.descuento_pct, itbis_pct=it.itbis_pct,
            total_linea=base*(1+it.itbis_pct/100)
        ))
        if it.producto_id:
            prod = db.query(Producto).filter_by(id=it.producto_id, empresa_id=eid).first()
            if prod:
                prod.stock_actual = max(0, prod.stock_actual - int(float(it.cantidad)))
                db.add(MovimientoInventario(
                    id=gen_uuid(), empresa_id=eid, producto_id=it.producto_id,
                    tipo="SALIDA", cantidad=it.cantidad,
                    origen_tipo="FACTURA", origen_id=fac.id
                ))
    db.commit(); return serialize(fac)

@app.get("/api/facturas/{fid}")
def get_factura(fid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    fac = db.query(Factura).filter_by(id=fid, empresa_id=eid).first()
    if not fac: raise HTTPException(404)
    cli   = db.query(Cliente).get(fac.cliente_id)
    items = db.query(FacturaItem).filter_by(factura_id=fid).all()
    pagos = db.query(Pago).filter_by(factura_id=fid).order_by(Pago.fecha).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    result = serialize(fac)
    result["cliente"] = serialize(cli) if cli else {}
    result["items"] = []
    for it in items:
        p = prods.get(it.producto_id)
        d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else (it.descripcion_libre or "—")
        result["items"].append(d)
    result["pagos"] = [serialize(p) for p in pagos]
    return result

@app.put("/api/facturas/{fid}/anular")
def anular_factura(fid: str, user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    fac = db.query(Factura).filter_by(id=fid, empresa_id=_eid(user)).first()
    if not fac: raise HTTPException(404)
    fac.estatus = "ANULADA"; db.commit(); return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# PAGOS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/pagos/stats")
def pagos_stats(user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user); hoy = date.today(); mes = hoy.replace(day=1)
    return {
        "cobrado_hoy":   float(db.query(func.sum(Pago.monto)).filter(Pago.empresa_id==eid, Pago.fecha==hoy).scalar() or 0),
        "cobrado_mes":   float(db.query(func.sum(Pago.monto)).filter(Pago.empresa_id==eid, Pago.fecha>=mes).scalar() or 0),
        "cobrado_total": float(db.query(func.sum(Pago.monto)).filter_by(empresa_id=eid).scalar() or 0),
        "pendiente":     float(db.query(func.sum(Factura.balance)).filter(Factura.empresa_id==eid, Factura.estatus.in_(["EMITIDA","PARCIAL"])).scalar() or 0),
        "cant_pagos":    db.query(func.count(Pago.id)).filter_by(empresa_id=eid).scalar() or 0,
    }

@app.get("/api/pagos")
def list_pagos(metodo: Optional[str]=None, user=Depends(get_current_user),
               db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(Pago, Factura, Cliente).join(Factura).join(Cliente).filter(Pago.empresa_id==eid)
    if metodo and metodo != "TODOS": query = query.filter(Pago.metodo==metodo)
    result = []
    for p, f, c in query.order_by(Pago.created_at.desc()).all():
        d = serialize(p); d["factura_ncf"] = f.numero_ncf or "—"; d["cliente_nombre"] = c.nombre
        result.append(d)
    return result

@app.post("/api/pagos", status_code=201)
def create_pago(data: PagoSchema, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    fac = db.query(Factura).filter_by(id=data.factura_id, empresa_id=eid).first()
    if not fac: raise HTTPException(404, "Factura no encontrada")
    pago = Pago(
        id=gen_uuid(), empresa_id=eid, factura_id=data.factura_id,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
        monto=data.monto, metodo=data.metodo,
        banco=data.banco, referencia=data.referencia, notas=data.notas
    )
    db.add(pago)
    fac.total_pagado = round(float(fac.total_pagado) + data.monto, 2)
    fac.balance      = round(float(fac.total) - float(fac.total_pagado), 2)
    fac.estatus      = "PAGADA" if fac.balance <= 0 else "PARCIAL"
    db.commit(); return serialize(pago)


# ════════════════════════════════════════════════════════════════════════════
# ÓRDENES DE COMPRA
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/ordenes-compra")
def list_ordenes(q: Optional[str]=None, estatus: Optional[str]=None,
                 user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    query = db.query(OrdenCompra, Proveedor).join(Proveedor).filter(OrdenCompra.empresa_id==eid)
    if q: query = query.filter(or_(OrdenCompra.numero.ilike(f"%{q}%"),
                                    Proveedor.nombre.ilike(f"%{q}%")))
    if estatus: query = query.filter(OrdenCompra.estatus==estatus)
    result = []
    for o, p in query.order_by(OrdenCompra.created_at.desc()).all():
        d = serialize(o); d["proveedor_nombre"] = p.nombre; result.append(d)
    return result

@app.post("/api/ordenes-compra", status_code=201)
def create_orden(data: OrdenCompraSchema, user=Depends(get_current_user),
                 db: Session=Depends(get_db)):
    eid    = _eid(user)
    numero = data.numero or next_num(db, "OC-", OrdenCompra, eid)
    subtotal = sum(it.cantidad * it.precio_unitario for it in data.items)
    itbis    = sum(it.cantidad * it.precio_unitario * (it.itbis_pct/100) for it in data.items)
    oc = OrdenCompra(
        id=gen_uuid(), empresa_id=eid, numero=numero,
        proveedor_id=data.proveedor_id,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
        fecha_entrega_est=date.fromisoformat(data.fecha_entrega_est) if data.fecha_entrega_est else None,
        estatus="EMITIDA", notas=data.notas,
        subtotal=subtotal, itbis=itbis, total=subtotal+itbis
    )
    db.add(oc); db.flush()
    for it in data.items:
        db.add(OrdenCompraItem(
            id=gen_uuid(), orden_id=oc.id, producto_id=it.producto_id,
            cantidad_solicitada=it.cantidad, precio_unitario=it.precio_unitario,
            itbis_pct=it.itbis_pct,
            total_linea=it.cantidad*it.precio_unitario*(1+it.itbis_pct/100)
        ))
    db.commit(); return serialize(oc)

@app.put("/api/ordenes-compra/{oid}/estatus")
def update_estatus_orden(oid: str, payload: dict = Body(default={}),
                          user=Depends(get_current_user), db: Session=Depends(get_db)):
    """Cambia el estatus de una orden de compra."""
    eid    = _eid(user)
    estatus = payload.get("estatus") or ""
    oc     = db.query(OrdenCompra).filter_by(id=oid, empresa_id=eid).first()
    if not oc: raise HTTPException(404, "Orden no encontrada")
    estatuses_validos = ["BORRADOR", "EMITIDA", "RECIBIDA", "PARCIAL", "ANULADA", "CERRADA"]
    if estatus not in estatuses_validos:
        raise HTTPException(400, f"Estatus inválido. Opciones: {', '.join(estatuses_validos)}")
    oc.estatus    = estatus
    oc.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "estatus": estatus}

@app.get("/api/ordenes-compra/{oid}")
def get_orden(oid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    oc  = db.query(OrdenCompra).filter_by(id=oid, empresa_id=eid).first()
    if not oc: raise HTTPException(404)
    prov  = db.query(Proveedor).get(oc.proveedor_id)
    items = db.query(OrdenCompraItem).filter_by(orden_id=oid).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    result = serialize(oc); result["proveedor"] = serialize(prov) if prov else {}
    result["items"] = []
    for it in items:
        p = prods.get(it.producto_id); d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else "—"
        result["items"].append(d)
    return result


# ════════════════════════════════════════════════════════════════════════════
# TRANSACCIONES / FINANZAS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/transacciones")
def list_transacciones(tipo: Optional[str]=None, user=Depends(get_current_user),
                       db: Session=Depends(get_db)):
    query = db.query(Transaccion).filter_by(empresa_id=_eid(user))
    if tipo: query = query.filter(Transaccion.tipo==tipo)
    return [serialize(t) for t in query.order_by(Transaccion.fecha.desc()).all()]

@app.post("/api/transacciones", status_code=201)
def create_transaccion(data: TransaccionSchema, user=Depends(get_current_user),
                       db: Session=Depends(get_db)):
    t = Transaccion(
        id=gen_uuid(),
        empresa_id=_eid(user),
        tipo=data.tipo,
        categoria=data.categoria,
        descripcion=data.descripcion,
        monto=data.monto,
        metodo=data.metodo,
        referencia=data.referencia,
        notas=data.notas,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
    )
    db.add(t); db.commit(); return serialize(t)

@app.get("/api/finanzas/resumen")
def resumen_finanzas(user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user); hoy = date.today(); mes = hoy.replace(day=1)
    def s(tipo, desde=None):
        q = db.query(func.sum(Transaccion.monto)).filter(Transaccion.empresa_id==eid, Transaccion.tipo==tipo)
        if desde: q = q.filter(Transaccion.fecha>=desde)
        return float(q.scalar() or 0)
    return {
        "ingresos_mes":   s("INGRESO", mes),   "egresos_mes":    s("EGRESO", mes),
        "utilidad_mes":   s("INGRESO", mes)  - s("EGRESO", mes),
        "ingresos_total": s("INGRESO"),        "egresos_total":  s("EGRESO"),
        "utilidad_total": s("INGRESO") - s("EGRESO"),
    }


# ════════════════════════════════════════════════════════════════════════════
# NÓMINA
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/nomina/empleados")
def get_empleados(activo: bool=True, user=Depends(get_current_user), db: Session=Depends(get_db)):
    return nom_module.listar_empleados(_eid(user), db, activo)

@app.post("/api/nomina/empleados", status_code=201)
def crear_empleado_ep(data: nom_module.EmpleadoSchema,
                      user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return nom_module.crear_empleado(data, _eid(user), db)

@app.get("/api/nomina/empleados/{emp_id}")
def get_empleado(emp_id: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    e = db.query(Empleado).filter_by(id=emp_id, empresa_id=_eid(user)).first()
    if not e: raise HTTPException(404)
    return nom_module._serializar_empleado(e)

@app.put("/api/nomina/empleados/{emp_id}")
def update_empleado(emp_id: str, data: nom_module.EmpleadoSchema,
                    user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    e = db.query(Empleado).filter_by(id=emp_id, empresa_id=_eid(user)).first()
    if not e: raise HTTPException(404)
    for k, v in data.dict(exclude_none=True).items():
        if hasattr(e, k): setattr(e, k, v)
    e.updated_at = datetime.utcnow(); db.commit()
    return nom_module._serializar_empleado(e)

@app.delete("/api/nomina/empleados/{emp_id}")
def baja_empleado(emp_id: str, user=Depends(admin_only), db: Session=Depends(get_db)):
    e = db.query(Empleado).filter_by(id=emp_id, empresa_id=_eid(user)).first()
    if not e: raise HTTPException(404)
    e.activo = False; e.fecha_salida = date.today(); db.commit()
    return {"ok": True}

@app.post("/api/nomina/simular")
def simular_nomina_ep(data: nom_module.SimularNominaSchema, user=Depends(get_current_user)):
    return nom_module.calcular_nomina_empleado(
        data.salario_base, data.bonificacion, data.horas_extra,
        data.valor_hora, data.otros_ingresos, data.otros_descuentos
    )

@app.get("/api/nomina/nominas")
def list_nominas(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return [serialize(n) for n in
            db.query(Nomina).filter_by(empresa_id=_eid(user))
            .order_by(Nomina.periodo.desc()).all()]

@app.post("/api/nomina/nominas", status_code=201)
def crear_nomina_ep(data: nom_module.NominaCreateSchema,
                    user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return nom_module.crear_nomina(data, _eid(user), db)

@app.post("/api/nomina/nominas/{nid}/procesar")
def procesar_nomina_ep(nid: str, user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return nom_module.procesar_nomina(nid, _eid(user), db)

@app.get("/api/nomina/nominas/{nid}/detalle")
def detalle_nomina_ep(nid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    return nom_module.detalle_nomina(nid, _eid(user), db)

@app.post("/api/nomina/nominas/{nid}/reprocesar")
def reprocesar_nomina(nid: str, user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    """Permite reprocesar una nómina en cualquier estado para recalcular con los empleados actuales."""
    eid = _eid(user)
    n = db.query(Nomina).filter_by(id=nid, empresa_id=eid).first()
    if not n: raise HTTPException(404)
    if n.estatus == "PAGADA": raise HTTPException(400, "No se puede reprocesar una nómina ya pagada")
    # Forzar estado BORRADOR para que procesar_nomina lo acepte
    n.estatus = "BORRADOR"
    db.commit()
    return nom_module.procesar_nomina(nid, eid, db)

@app.post("/api/nomina/nominas/{nid}/pagar")
def pagar_nomina(nid: str, user=Depends(admin_only), db: Session=Depends(get_db)):
    n = db.query(Nomina).filter_by(id=nid, empresa_id=_eid(user)).first()
    if not n: raise HTTPException(404)
    if n.estatus != "PROCESADA": raise HTTPException(400, "Debe estar PROCESADA primero")
    n.estatus = "PAGADA"; n.updated_at = datetime.utcnow(); db.commit()
    return {"ok": True, "estatus": "PAGADA"}


# ════════════════════════════════════════════════════════════════════════════
# TSS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/tss/generar/{nid}")
def generar_tss(nid: str, user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return nom_module.generar_tss(nid, _eid(user), db)

@app.get("/api/tss/tasas")
def tasas_tss(user=Depends(get_current_user)):
    return nom_module.TASAS

@app.post("/api/tss/simular")
def simular_tss(salario: float, user=Depends(get_current_user)):
    return nom_module.calcular_aportes_tss(salario)


# ════════════════════════════════════════════════════════════════════════════
# BANCOS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/bancos/cuentas")
def list_cuentas(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return banco_module.listar_cuentas(_eid(user), db)

@app.post("/api/bancos/cuentas", status_code=201)
def crear_cuenta_ep(data: banco_module.CuentaSchema,
                    user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return banco_module.crear_cuenta(data, _eid(user), db)

@app.get("/api/bancos/resumen")
def resumen_bancos(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return banco_module.resumen_banco(_eid(user), db)

@app.get("/api/bancos/movimientos")
def list_movimientos(cuenta_id: Optional[str]=None,
                     desde: Optional[str]=None, hasta: Optional[str]=None,
                     user=Depends(get_current_user), db: Session=Depends(get_db)):
    return banco_module.listar_movimientos(_eid(user), db, cuenta_id, desde, hasta)

@app.post("/api/bancos/movimientos", status_code=201)
def crear_movimiento_ep(data: banco_module.MovimientoSchema,
                        user=Depends(get_current_user), db: Session=Depends(get_db)):
    return banco_module.registrar_movimiento(data, _eid(user), db)

@app.post("/api/bancos/conciliacion")
def iniciar_conciliacion_ep(data: banco_module.ConciliacionSchema,
                            user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    return banco_module.iniciar_conciliacion(data, _eid(user), db)

@app.put("/api/bancos/cuentas/{cid}/desactivar")
def desactivar_cuenta(cid: str, user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    c = db.query(CuentaBancaria).filter_by(id=cid, empresa_id=_eid(user)).first()
    if not c: raise HTTPException(404, "Cuenta no encontrada")
    # Verificar que no tenga movimientos pendientes (no conciliados)
    pendientes = db.query(MovimientoBanco).filter_by(cuenta_id=cid, conciliado=False).count()
    if pendientes > 0:
        raise HTTPException(400, f"La cuenta tiene {pendientes} movimiento(s) sin conciliar. Concílalos primero.")
    c.activa = False
    db.commit()
    return {"ok": True, "mensaje": f"Cuenta {c.banco} {c.numero} desactivada"}

@app.put("/api/bancos/movimientos/{mid}/conciliar")
def conciliar_ep(mid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    return banco_module.conciliar_movimiento(mid, _eid(user), db)



# ════════════════════════════════════════════════════════════════════════════
# INVENTARIO — endpoint dedicado con estado de stock
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/inventario")
def get_inventario(user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    productos = db.query(Producto).filter_by(empresa_id=eid, activo=True).all()
    result = []
    for p in productos:
        if p.stock_actual <= 0:
            estado = "AGOTADO"
        elif p.stock_minimo > 0 and p.stock_actual <= p.stock_minimo:
            estado = "BAJO"
        else:
            estado = "OK"
        # Último movimiento
        ultimo = (db.query(MovimientoInventario)
                  .filter_by(producto_id=p.id)
                  .order_by(MovimientoInventario.created_at.desc())
                  .first())
        result.append({
            "id":               p.id,
            "codigo":           p.codigo,
            "descripcion":      p.descripcion,
            "marca":            p.marca or "—",
            "unidad":           p.unidad,
            "stock_actual":     p.stock_actual,
            "stock_minimo":     p.stock_minimo,
            "precio_costo":     p.precio_costo,
            "precio_venta":     p.precio_venta,
            "estado":           estado,
            "ultimo_movimiento": str(ultimo.created_at.date()) if ultimo else "—",
        })
    return result


# ════════════════════════════════════════════════════════════════════════════
# RESUMEN CONTABLE — endpoint para la página de contabilidad
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/reportes/resumen-contable")
def resumen_contable(user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user)
    hoy = date.today()
    mes = hoy.replace(day=1)

    def suma(tipo, desde=None):
        q = db.query(func.sum(Transaccion.monto)).filter(
            Transaccion.empresa_id==eid, Transaccion.tipo==tipo)
        if desde: q = q.filter(Transaccion.fecha>=desde)
        return float(q.scalar() or 0)

    return {
        "ingresos_mes":   suma("INGRESO", mes),
        "egresos_mes":    suma("EGRESO",  mes),
        "utilidad_mes":   suma("INGRESO", mes) - suma("EGRESO", mes),
        "ingresos_total": suma("INGRESO"),
        "egresos_total":  suma("EGRESO"),
        "utilidad_total": suma("INGRESO") - suma("EGRESO"),
    }

# ════════════════════════════════════════════════════════════════════════════
# REPORTES DGII
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/reportes/ventas")
def reporte_ventas(desde: Optional[str]=None, hasta: Optional[str]=None,
                   user=Depends(get_current_user), db: Session=Depends(get_db)):
    eid = _eid(user); hoy = date.today()
    d0 = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1 = date.fromisoformat(hasta) if hasta else hoy
    rows = (db.query(Factura, Cliente).join(Cliente)
            .filter(Factura.empresa_id==eid, Factura.fecha>=d0,
                    Factura.fecha<=d1, Factura.estatus!="ANULADA")
            .order_by(Factura.fecha.desc()).all())
    detalle = [{"ncf": f.numero_ncf or "—", "cliente": c.nombre, "fecha": str(f.fecha),
                "total": float(f.total), "cobrado": float(f.total_pagado),
                "balance": float(f.balance), "estatus": f.estatus}
               for f, c in rows]
    return {
        "desde": str(d0), "hasta": str(d1),
        "resumen": {
            "total_ventas":   sum(r["total"]   for r in detalle),
            "total_cobrado":  sum(r["cobrado"]  for r in detalle),
            "total_balance":  sum(r["balance"]  for r in detalle),
            "total_facturas": len(detalle),
        },
        "detalle": detalle
    }

@app.get("/api/reportes/dgii-606")
def reporte_606(desde: Optional[str]=None, hasta: Optional[str]=None,
                user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    eid = _eid(user); hoy = date.today()
    d0 = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1 = date.fromisoformat(hasta) if hasta else hoy
    rows = (db.query(OrdenCompra, Proveedor).join(Proveedor)
            .filter(OrdenCompra.empresa_id==eid, OrdenCompra.fecha>=d0,
                    OrdenCompra.fecha<=d1, OrdenCompra.estatus!="ANULADA")
            .order_by(OrdenCompra.fecha).all())
    return {"desde": str(d0), "hasta": str(d1), "filas": [
        {"rnc_proveedor": p.rnc or "—", "nombre": p.nombre,
         "fecha": str(o.fecha), "numero": o.numero,
         "monto": float(o.total), "itbis": float(o.itbis)}
        for o, p in rows
    ]}

@app.get("/api/reportes/dgii-607")
def reporte_607(desde: Optional[str]=None, hasta: Optional[str]=None,
                user=Depends(admin_supervisor), db: Session=Depends(get_db)):
    eid = _eid(user); hoy = date.today()
    d0 = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1 = date.fromisoformat(hasta) if hasta else hoy
    rows = (db.query(Factura, Cliente).join(Cliente)
            .filter(Factura.empresa_id==eid, Factura.fecha>=d0,
                    Factura.fecha<=d1, Factura.estatus!="ANULADA")
            .order_by(Factura.fecha).all())
    return {"desde": str(d0), "hasta": str(d1), "filas": [
        {"rnc_cliente": c.rnc_cedula or "—", "nombre": c.nombre,
         "tipo_id": c.tipo or "FINAL", "ncf": f.numero_ncf or "—",
         "tipo_ncf": f.tipo_ncf or "B02", "fecha": str(f.fecha),
         "subtotal": float(f.subtotal), "itbis": float(f.itbis), "total": float(f.total)}
        for f, c in rows
    ]}


# ════════════════════════════════════════════════════════════════════════════
# PDF
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/facturas/{fid}/pdf")
def pdf_factura(fid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    if not REPORTLAB_OK: raise HTTPException(503, "pip install reportlab pillow")
    eid = _eid(user)
    fac = db.query(Factura).filter_by(id=fid, empresa_id=eid).first()
    if not fac: raise HTTPException(404)
    cli   = db.query(Cliente).get(fac.cliente_id)
    emp   = db.query(Empresa).get(eid)
    items = db.query(FacturaItem).filter_by(factura_id=fid).all()
    pagos = db.query(Pago).filter_by(factura_id=fid).order_by(Pago.fecha).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    items_data = []
    for it in items:
        p = prods.get(it.producto_id); d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else (it.descripcion_libre or "—")
        items_data.append(d)
    data = {"factura": serialize(fac), "cliente": serialize(cli) if cli else {},
            "empresa": serialize(emp) if emp else {}, "items": items_data,
            "pagos": [serialize(p) for p in pagos]}
    try:
        pdf_bytes = generar_pdf_factura(data)
    except Exception as e:
        raise HTTPException(500, f"Error PDF: {e}")
    ncf = (fac.numero_ncf or fid[:8]).replace("/","_").replace(" ","_")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Factura_{ncf}.pdf"'})

@app.get("/api/cotizaciones/{cid}/pdf")
def pdf_cotizacion(cid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    if not REPORTLAB_OK: raise HTTPException(503, "pip install reportlab pillow")
    eid = _eid(user)
    cot = db.query(Cotizacion).filter_by(id=cid, empresa_id=eid).first()
    if not cot: raise HTTPException(404)
    cli   = db.query(Cliente).get(cot.cliente_id)
    emp   = db.query(Empresa).get(eid)
    items = db.query(CotizacionItem).filter_by(cotizacion_id=cid).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    items_data = []
    for it in items:
        p = prods.get(it.producto_id); d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else (it.descripcion_libre or "—")
        items_data.append(d)
    data = {"cotizacion": serialize(cot), "cliente": serialize(cli) if cli else {},
            "empresa": serialize(emp) if emp else {}, "items": items_data}
    try:
        pdf_bytes = generar_pdf_cotizacion(data)
    except Exception as e:
        raise HTTPException(500, f"Error PDF: {e}")
    num = (cot.numero or cid[:8]).replace("/","_").replace(" ","_")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Cotizacion_{num}.pdf"'})

@app.get("/api/ordenes-compra/{oid}/pdf")
def pdf_orden(oid: str, user=Depends(get_current_user), db: Session=Depends(get_db)):
    if not REPORTLAB_OK: raise HTTPException(503, "pip install reportlab pillow")
    eid = _eid(user)
    oc   = db.query(OrdenCompra).filter_by(id=oid, empresa_id=eid).first()
    if not oc: raise HTTPException(404)
    prov  = db.query(Proveedor).get(oc.proveedor_id)
    emp   = db.query(Empresa).get(eid)
    items = db.query(OrdenCompraItem).filter_by(orden_id=oid).all()
    prods = {p.id: p for p in db.query(Producto).filter_by(empresa_id=eid).all()}
    items_data = []
    for it in items:
        p = prods.get(it.producto_id); d = serialize(it)
        d["producto_codigo"] = p.codigo if p else "—"
        d["producto_desc"]   = p.descripcion if p else "—"
        items_data.append(d)
    data = {"orden": serialize(oc), "proveedor": serialize(prov) if prov else {},
            "empresa": serialize(emp) if emp else {}, "items": items_data}
    try:
        pdf_bytes = generar_pdf_orden(data)
    except Exception as e:
        raise HTTPException(500, f"Error PDF: {e}")
    num = (oc.numero or oid[:8]).replace("/","_").replace(" ","_")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="OrdenCompra_{num}.pdf"'})


# ════════════════════════════════════════════════════════════════════════════
# ARRANQUE DIRECTO
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# EXCEL EXPORTS
# ════════════════════════════════════════════════════════════════════════════

def _excel_response(data: bytes, filename: str):
    """Helper para retornar archivo Excel como descarga."""
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/api/excel/contabilidad")
def excel_contabilidad(
    desde: str = None, hasta: str = None,
    user=Depends(get_current_user), db: Session = Depends(get_db)
):
    if not OPENPYXL_OK:
        raise HTTPException(503, "Instala openpyxl: pip install openpyxl")
    eid  = _eid(user)
    hoy  = date.today()
    d0   = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1   = date.fromisoformat(hasta) if hasta else hoy
    trx  = db.query(Transaccion).filter(
        Transaccion.empresa_id == eid,
        Transaccion.fecha >= d0,
        Transaccion.fecha <= d1
    ).order_by(Transaccion.fecha).all()
    emp  = db.query(Empresa).get(eid)
    data = exportar_contabilidad(
        [serialize(t) for t in trx],
        serialize(emp) if emp else {},
        str(d0), str(d1)
    )
    fname = f"Contabilidad_{d0}_{d1}.xlsx"
    return _excel_response(data, fname)


@app.get("/api/excel/606")
def excel_606(
    desde: str = None, hasta: str = None,
    user=Depends(admin_supervisor), db: Session = Depends(get_db)
):
    if not OPENPYXL_OK:
        raise HTTPException(503, "Instala openpyxl: pip install openpyxl")
    eid  = _eid(user)
    hoy  = date.today()
    d0   = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1   = date.fromisoformat(hasta) if hasta else hoy
    r    = reporte_606(desde=str(d0), hasta=str(d1), user=user, db=db)
    emp  = db.query(Empresa).get(eid)
    data = exportar_606(r["filas"], serialize(emp) if emp else {}, str(d0), str(d1))
    return _excel_response(data, f"DGII_606_{d0}_{d1}.xlsx")


@app.get("/api/excel/607")
def excel_607(
    desde: str = None, hasta: str = None,
    user=Depends(admin_supervisor), db: Session = Depends(get_db)
):
    if not OPENPYXL_OK:
        raise HTTPException(503, "Instala openpyxl: pip install openpyxl")
    eid  = _eid(user)
    hoy  = date.today()
    d0   = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1   = date.fromisoformat(hasta) if hasta else hoy
    r    = reporte_607(desde=str(d0), hasta=str(d1), user=user, db=db)
    emp  = db.query(Empresa).get(eid)
    data = exportar_607(r["filas"], serialize(emp) if emp else {}, str(d0), str(d1))
    return _excel_response(data, f"DGII_607_{d0}_{d1}.xlsx")


@app.get("/api/excel/ventas")
def excel_ventas(
    desde: str = None, hasta: str = None,
    user=Depends(get_current_user), db: Session = Depends(get_db)
):
    if not OPENPYXL_OK:
        raise HTTPException(503, "Instala openpyxl: pip install openpyxl")
    hoy  = date.today()
    d0   = date.fromisoformat(desde) if desde else hoy.replace(day=1)
    d1   = date.fromisoformat(hasta) if hasta else hoy
    r    = reporte_ventas(desde=str(d0), hasta=str(d1), user=user, db=db)
    emp  = db.query(Empresa).get(_eid(user))
    data = exportar_reporte_ventas(
        r["detalle"], r["resumen"],
        serialize(emp) if emp else {},
        str(d0), str(d1)
    )
    return _excel_response(data, f"Ventas_{d0}_{d1}.xlsx")


if __name__ == "__main__":
    import uvicorn
    import socket

    # Leer .env si existe
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("PORT="):
                os.environ["PORT"] = line.split("=", 1)[1].strip()

    # Buscar puerto libre automáticamente
    preferred = int(os.getenv("PORT", "8765"))
    port = preferred
    for candidate in [preferred, 8000, 8080, 8888, 9000, 9090, 5000]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", candidate))
            port = candidate
            break
        except OSError:
            continue

    print(f"\n  FactuPro iniciando en: http://127.0.0.1:{port}\n")

    uvicorn.run(
        app,            # objeto directo, evita problemas de reload en Windows
        host="127.0.0.1",
        port=port,
        reload=False,   # reload=True causa WinError 10013 en algunos Windows
        log_level="info",
    )
