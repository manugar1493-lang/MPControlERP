"""
nomina.py — FactuPro v2.0
Módulo de Nómina: AFP, SFS, ISR (escala DGII 2024), TSS
"""

from datetime import datetime, date
from typing import List, Optional
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import (
    Empleado, Nomina, NominaDetalle, TssPeriodo, TssAporte,
    TssExportacion, gen_uuid
)


# ══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS LEGALES RD 2024/2025
# ══════════════════════════════════════════════════════════════════════════════

TASAS = {
    # Empleado
    "afp_emp":     0.0287,
    "sfs_emp":     0.0304,
    # Patronal
    "afp_pat":     0.0710,
    "sfs_pat":     0.0709,
    "infotep":     0.0100,
    "arl":         0.0120,
}

# Escala ISR anual DGII 2024 (en RD$)
ISR_TRAMOS = [
    (0,           416_220.00,  0.00,  0.0),
    (416_220.01,  624_329.00,  0.00,  0.15),
    (624_329.01,  867_123.00,  31_216.20, 0.20),
    (867_123.01,  float("inf"), 79_776.80, 0.25),
]


# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULOS CORE
# ══════════════════════════════════════════════════════════════════════════════

def calcular_isr_anual(renta_anual: float) -> float:
    """Calcula ISR anual según escala DGII 2024."""
    for desde, hasta, cuota_fija, tasa in ISR_TRAMOS:
        if desde <= renta_anual <= hasta:
            return cuota_fija + (renta_anual - desde) * tasa
    return 0.0


def calcular_nomina_empleado(
    salario_base: float,
    bonificacion: float = 0.0,
    horas_extra: float = 0.0,
    valor_hora: float = 0.0,
    otros_ingresos: float = 0.0,
    otros_descuentos: float = 0.0,
) -> dict:
    """
    Cálculo completo de nómina para un empleado.
    Retorna todos los conceptos desglosados.
    """
    monto_extra    = horas_extra * valor_hora
    total_ingresos = salario_base + bonificacion + monto_extra + otros_ingresos

    # ── Deducciones del empleado ──────────────────────────────────────────────
    afp_emp = total_ingresos * TASAS["afp_emp"]
    sfs_emp = total_ingresos * TASAS["sfs_emp"]
    total_ded_previas = afp_emp + sfs_emp

    # ── ISR mensual (base: ingresos - AFP - SFS anualizados) ─────────────────
    renta_anual = (total_ingresos - total_ded_previas) * 12
    isr_anual   = calcular_isr_anual(renta_anual)
    isr_mensual = isr_anual / 12

    total_deducciones = total_ded_previas + isr_mensual + otros_descuentos
    salario_neto      = total_ingresos - total_deducciones

    # ── Aportes patronales (costo empresa, no se descuenta al empleado) ───────
    afp_pat     = total_ingresos * TASAS["afp_pat"]
    sfs_pat     = total_ingresos * TASAS["sfs_pat"]
    infotep_pat = total_ingresos * TASAS["infotep"]
    costo_total = total_ingresos + afp_pat + sfs_pat + infotep_pat

    return {
        # Ingresos
        "salario_base":        round(salario_base, 2),
        "bonificacion":        round(bonificacion, 2),
        "horas_extra":         round(horas_extra, 2),
        "monto_extra":         round(monto_extra, 2),
        "otros_ingresos":      round(otros_ingresos, 2),
        "total_ingresos":      round(total_ingresos, 2),
        # Deducciones empleado
        "afp_empleado":        round(afp_emp, 2),
        "sfs_empleado":        round(sfs_emp, 2),
        "isr_mensual":         round(isr_mensual, 2),
        "otros_descuentos":    round(otros_descuentos, 2),
        "total_deducciones":   round(total_deducciones, 2),
        # Neto
        "salario_neto":        round(salario_neto, 2),
        # Patronal
        "afp_patronal":        round(afp_pat, 2),
        "sfs_patronal":        round(sfs_pat, 2),
        "infotep":             round(infotep_pat, 2),
        "costo_total_empresa": round(costo_total, 2),
        # TSS
        "salario_cotizable":   round(total_ingresos, 2),
        "renta_anual":         round(renta_anual, 2),
        "isr_anual":           round(isr_anual, 2),
    }


def calcular_aportes_tss(salario_cotizable: float) -> dict:
    """Calcula aportes TSS independientemente de la nómina."""
    return {
        "salario_cotizable": round(salario_cotizable, 2),
        "afp_empleado":      round(salario_cotizable * TASAS["afp_emp"], 2),
        "afp_patronal":      round(salario_cotizable * TASAS["afp_pat"], 2),
        "sfs_empleado":      round(salario_cotizable * TASAS["sfs_emp"], 2),
        "sfs_patronal":      round(salario_cotizable * TASAS["sfs_pat"], 2),
        "arl_patronal":      round(salario_cotizable * TASAS["arl"],     2),
        "total_empleado":    round(salario_cotizable * (TASAS["afp_emp"] + TASAS["sfs_emp"]), 2),
        "total_patronal":    round(salario_cotizable * (TASAS["afp_pat"] + TASAS["sfs_pat"] + TASAS["arl"]), 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS PYDANTIC
# ══════════════════════════════════════════════════════════════════════════════

class EmpleadoSchema(BaseModel):
    cedula:         str
    nombre:         str
    apellidos:      Optional[str] = None
    email:          Optional[str] = None
    telefono:       Optional[str] = None
    direccion:      Optional[str] = None
    fecha_ingreso:  Optional[str] = None
    tipo_contrato:  str = "INDEFINIDO"
    cargo:          Optional[str] = None
    departamento:   Optional[str] = None
    salario_base:   float
    nss:            Optional[str] = None
    afp_id:         Optional[str] = None
    sfs_id:         Optional[str] = None
    notas:          Optional[str] = None


class NominaCreateSchema(BaseModel):
    periodo:     str        # "2025-01"
    descripcion: Optional[str] = None
    fecha_pago:  Optional[str] = None


class NominaDetalleInputSchema(BaseModel):
    empleado_id:      str
    bonificacion:     float = 0.0
    horas_extra:      float = 0.0
    valor_hora:       float = 0.0
    otros_ingresos:   float = 0.0
    otros_descuentos: float = 0.0


class SimularNominaSchema(BaseModel):
    salario_base:     float
    bonificacion:     float = 0.0
    horas_extra:      float = 0.0
    valor_hora:       float = 0.0
    otros_ingresos:   float = 0.0
    otros_descuentos: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# HANDLERS DE NÓMINA
# ══════════════════════════════════════════════════════════════════════════════

def crear_empleado(data: EmpleadoSchema, empresa_id: str, db: Session) -> dict:
    existe = db.query(Empleado).filter_by(
        empresa_id=empresa_id, cedula=data.cedula
    ).first()
    if existe:
        raise HTTPException(400, f"Ya existe empleado con cédula {data.cedula}")

    emp = Empleado(
        id=gen_uuid(),
        empresa_id=empresa_id,
        cedula=data.cedula,
        nombre=data.nombre,
        apellidos=data.apellidos,
        email=data.email,
        telefono=data.telefono,
        direccion=data.direccion,
        fecha_ingreso=date.fromisoformat(data.fecha_ingreso) if data.fecha_ingreso else date.today(),
        tipo_contrato=data.tipo_contrato,
        cargo=data.cargo,
        departamento=data.departamento,
        salario_base=data.salario_base,
        nss=data.nss,
        afp_id=data.afp_id,
        sfs_id=data.sfs_id,
        notas=data.notas,
        activo=True,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return _serializar_empleado(emp)


def listar_empleados(empresa_id: str, db: Session, activo: bool = True) -> list:
    q = db.query(Empleado).filter_by(empresa_id=empresa_id)
    if activo is not None:
        q = q.filter_by(activo=activo)
    return [_serializar_empleado(e) for e in q.order_by(Empleado.nombre).all()]


def _serializar_empleado(e: Empleado) -> dict:
    return {
        "id": e.id, "cedula": e.cedula, "nombre": e.nombre,
        "apellidos": e.apellidos, "cargo": e.cargo,
        "departamento": e.departamento, "salario_base": e.salario_base,
        "tipo_contrato": e.tipo_contrato, "fecha_ingreso": str(e.fecha_ingreso) if e.fecha_ingreso else None,
        "nss": e.nss, "afp_id": e.afp_id, "sfs_id": e.sfs_id,
        "activo": e.activo, "email": e.email, "telefono": e.telefono,
    }


def crear_nomina(data: NominaCreateSchema, empresa_id: str, db: Session) -> dict:
    existe = db.query(Nomina).filter_by(empresa_id=empresa_id, periodo=data.periodo).first()
    if existe:
        raise HTTPException(400, f"Ya existe nómina para el período {data.periodo}")

    nom = Nomina(
        id=gen_uuid(),
        empresa_id=empresa_id,
        periodo=data.periodo,
        descripcion=data.descripcion or f"Nómina {data.periodo}",
        fecha_pago=date.fromisoformat(data.fecha_pago) if data.fecha_pago else None,
        estatus="BORRADOR",
    )
    db.add(nom)
    db.commit()
    db.refresh(nom)
    return {"id": nom.id, "periodo": nom.periodo, "estatus": nom.estatus}


def procesar_nomina(nomina_id: str, empresa_id: str, db: Session) -> dict:
    """
    Calcula todos los conceptos para todos los empleados activos
    y guarda el detalle. Cambia estatus a PROCESADA.
    """
    nom = db.query(Nomina).filter_by(id=nomina_id, empresa_id=empresa_id).first()
    if not nom:
        raise HTTPException(404, "Nómina no encontrada")
    if nom.estatus != "BORRADOR":
        raise HTTPException(400, "Solo se puede procesar una nómina en estado BORRADOR")

    # Borrar detalles previos si los hay
    db.query(NominaDetalle).filter_by(nomina_id=nomina_id).delete()

    empleados = db.query(Empleado).filter_by(empresa_id=empresa_id, activo=True).all()
    total_bruto = total_ded = total_neto = 0.0

    for emp in empleados:
        calc = calcular_nomina_empleado(emp.salario_base)
        det  = NominaDetalle(
            id=gen_uuid(),
            nomina_id=nomina_id,
            empleado_id=emp.id,
            salario_base=emp.salario_base,
            total_ingresos=calc["total_ingresos"],
            afp_empleado=calc["afp_empleado"],
            sfs_empleado=calc["sfs_empleado"],
            isr_mensual=calc["isr_mensual"],
            otros_descuentos=0.0,
            total_deducciones=calc["total_deducciones"],
            afp_patronal=calc["afp_patronal"],
            sfs_patronal=calc["sfs_patronal"],
            infotep=calc["infotep"],
            salario_neto=calc["salario_neto"],
            horas_extra=0.0,
            monto_extra=0.0,
            bonificacion=0.0,
            otros_ingresos=0.0,
        )
        db.add(det)
        total_bruto += calc["total_ingresos"]
        total_ded   += calc["total_deducciones"]
        total_neto  += calc["salario_neto"]

    nom.total_bruto       = round(total_bruto, 2)
    nom.total_deducciones = round(total_ded, 2)
    nom.total_neto        = round(total_neto, 2)
    nom.estatus           = "PROCESADA"
    nom.updated_at        = datetime.utcnow()
    db.commit()

    return {
        "id": nom.id, "periodo": nom.periodo, "estatus": nom.estatus,
        "empleados": len(empleados),
        "total_bruto": nom.total_bruto,
        "total_deducciones": nom.total_deducciones,
        "total_neto": nom.total_neto,
    }


def detalle_nomina(nomina_id: str, empresa_id: str, db: Session) -> dict:
    nom = db.query(Nomina).filter_by(id=nomina_id, empresa_id=empresa_id).first()
    if not nom:
        raise HTTPException(404, "Nómina no encontrada")

    detalles = (
        db.query(NominaDetalle, Empleado)
        .join(Empleado, NominaDetalle.empleado_id == Empleado.id)
        .filter(NominaDetalle.nomina_id == nomina_id)
        .all()
    )

    filas = []
    for d, e in detalles:
        filas.append({
            "empleado_id":      e.id,
            "cedula":           e.cedula,
            "nombre":           f"{e.nombre} {e.apellidos or ''}".strip(),
            "cargo":            e.cargo or "—",
            "salario_base":     float(d.salario_base or 0),
            "total_ingresos":   float(d.total_ingresos or 0),
            "afp_empleado":     float(d.afp_empleado or 0),
            "sfs_empleado":     float(d.sfs_empleado or 0),
            "isr_mensual":      float(d.isr_mensual or 0),
            "otros_descuentos": float(d.otros_descuentos or 0),
            "total_deducciones":float(d.total_deducciones or 0),
            "salario_neto":     float(d.salario_neto or 0),
            "afp_patronal":     float(d.afp_patronal or 0),
            "sfs_patronal":     float(d.sfs_patronal or 0),
            "infotep":          float(d.infotep or 0),
        })

    return {
        "nomina": {
            "id": nom.id, "periodo": nom.periodo, "estatus": nom.estatus,
            "fecha_pago": str(nom.fecha_pago) if nom.fecha_pago else None,
            "total_bruto": nom.total_bruto,
            "total_deducciones": nom.total_deducciones,
            "total_neto": nom.total_neto,
        },
        "detalles": filas,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TSS — GENERACIÓN DE ARCHIVO
# ══════════════════════════════════════════════════════════════════════════════

def generar_tss(nomina_id: str, empresa_id: str, db: Session) -> dict:
    """Genera los registros TSS a partir de la nómina procesada."""
    from models import Empresa as EmpresaModel

    nom = db.query(Nomina).filter_by(id=nomina_id, empresa_id=empresa_id).first()
    if not nom:
        raise HTTPException(404, "Nómina no encontrada")
    if nom.estatus not in ("PROCESADA", "PAGADA"):
        raise HTTPException(400, "La nómina debe estar PROCESADA antes de generar TSS")

    anio, mes = int(nom.periodo[:4]), int(nom.periodo[5:7])

    # Crear o recuperar período TSS
    periodo = db.query(TssPeriodo).filter_by(
        empresa_id=empresa_id, anio=anio, mes=mes
    ).first()
    if not periodo:
        periodo = TssPeriodo(
            id=gen_uuid(), empresa_id=empresa_id,
            anio=anio, mes=mes, nomina_id=nomina_id
        )
        db.add(periodo)
        db.flush()

    # Borrar aportes previos del período
    db.query(TssAporte).filter_by(periodo_id=periodo.id).delete()

    detalles = (
        db.query(NominaDetalle, Empleado)
        .join(Empleado, NominaDetalle.empleado_id == Empleado.id)
        .filter(NominaDetalle.nomina_id == nomina_id)
        .all()
    )

    empresa = db.query(EmpresaModel).get(empresa_id)
    lineas_txt = []

    for d, e in detalles:
        tss = calcular_aportes_tss(d.total_ingresos)
        aporte = TssAporte(
            id=gen_uuid(),
            periodo_id=periodo.id,
            empleado_id=e.id,
            salario_cotizable=tss["salario_cotizable"],
            afp_empleado=tss["afp_empleado"],
            afp_patronal=tss["afp_patronal"],
            sfs_empleado=tss["sfs_empleado"],
            sfs_patronal=tss["sfs_patronal"],
            arl_patronal=tss["arl_patronal"],
            total_empleado=tss["total_empleado"],
            total_patronal=tss["total_patronal"],
        )
        db.add(aporte)

        # Formato archivo plano TSS
        rnc_emp = (empresa.rnc or "").ljust(11)[:11]
        nss     = (e.nss or "").ljust(11)[:11]
        lineas_txt.append(
            f"{rnc_emp}{nss}"
            f"{tss['salario_cotizable']:>12.2f}"
            f"{tss['afp_empleado']:>10.2f}"
            f"{tss['afp_patronal']:>10.2f}"
            f"{tss['sfs_empleado']:>10.2f}"
            f"{tss['sfs_patronal']:>10.2f}"
        )

    periodo.estatus = "ENVIADO"
    db.commit()

    return {
        "periodo_id": periodo.id,
        "periodo":    f"{anio}-{mes:02d}",
        "empleados":  len(detalles),
        "archivo_txt": "\n".join(lineas_txt),
        "resumen": {
            "total_afp_empleado": round(sum(d.afp_empleado for d, _ in detalles), 2),
            "total_sfs_empleado": round(sum(d.sfs_empleado for d, _ in detalles), 2),
        }
    }
