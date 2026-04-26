"""
bancos.py — FactuPro v2.1
Módulo de Bancos: cuentas, movimientos, conciliación (CORREGIDO MONEDA)
"""

from datetime import date
from typing import Optional
from fastapi import HTTPException
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from models import CuentaBancaria, MovimientoBanco, Conciliacion, gen_uuid


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

MONEDAS_VALIDAS = ["DOP", "USD"]


def normalizar_moneda(moneda: str) -> str:
    """Convierte valores como RD$ → DOP"""
    if not moneda:
        return "DOP"
    moneda = moneda.upper().strip()
    if moneda in ["RD$", "DOP"]:
        return "DOP"
    if moneda == "USD":
        return "USD"
    return moneda


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class CuentaSchema(BaseModel):
    banco: str
    numero: str
    tipo: str = "CORRIENTE"
    moneda: str = "DOP"
    saldo_inicial: float = 0.0
    notas: Optional[str] = None

    @validator("moneda")
    def validar_moneda(cls, v):
        v = normalizar_moneda(v)
        if v not in MONEDAS_VALIDAS:
            raise ValueError("Moneda inválida. Use DOP o USD")
        return v


class MovimientoSchema(BaseModel):
    cuenta_id: str
    fecha: Optional[str] = None
    tipo: str  # DEBITO / CREDITO
    monto: float
    descripcion: Optional[str] = None
    referencia: Optional[str] = None
    factura_id: Optional[str] = None
    pago_id: Optional[str] = None

    @validator("monto")
    def validar_monto(cls, v):
        if v <= 0:
            raise ValueError("El monto debe ser mayor a 0")
        return v

    @validator("tipo")
    def validar_tipo(cls, v):
        v = v.upper()
        if v not in ["DEBITO", "CREDITO"]:
            raise ValueError("Tipo debe ser DEBITO o CREDITO")
        return v


class ConciliacionSchema(BaseModel):
    cuenta_id: str
    periodo: str
    saldo_banco: float
    notas: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# CUENTAS
# ══════════════════════════════════════════════════════════════════════════════

def crear_cuenta(data: CuentaSchema, empresa_id: str, db: Session) -> dict:
    moneda = normalizar_moneda(data.moneda)
    cuenta = CuentaBancaria(
        id=gen_uuid(),
        empresa_id=empresa_id,
        banco=data.banco,
        numero=data.numero,
        tipo=data.tipo,
        moneda=moneda,
        saldo_inicial=data.saldo_inicial,
        saldo_actual=data.saldo_inicial,
        notas=data.notas,
        activa=True,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return _serializar_cuenta(cuenta)


def listar_cuentas(empresa_id: str, db: Session) -> list:
    cuentas = db.query(CuentaBancaria).filter_by(empresa_id=empresa_id, activa=True).all()
    return [_serializar_cuenta(c) for c in cuentas]


def _serializar_cuenta(c: CuentaBancaria) -> dict:
    return {
        "id": c.id, "banco": c.banco, "numero": c.numero,
        "tipo": c.tipo, "moneda": c.moneda,
        "saldo_inicial": c.saldo_inicial, "saldo_actual": c.saldo_actual,
        "activa": c.activa, "notas": c.notas,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MOVIMIENTOS
# ══════════════════════════════════════════════════════════════════════════════

def registrar_movimiento(data: MovimientoSchema, empresa_id: str, db: Session) -> dict:
    cuenta = db.query(CuentaBancaria).filter_by(
        id=data.cuenta_id, empresa_id=empresa_id
    ).first()
    if not cuenta:
        raise HTTPException(404, "Cuenta bancaria no encontrada")

    mov = MovimientoBanco(
        id=gen_uuid(),
        empresa_id=empresa_id,
        cuenta_id=data.cuenta_id,
        fecha=date.fromisoformat(data.fecha) if data.fecha else date.today(),
        tipo=data.tipo,
        monto=data.monto,
        descripcion=data.descripcion,
        referencia=data.referencia,
        factura_id=data.factura_id,
        pago_id=data.pago_id,
        conciliado=False,
    )
    db.add(mov)

    if data.tipo == "CREDITO":
        cuenta.saldo_actual += data.monto
    else:
        cuenta.saldo_actual -= data.monto

    db.commit()
    db.refresh(mov)
    return _serializar_movimiento(mov)


def listar_movimientos(
    empresa_id: str, db: Session,
    cuenta_id: Optional[str] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
) -> list:
    q = db.query(MovimientoBanco).filter_by(empresa_id=empresa_id)
    if cuenta_id:
        q = q.filter_by(cuenta_id=cuenta_id)
    if desde:
        q = q.filter(MovimientoBanco.fecha >= date.fromisoformat(desde))
    if hasta:
        q = q.filter(MovimientoBanco.fecha <= date.fromisoformat(hasta))
    return [_serializar_movimiento(m) for m in q.order_by(MovimientoBanco.fecha.desc()).all()]


def _serializar_movimiento(m: MovimientoBanco) -> dict:
    return {
        "id": m.id, "cuenta_id": m.cuenta_id,
        "fecha": str(m.fecha), "tipo": m.tipo,
        "monto": m.monto, "descripcion": m.descripcion,
        "referencia": m.referencia, "conciliado": m.conciliado,
        "factura_id": m.factura_id, "pago_id": m.pago_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CONCILIACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def iniciar_conciliacion(data: ConciliacionSchema, empresa_id: str, db: Session) -> dict:
    cuenta = db.query(CuentaBancaria).filter_by(
        id=data.cuenta_id, empresa_id=empresa_id
    ).first()
    if not cuenta:
        raise HTTPException(404, "Cuenta no encontrada")
    conc = Conciliacion(
        id=gen_uuid(), empresa_id=empresa_id,
        cuenta_id=data.cuenta_id, periodo=data.periodo,
        saldo_libro=cuenta.saldo_actual,
        saldo_banco=data.saldo_banco,
        diferencia=round(data.saldo_banco - cuenta.saldo_actual, 2),
        estatus="ABIERTA", notas=data.notas,
    )
    db.add(conc)
    db.commit()
    db.refresh(conc)
    return {
        "id": conc.id, "periodo": conc.periodo,
        "saldo_libro": conc.saldo_libro,
        "saldo_banco": conc.saldo_banco,
        "diferencia":  conc.diferencia,
        "estatus":     conc.estatus,
    }


def conciliar_movimiento(mov_id: str, empresa_id: str, db: Session) -> dict:
    mov = db.query(MovimientoBanco).filter_by(id=mov_id, empresa_id=empresa_id).first()
    if not mov:
        raise HTTPException(404, "Movimiento no encontrado")
    mov.conciliado = True
    db.commit()
    return {"ok": True, "movimiento_id": mov_id, "conciliado": True}


def resumen_banco(empresa_id: str, db: Session) -> list:
    cuentas = db.query(CuentaBancaria).filter_by(empresa_id=empresa_id, activa=True).all()
    resultado = []
    for c in cuentas:
        total_creditos = sum(
            m.monto for m in db.query(MovimientoBanco)
            .filter_by(cuenta_id=c.id, tipo="CREDITO").all()
        )
        total_debitos = sum(
            m.monto for m in db.query(MovimientoBanco)
            .filter_by(cuenta_id=c.id, tipo="DEBITO").all()
        )
        resultado.append({
            "cuenta_id": c.id, "banco": c.banco, "numero": c.numero,
            "tipo": c.tipo, "moneda": c.moneda,
            "saldo_actual": c.saldo_actual,
            "total_creditos": round(total_creditos, 2),
            "total_debitos":  round(total_debitos, 2),
        })
    return resultado
