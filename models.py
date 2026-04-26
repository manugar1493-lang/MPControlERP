"""
models.py — FactuPro v2.0
Modelos SQLAlchemy — Multi-empresa, Auth, Nómina, Bancos, TSS
"""

import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Date, DateTime,
    ForeignKey, Text, UniqueConstraint, Index, LargeBinary
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


def gen_uuid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class TipoCliente(str, enum.Enum):
    FINAL         = "FINAL"
    JURIDICO      = "JURIDICO"
    GUBERNAMENTAL = "GUBERNAMENTAL"
    ESPECIAL      = "ESPECIAL"

class EstatusFactura(str, enum.Enum):
    BORRADOR = "BORRADOR"
    EMITIDA  = "EMITIDA"
    PARCIAL  = "PARCIAL"
    PAGADA   = "PAGADA"
    ANULADA  = "ANULADA"
    VENCIDA  = "VENCIDA"

class EstatusCotizacion(str, enum.Enum):
    BORRADOR   = "BORRADOR"
    ENVIADA    = "ENVIADA"
    APROBADA   = "APROBADA"
    RECHAZADA  = "RECHAZADA"
    CONVERTIDA = "CONVERTIDA"
    VENCIDA    = "VENCIDA"

class MetodoPago(str, enum.Enum):
    EFECTIVO      = "EFECTIVO"
    TRANSFERENCIA = "TRANSFERENCIA"
    TARJETA       = "TARJETA"
    CHEQUE        = "CHEQUE"

class TipoNCF(str, enum.Enum):
    B01 = "B01"
    B02 = "B02"
    B14 = "B14"
    B15 = "B15"
    E31 = "E31"
    E32 = "E32"

class TipoMovimiento(str, enum.Enum):
    ENTRADA = "ENTRADA"
    SALIDA  = "SALIDA"
    AJUSTE  = "AJUSTE"

class TipoTransaccion(str, enum.Enum):
    INGRESO = "INGRESO"
    EGRESO  = "EGRESO"

class RolUsuario(str, enum.Enum):
    ADMIN      = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    OPERADOR   = "OPERADOR"

class TipoContrato(str, enum.Enum):
    INDEFINIDO = "INDEFINIDO"
    DEFINIDO   = "DEFINIDO"
    POR_OBRA   = "POR_OBRA"

class EstatusNomina(str, enum.Enum):
    BORRADOR  = "BORRADOR"
    PROCESADA = "PROCESADA"
    PAGADA    = "PAGADA"
    ANULADA   = "ANULADA"

class TipoConcepto(str, enum.Enum):
    INGRESO   = "INGRESO"
    DEDUCCION = "DEDUCCION"

class TipoMovBanco(str, enum.Enum):
    DEBITO  = "DEBITO"
    CREDITO = "CREDITO"

class TipoCuenta(str, enum.Enum):
    CORRIENTE = "CORRIENTE"
    AHORRO    = "AHORRO"
    NOMINA    = "NOMINA"


# ══════════════════════════════════════════════════════════════════════════════
# EMPRESA  (tabla raíz del multi-tenant)
# ══════════════════════════════════════════════════════════════════════════════

class Empresa(Base):
    __tablename__ = "empresa"

    id               = Column(String, primary_key=True, default=gen_uuid)
    nombre           = Column(String(200), nullable=False, default="Mi Empresa")
    nombre_comercial = Column(String(200))
    rnc              = Column(String(20))
    direccion        = Column(Text)
    telefono         = Column(String(30))
    email            = Column(String(100))
    sitio_web        = Column(String(200))
    logo_path        = Column(String(500))
    moneda           = Column(String(10), default="RD$")
    itbis_pct        = Column(Float, default=18.0)
    seq_factura      = Column(Integer, default=1)
    seq_cotizacion   = Column(Integer, default=1)
    seq_orden        = Column(Integer, default=1)
    ncf_prefix       = Column(String(10), default="B02")
    ncf_sequence     = Column(Integer, default=1)
    activa           = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    usuarios  = relationship("Usuario",  back_populates="empresa")
    clientes  = relationship("Cliente",  back_populates="empresa")
    productos = relationship("Producto", back_populates="empresa")


# ══════════════════════════════════════════════════════════════════════════════
# AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════════════════════

class Usuario(Base):
    __tablename__ = "usuarios"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    nombre     = Column(String(100), nullable=False)
    email      = Column(String(100), nullable=False)
    password   = Column(String(200), nullable=False)
    rol        = Column(String(30), default=RolUsuario.OPERADOR)
    activo     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "email", name="uq_usuario_email_empresa"),
        Index("ix_usuarios_empresa", "empresa_id"),
    )

    empresa = relationship("Empresa", back_populates="usuarios")


class Sesion(Base):
    """Control de tokens activos (para invalidación en logout)."""
    __tablename__ = "sesiones"

    id          = Column(String, primary_key=True, default=gen_uuid)
    usuario_id  = Column(String, ForeignKey("usuarios.id"), nullable=False)
    empresa_id  = Column(String, nullable=False)
    token_hash  = Column(String(200), unique=True, nullable=False)
    expira_en   = Column(DateTime, nullable=False)
    activa      = Column(Boolean, default=True)
    ip          = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_sesiones_token", "token_hash"),)


# ══════════════════════════════════════════════════════════════════════════════
# CLIENTES  (con empresa_id)
# ══════════════════════════════════════════════════════════════════════════════

class Cliente(Base):
    __tablename__ = "clientes"

    id             = Column(String, primary_key=True, default=gen_uuid)
    empresa_id     = Column(String, ForeignKey("empresa.id"), nullable=False)
    nombre         = Column(String(200), nullable=False)
    tipo           = Column(String(30), default=TipoCliente.FINAL)
    rnc_cedula     = Column(String(20))
    telefono       = Column(String(30))
    email          = Column(String(100))
    direccion      = Column(Text)
    limite_credito = Column(Float, default=0.0)
    dias_credito   = Column(Integer, default=0)
    notas          = Column(Text)
    activo         = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_clientes_empresa", "empresa_id"),)

    empresa      = relationship("Empresa", back_populates="clientes")
    facturas     = relationship("Factura",    back_populates="cliente")
    cotizaciones = relationship("Cotizacion", back_populates="cliente")
    documentos   = relationship("ClienteDocumento", back_populates="cliente",
                                cascade="all, delete-orphan")


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTOS DE CLIENTE  (PDFs adjuntos)
# ══════════════════════════════════════════════════════════════════════════════

class ClienteDocumento(Base):
    __tablename__ = "cliente_documentos"

    id             = Column(String, primary_key=True, default=gen_uuid)
    empresa_id     = Column(String, ForeignKey("empresa.id"), nullable=False)
    cliente_id     = Column(String, ForeignKey("clientes.id"), nullable=False)
    nombre_archivo = Column(String(300), nullable=False)
    tamano_kb      = Column(Integer, default=0)
    contenido      = Column(LargeBinary, nullable=False)   # PDF almacenado en BD
    created_at     = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_cliente_docs_cliente", "cliente_id"),)

    cliente = relationship("Cliente", back_populates="documentos")


# ══════════════════════════════════════════════════════════════════════════════
# PROVEEDORES  (con empresa_id)
# ══════════════════════════════════════════════════════════════════════════════

class Proveedor(Base):
    __tablename__ = "proveedores"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    nombre     = Column(String(200), nullable=False)
    rnc        = Column(String(20))
    contacto   = Column(String(100))
    telefono   = Column(String(30))
    email      = Column(String(100))
    direccion  = Column(Text)
    dias_pago  = Column(Integer, default=30)
    notas      = Column(Text)
    activo     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_proveedores_empresa", "empresa_id"),)

    ordenes = relationship("OrdenCompra", back_populates="proveedor")


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORÍAS & PRODUCTOS  (con empresa_id)
# ══════════════════════════════════════════════════════════════════════════════

class Categoria(Base):
    __tablename__ = "categorias"

    id          = Column(String, primary_key=True, default=gen_uuid)
    empresa_id  = Column(String, ForeignKey("empresa.id"), nullable=False)
    nombre      = Column(String(100), nullable=False)
    descripcion = Column(Text)

    productos = relationship("Producto", back_populates="categoria")


class Producto(Base):
    __tablename__ = "productos"

    id           = Column(String, primary_key=True, default=gen_uuid)
    empresa_id   = Column(String, ForeignKey("empresa.id"), nullable=False)
    codigo       = Column(String(50), nullable=False)
    descripcion  = Column(String(300), nullable=False)
    marca        = Column(String(100))
    unidad       = Column(String(20), default="UND")
    categoria_id = Column(String, ForeignKey("categorias.id"), nullable=True)
    precio_venta = Column(Float, nullable=False, default=0.0)
    precio_costo = Column(Float, default=0.0)
    itbis_pct    = Column(Float, default=18.0)
    stock_actual = Column(Integer, default=0)
    stock_minimo = Column(Integer, default=0)
    ubicacion    = Column(String(100))
    notas        = Column(Text)
    activo       = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_producto_codigo_empresa"),
        Index("ix_productos_empresa", "empresa_id"),
    )

    empresa     = relationship("Empresa", back_populates="productos")
    categoria   = relationship("Categoria", back_populates="productos")
    movimientos = relationship("MovimientoInventario", back_populates="producto")


# ══════════════════════════════════════════════════════════════════════════════
# COTIZACIONES
# ══════════════════════════════════════════════════════════════════════════════

class Cotizacion(Base):
    __tablename__ = "cotizaciones"

    id                = Column(String, primary_key=True, default=gen_uuid)
    empresa_id        = Column(String, ForeignKey("empresa.id"), nullable=False)
    numero            = Column(String(30))
    cliente_id        = Column(String, ForeignKey("clientes.id"), nullable=False)
    fecha             = Column(Date, default=date.today)
    fecha_vencimiento = Column(Date)
    estatus           = Column(String(20), default=EstatusCotizacion.BORRADOR)
    condiciones       = Column(Text)
    notas             = Column(Text)
    subtotal          = Column(Float, default=0.0)
    descuento         = Column(Float, default=0.0)
    itbis             = Column(Float, default=0.0)
    total             = Column(Float, default=0.0)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "numero", name="uq_cotizacion_numero_empresa"),
        Index("ix_cotizaciones_empresa", "empresa_id"),
    )

    cliente  = relationship("Cliente",        back_populates="cotizaciones")
    items    = relationship("CotizacionItem", back_populates="cotizacion", cascade="all, delete-orphan")
    facturas = relationship("Factura",        back_populates="cotizacion")


class CotizacionItem(Base):
    __tablename__ = "cotizacion_items"

    id                = Column(String, primary_key=True, default=gen_uuid)
    cotizacion_id     = Column(String, ForeignKey("cotizaciones.id"), nullable=False)
    producto_id       = Column(String, ForeignKey("productos.id"), nullable=True)
    descripcion_libre = Column(String(300))
    cantidad          = Column(Float, nullable=False, default=1)
    precio_unitario   = Column(Float, nullable=False, default=0.0)
    descuento_pct     = Column(Float, default=0.0)
    itbis_pct         = Column(Float, default=18.0)
    total_linea       = Column(Float, default=0.0)

    cotizacion = relationship("Cotizacion", back_populates="items")
    producto   = relationship("Producto")


# ══════════════════════════════════════════════════════════════════════════════
# FACTURAS
# ══════════════════════════════════════════════════════════════════════════════

class Factura(Base):
    __tablename__ = "facturas"

    id                = Column(String, primary_key=True, default=gen_uuid)
    empresa_id        = Column(String, ForeignKey("empresa.id"), nullable=False)
    numero_ncf        = Column(String(30))
    tipo_ncf          = Column(String(10), default="B02")
    cliente_id        = Column(String, ForeignKey("clientes.id"), nullable=False)
    cotizacion_id     = Column(String, ForeignKey("cotizaciones.id"), nullable=True)
    fecha             = Column(Date, default=date.today)
    fecha_vencimiento = Column(Date)
    estatus           = Column(String(20), default=EstatusFactura.BORRADOR)
    condicion_pago    = Column(String(50), default="CONTADO")
    subtotal          = Column(Float, default=0.0)
    descuento         = Column(Float, default=0.0)
    itbis             = Column(Float, default=0.0)
    total             = Column(Float, default=0.0)
    total_pagado      = Column(Float, default=0.0)
    balance           = Column(Float, default=0.0)
    notas             = Column(Text)
    ecf_xml           = Column(Text)
    ecf_estado        = Column(String(50))
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "numero_ncf", name="uq_factura_ncf_empresa"),
        Index("ix_facturas_empresa", "empresa_id"),
        Index("ix_facturas_fecha",   "empresa_id", "fecha"),
    )

    cliente    = relationship("Cliente",     back_populates="facturas")
    cotizacion = relationship("Cotizacion",  back_populates="facturas")
    items      = relationship("FacturaItem", back_populates="factura", cascade="all, delete-orphan")
    pagos      = relationship("Pago",        back_populates="factura")


class FacturaItem(Base):
    __tablename__ = "factura_items"

    id                = Column(String, primary_key=True, default=gen_uuid)
    factura_id        = Column(String, ForeignKey("facturas.id"), nullable=False)
    producto_id       = Column(String, ForeignKey("productos.id"), nullable=True)
    descripcion_libre = Column(String(300))
    cantidad          = Column(Float, nullable=False, default=1)
    precio_unitario   = Column(Float, nullable=False, default=0.0)
    descuento_pct     = Column(Float, default=0.0)
    itbis_pct         = Column(Float, default=18.0)
    total_linea       = Column(Float, default=0.0)

    factura  = relationship("Factura",  back_populates="items")
    producto = relationship("Producto")


# ══════════════════════════════════════════════════════════════════════════════
# PAGOS
# ══════════════════════════════════════════════════════════════════════════════

class Pago(Base):
    __tablename__ = "pagos"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    factura_id = Column(String, ForeignKey("facturas.id"), nullable=False)
    fecha      = Column(Date, default=date.today)
    monto      = Column(Float, nullable=False)
    metodo     = Column(String(30), default=MetodoPago.EFECTIVO)
    banco      = Column(String(100))
    referencia = Column(String(100))
    notas      = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    factura = relationship("Factura", back_populates="pagos")


# ══════════════════════════════════════════════════════════════════════════════
# ÓRDENES DE COMPRA
# ══════════════════════════════════════════════════════════════════════════════

class OrdenCompra(Base):
    __tablename__ = "ordenes_compra"

    id                = Column(String, primary_key=True, default=gen_uuid)
    empresa_id        = Column(String, ForeignKey("empresa.id"), nullable=False)
    numero            = Column(String(30))
    proveedor_id      = Column(String, ForeignKey("proveedores.id"), nullable=False)
    fecha             = Column(Date, default=date.today)
    fecha_entrega_est = Column(Date)
    estatus           = Column(String(30), default="BORRADOR")
    subtotal          = Column(Float, default=0.0)
    itbis             = Column(Float, default=0.0)
    total             = Column(Float, default=0.0)
    notas             = Column(Text)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "numero", name="uq_orden_numero_empresa"),
        Index("ix_ordenes_empresa", "empresa_id"),
    )

    proveedor   = relationship("Proveedor",       back_populates="ordenes")
    items       = relationship("OrdenCompraItem", back_populates="orden", cascade="all, delete-orphan")
    recepciones = relationship("RecepcionCompra", back_populates="orden")


class OrdenCompraItem(Base):
    __tablename__ = "orden_compra_items"

    id                  = Column(String, primary_key=True, default=gen_uuid)
    orden_id            = Column(String, ForeignKey("ordenes_compra.id"), nullable=False)
    producto_id         = Column(String, ForeignKey("productos.id"), nullable=True)
    cantidad_solicitada = Column(Float, nullable=False, default=1)
    cantidad_recibida   = Column(Float, default=0.0)
    precio_unitario     = Column(Float, default=0.0)
    itbis_pct           = Column(Float, default=18.0)
    total_linea         = Column(Float, default=0.0)

    orden    = relationship("OrdenCompra", back_populates="items")
    producto = relationship("Producto")


class RecepcionCompra(Base):
    __tablename__ = "recepciones_compra"

    id                = Column(String, primary_key=True, default=gen_uuid)
    empresa_id        = Column(String, ForeignKey("empresa.id"), nullable=False)
    orden_id          = Column(String, ForeignKey("ordenes_compra.id"), nullable=False)
    fecha             = Column(Date, default=date.today)
    numero_referencia = Column(String(100))
    notas             = Column(Text)
    created_at        = Column(DateTime, default=datetime.utcnow)

    orden = relationship("OrdenCompra", back_populates="recepciones")
    items = relationship("RecepcionItem", back_populates="recepcion", cascade="all, delete-orphan")


class RecepcionItem(Base):
    __tablename__ = "recepcion_items"

    id                = Column(String, primary_key=True, default=gen_uuid)
    recepcion_id      = Column(String, ForeignKey("recepciones_compra.id"), nullable=False)
    orden_item_id     = Column(String, ForeignKey("orden_compra_items.id"))
    cantidad_recibida = Column(Float, nullable=False)

    recepcion = relationship("RecepcionCompra", back_populates="items")


# ══════════════════════════════════════════════════════════════════════════════
# INVENTARIO & TRANSACCIONES
# ══════════════════════════════════════════════════════════════════════════════

class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"

    id             = Column(String, primary_key=True, default=gen_uuid)
    empresa_id     = Column(String, ForeignKey("empresa.id"), nullable=False)
    producto_id    = Column(String, ForeignKey("productos.id"), nullable=False)
    tipo           = Column(String(20), default=TipoMovimiento.ENTRADA)
    cantidad       = Column(Float, nullable=False)
    costo_unitario = Column(Float, default=0.0)
    origen_tipo    = Column(String(50))
    origen_id      = Column(String)
    notas          = Column(Text)
    created_at     = Column(DateTime, default=datetime.utcnow)

    producto = relationship("Producto", back_populates="movimientos")


class Transaccion(Base):
    __tablename__ = "transacciones"

    id          = Column(String, primary_key=True, default=gen_uuid)
    empresa_id  = Column(String, ForeignKey("empresa.id"), nullable=False)
    tipo        = Column(String(20), nullable=False)
    categoria   = Column(String(100))
    descripcion = Column(String(300), nullable=False)
    monto       = Column(Float, nullable=False)
    fecha       = Column(Date, default=date.today)
    metodo      = Column(String(30), default="EFECTIVO")
    referencia  = Column(String(100))
    factura_id  = Column(String, ForeignKey("facturas.id"), nullable=True)
    notas       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_transacciones_empresa", "empresa_id"),)

    factura = relationship("Factura")


# ══════════════════════════════════════════════════════════════════════════════
# NÓMINA
# ══════════════════════════════════════════════════════════════════════════════

class Empleado(Base):
    __tablename__ = "empleados"

    id               = Column(String, primary_key=True, default=gen_uuid)
    empresa_id       = Column(String, ForeignKey("empresa.id"), nullable=False)
    cedula           = Column(String(20), nullable=False)
    nombre           = Column(String(200), nullable=False)
    apellidos        = Column(String(200))
    email            = Column(String(100))
    telefono         = Column(String(30))
    direccion        = Column(Text)
    fecha_ingreso    = Column(Date, default=date.today)
    fecha_salida     = Column(Date, nullable=True)
    tipo_contrato    = Column(String(30), default=TipoContrato.INDEFINIDO)
    cargo            = Column(String(100))
    departamento     = Column(String(100))
    salario_base     = Column(Float, nullable=False, default=0.0)
    comision_pct     = Column(Float, default=0.0)  # Porcentaje de comisión
    # TSS
    afp_id           = Column(String(50))   # Identificador en AFP
    sfs_id           = Column(String(50))   # Identificador en SFS
    nss              = Column(String(30))   # Número Seguridad Social
    activo           = Column(Boolean, default=True)
    notas            = Column(Text)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "cedula", name="uq_empleado_cedula_empresa"),
        Index("ix_empleados_empresa", "empresa_id"),
    )

    nomina_detalles = relationship("NominaDetalle", back_populates="empleado")


class ConceptoNomina(Base):
    """Catálogo de conceptos: AFP, SFS, ISR, bonos, horas extra, etc."""
    __tablename__ = "conceptos_nomina"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    nombre     = Column(String(100), nullable=False)
    tipo       = Column(String(20), default=TipoConcepto.INGRESO)  # INGRESO / DEDUCCION
    formula    = Column(String(200))   # Ej: "salario_base * 0.0287"
    porcentaje = Column(Float, default=0.0)
    monto_fijo = Column(Float, default=0.0)
    es_sistema = Column(Boolean, default=False)  # True = AFP, SFS, ISR (no editable)
    activo     = Column(Boolean, default=True)
    orden      = Column(Integer, default=0)


class Nomina(Base):
    __tablename__ = "nominas"

    id          = Column(String, primary_key=True, default=gen_uuid)
    empresa_id  = Column(String, ForeignKey("empresa.id"), nullable=False)
    periodo     = Column(String(7), nullable=False)  # "2025-01"
    descripcion = Column(String(200))
    fecha_pago  = Column(Date)
    estatus     = Column(String(20), default=EstatusNomina.BORRADOR)
    total_bruto = Column(Float, default=0.0)
    total_deducciones = Column(Float, default=0.0)
    total_neto  = Column(Float, default=0.0)
    notas       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "periodo", name="uq_nomina_periodo_empresa"),
        Index("ix_nominas_empresa", "empresa_id"),
    )

    detalles = relationship("NominaDetalle", back_populates="nomina", cascade="all, delete-orphan")


class NominaDetalle(Base):
    __tablename__ = "nomina_detalle"

    id           = Column(String, primary_key=True, default=gen_uuid)
    nomina_id    = Column(String, ForeignKey("nominas.id"), nullable=False)
    empleado_id  = Column(String, ForeignKey("empleados.id"), nullable=False)
    salario_base = Column(Float, default=0.0)
    # Ingresos
    horas_extra  = Column(Float, default=0.0)
    monto_extra  = Column(Float, default=0.0)
    bonificacion = Column(Float, default=0.0)
    otros_ingresos = Column(Float, default=0.0)
    total_ingresos = Column(Float, default=0.0)
    # Deducciones
    afp_empleado = Column(Float, default=0.0)
    sfs_empleado = Column(Float, default=0.0)
    isr_mensual  = Column(Float, default=0.0)
    otros_descuentos = Column(Float, default=0.0)
    total_deducciones = Column(Float, default=0.0)
    # Aportes patronales
    afp_patronal = Column(Float, default=0.0)
    sfs_patronal = Column(Float, default=0.0)
    infotep      = Column(Float, default=0.0)
    # Resultado
    salario_neto = Column(Float, default=0.0)
    notas        = Column(Text)

    nomina   = relationship("Nomina",   back_populates="detalles")
    empleado = relationship("Empleado", back_populates="nomina_detalles")


# ══════════════════════════════════════════════════════════════════════════════
# TSS — TESORERÍA SEGURIDAD SOCIAL
# ══════════════════════════════════════════════════════════════════════════════

class TssPeriodo(Base):
    __tablename__ = "tss_periodos"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    anio       = Column(Integer, nullable=False)
    mes        = Column(Integer, nullable=False)
    nomina_id  = Column(String, ForeignKey("nominas.id"), nullable=True)
    estatus    = Column(String(30), default="PENDIENTE")  # PENDIENTE / ENVIADO
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "anio", "mes", name="uq_tss_periodo"),
    )

    aportes      = relationship("TssAporte",      back_populates="periodo")
    exportaciones = relationship("TssExportacion", back_populates="periodo")


class TssAporte(Base):
    __tablename__ = "tss_aportes"

    id           = Column(String, primary_key=True, default=gen_uuid)
    periodo_id   = Column(String, ForeignKey("tss_periodos.id"), nullable=False)
    empleado_id  = Column(String, ForeignKey("empleados.id"), nullable=False)
    salario_cotizable = Column(Float, default=0.0)
    afp_empleado = Column(Float, default=0.0)
    afp_patronal = Column(Float, default=0.0)
    sfs_empleado = Column(Float, default=0.0)
    sfs_patronal = Column(Float, default=0.0)
    arl_patronal = Column(Float, default=0.0)
    total_empleado = Column(Float, default=0.0)
    total_patronal = Column(Float, default=0.0)

    periodo  = relationship("TssPeriodo",  back_populates="aportes")
    empleado = relationship("Empleado")


class TssExportacion(Base):
    __tablename__ = "tss_exportaciones"

    id          = Column(String, primary_key=True, default=gen_uuid)
    periodo_id  = Column(String, ForeignKey("tss_periodos.id"), nullable=False)
    archivo     = Column(String(500))
    tipo        = Column(String(20), default="TXT")  # TXT / EXCEL
    created_at  = Column(DateTime, default=datetime.utcnow)

    periodo = relationship("TssPeriodo", back_populates="exportaciones")


# ══════════════════════════════════════════════════════════════════════════════
# BANCOS
# ══════════════════════════════════════════════════════════════════════════════

class CuentaBancaria(Base):
    __tablename__ = "cuentas_bancarias"

    id            = Column(String, primary_key=True, default=gen_uuid)
    empresa_id    = Column(String, ForeignKey("empresa.id"), nullable=False)
    banco         = Column(String(100), nullable=False)
    numero        = Column(String(50),  nullable=False)
    tipo          = Column(String(30),  default=TipoCuenta.CORRIENTE)
    moneda        = Column(String(10),  default="RD$")
    saldo_inicial = Column(Float, default=0.0)
    saldo_actual  = Column(Float, default=0.0)
    activa        = Column(Boolean, default=True)
    notas         = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_cuentas_empresa", "empresa_id"),)

    movimientos = relationship("MovimientoBanco", back_populates="cuenta")


class MovimientoBanco(Base):
    __tablename__ = "movimientos_banco"

    id          = Column(String, primary_key=True, default=gen_uuid)
    empresa_id  = Column(String, ForeignKey("empresa.id"), nullable=False)
    cuenta_id   = Column(String, ForeignKey("cuentas_bancarias.id"), nullable=False)
    fecha       = Column(Date, default=date.today)
    tipo        = Column(String(20), default=TipoMovBanco.CREDITO)
    monto       = Column(Float, nullable=False)
    descripcion = Column(String(300))
    referencia  = Column(String(100))
    factura_id  = Column(String, ForeignKey("facturas.id"), nullable=True)
    pago_id     = Column(String, ForeignKey("pagos.id"),    nullable=True)
    conciliado  = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_movimientos_banco_empresa", "empresa_id"),)

    cuenta = relationship("CuentaBancaria", back_populates="movimientos")


class Conciliacion(Base):
    __tablename__ = "conciliaciones"

    id         = Column(String, primary_key=True, default=gen_uuid)
    empresa_id = Column(String, ForeignKey("empresa.id"), nullable=False)
    cuenta_id  = Column(String, ForeignKey("cuentas_bancarias.id"), nullable=False)
    periodo    = Column(String(7), nullable=False)   # "2025-01"
    saldo_libro = Column(Float, default=0.0)
    saldo_banco = Column(Float, default=0.0)
    diferencia  = Column(Float, default=0.0)
    estatus     = Column(String(20), default="ABIERTA")
    notas       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)
