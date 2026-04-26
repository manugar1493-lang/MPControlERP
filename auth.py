"""
auth.py — FactuPro v2.0
Autenticación JWT + bcrypt · Multi-empresa · Roles
Instalar: pip install PyJWT bcrypt
"""

import hashlib
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.orm import Session

try:
    import jwt
    import bcrypt
    AUTH_OK = True
except ImportError:
    AUTH_OK = False

from models import Usuario, Sesion, Empresa, gen_uuid

# ── Configuración ─────────────────────────────────────────────────────────────
SECRET_KEY     = os.getenv("SECRET_KEY", "factupro-secret-cambia-en-produccion")
ALGORITHM      = "HS256"
TOKEN_HOURS    = int(os.getenv("TOKEN_HOURS", "8"))
MAX_LOGIN_FAIL = 5   # intentos máximos


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORDS
# ══════════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    if not AUTH_OK:
        raise RuntimeError("Instala: pip install PyJWT bcrypt")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not AUTH_OK:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# TOKENS JWT
# ══════════════════════════════════════════════════════════════════════════════

def create_token(usuario_id: str, empresa_id: str, rol: str, nombre: str) -> dict:
    if not AUTH_OK:
        raise RuntimeError("Instala: pip install PyJWT bcrypt")
    expira = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    payload = {
        "sub":        usuario_id,
        "empresa_id": empresa_id,
        "rol":        rol,
        "nombre":     nombre,
        "exp":        expira,
        "iat":        datetime.utcnow(),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "expira_en":    expira.isoformat(),
        "rol":          rol,
        "nombre":       nombre,
        "empresa_id":   empresa_id,
    }


def decode_token(token: str) -> dict:
    if not AUTH_OK:
        raise HTTPException(status_code=503, detail="Módulo auth no disponible")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado. Inicia sesión nuevamente.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY — get_current_user
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user(authorization: str = Header(default=None)):
    """
    Inyecta el usuario autenticado en cualquier endpoint.
    Uso: user = Depends(get_current_user)
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Token requerido.")
    token = authorization.replace("Bearer ", "").strip()
    return decode_token(token)


def require_rol(*roles):
    """
    Decorador de rol. Uso:
        user = Depends(require_rol("ADMIN", "SUPERVISOR"))
    """
    def dependency(user=Depends(get_current_user)):
        if user.get("rol") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Se requiere rol: {', '.join(roles)}"
            )
        return user
    return dependency


# Shortcuts
admin_only      = require_rol("ADMIN")
admin_supervisor = require_rol("ADMIN", "SUPERVISOR")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER — endpoints de autenticación
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginSchema(BaseModel):
    email:    str
    password: str


class UsuarioCreateSchema(BaseModel):
    nombre:     str
    email:      str
    password:   str
    rol:        str = "OPERADOR"
    empresa_id: Optional[str] = None   # solo ADMIN puede especificarla


class CambiarPasswordSchema(BaseModel):
    password_actual: str
    password_nuevo:  str


# ── Login ─────────────────────────────────────────────────────────────────────
@router.post("/login")
def login(data: LoginSchema, db: Session = Depends(lambda: None)):
    # Este endpoint recibe db via Depends(get_db) en main.py
    # Se define aquí el handler, el Depends real se conecta en main.py
    pass   # Ver implementación en main.py → _login_handler


def login_handler(data: LoginSchema, db: Session):
    usuario = db.query(Usuario).filter_by(email=data.email, activo=True).first()
    if not usuario or not verify_password(data.password, usuario.password):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos.")

    empresa = db.query(Empresa).get(usuario.empresa_id)
    if not empresa or not empresa.activa:
        raise HTTPException(status_code=403, detail="Empresa inactiva o no encontrada.")

    return create_token(
        usuario_id=usuario.id,
        empresa_id=usuario.empresa_id,
        rol=usuario.rol,
        nombre=usuario.nombre,
    )


# ── Perfil ────────────────────────────────────────────────────────────────────
def perfil_handler(user: dict, db: Session):
    usuario = db.query(Usuario).get(user["sub"])
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")
    empresa = db.query(Empresa).get(usuario.empresa_id)
    return {
        "id":         usuario.id,
        "nombre":     usuario.nombre,
        "email":      usuario.email,
        "rol":        usuario.rol,
        "empresa_id": usuario.empresa_id,
        "empresa":    empresa.nombre if empresa else None,
        "logo":       empresa.logo_path if empresa else None,
    }


# ── Cambiar password ──────────────────────────────────────────────────────────
def cambiar_password_handler(data: CambiarPasswordSchema, user: dict, db: Session):
    usuario = db.query(Usuario).get(user["sub"])
    if not verify_password(data.password_actual, usuario.password):
        raise HTTPException(400, "Contraseña actual incorrecta.")
    usuario.password   = hash_password(data.password_nuevo)
    usuario.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "mensaje": "Contraseña actualizada correctamente."}


# ── Crear usuario (solo ADMIN) ────────────────────────────────────────────────
def crear_usuario_handler(data: UsuarioCreateSchema, user: dict, db: Session):
    empresa_id = user["empresa_id"]   # siempre de la empresa del admin

    # Verificar email único en la empresa
    existe = db.query(Usuario).filter_by(
        empresa_id=empresa_id, email=data.email
    ).first()
    if existe:
        raise HTTPException(400, f"Ya existe un usuario con email {data.email}")

    nuevo = Usuario(
        id=gen_uuid(),
        empresa_id=empresa_id,
        nombre=data.nombre,
        email=data.email,
        password=hash_password(data.password),
        rol=data.rol,
        activo=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {
        "id":     nuevo.id,
        "nombre": nuevo.nombre,
        "email":  nuevo.email,
        "rol":    nuevo.rol,
    }


# ── Listar usuarios (ADMIN) ───────────────────────────────────────────────────
def listar_usuarios_handler(user: dict, db: Session):
    usuarios = db.query(Usuario).filter_by(empresa_id=user["empresa_id"]).all()
    return [
        {"id": u.id, "nombre": u.nombre, "email": u.email,
         "rol": u.rol, "activo": u.activo}
        for u in usuarios
    ]


# ── Seed admin inicial ────────────────────────────────────────────────────────
def seed_admin(db: Session, empresa_id: str):
    """Crea el usuario admin por defecto si no existe ninguno."""
    if db.query(Usuario).filter_by(empresa_id=empresa_id).count() == 0:
        admin = Usuario(
            id=gen_uuid(),
            empresa_id=empresa_id,
            nombre="Administrador",
            email="admin@factupro.com",
            password=hash_password("Admin123!"),
            rol="ADMIN",
            activo=True,
        )
        db.add(admin)
        db.commit()
        print("[FactuPro] Usuario admin creado: admin@factupro.com / Admin123!")
        print("[FactuPro] ¡CAMBIA LA CONTRASEÑA después del primer login!")
