"""
licencia.py — FactuPro v2.0
Claves de activación de 25 caracteres estilo Windows.
Formato: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
Sin servidor — validación local con HMAC-SHA256.
"""

import hashlib, hmac, json, struct, platform
from datetime import date, timedelta
from pathlib import Path

_MASTER_KEY = b"FactuPro@2025#RD!ERP-DGII-NCF-S3cr3t-K3y-v2"
LICENSE_FILE = "factupro.lic"

# Alfabeto sin caracteres confusos (sin 0, O, 1, I, L) — 31 caracteres
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_BASE = len(ALPHABET)  # 31

TIPO_MAP   = {"TRIAL":0,"MENSUAL":1,"TRIMESTRAL":2,"SEMESTRAL":3,"ANUAL":4,"CUSTOM":5}
TIPO_MAP_R = {v:k for k,v in TIPO_MAP.items()}


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def get_license_path() -> Path:
    return _base_dir() / LICENSE_FILE


def get_machine_id() -> str:
    parts = [platform.node(), platform.system(), platform.machine()]
    try:
        if platform.system() == "Windows":
            import subprocess
            r = subprocess.check_output("wmic csproduct get uuid", shell=True,
                stderr=subprocess.DEVNULL, timeout=3).decode().strip().split("\n")
            hw = r[-1].strip()
            if hw and hw != "UUID": parts.append(hw)
    except Exception: pass
    return hashlib.sha256("|".join(p for p in parts if p).encode()).hexdigest()[:32]


# ── Helpers base32 ────────────────────────────────────────────────────────────

def _to_base32(data: bytes, length: int) -> str:
    num = int.from_bytes(data, 'big')
    chars = []
    for _ in range(length):
        chars.append(ALPHABET[num % _BASE])
        num //= _BASE
    return ''.join(reversed(chars))


# ════════════════════════════════════════════════════════════════════════════
# GENERAR CLAVE (vendedor)
# ════════════════════════════════════════════════════════════════════════════

def generar_clave(dias: int = 30, tipo: str = "MENSUAL") -> str:
    """
    Genera una clave de activación de 25 caracteres.
    Formato: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
    """
    hoy      = date.today()
    tipo_num = TIPO_MAP.get(tipo.upper(), 1)
    anio_off = hoy.year - 2020

    # 4 bytes de datos
    packed = struct.pack(">I",
        (tipo_num  << 28) |
        (dias      << 16) |
        (anio_off  <<  9) |
        (hoy.month <<  5) |
        hoy.day
    )

    # 10 bytes de firma HMAC (14 bytes total caben en 24 chars base-31)
    sig = hmac.new(_MASTER_KEY, packed, hashlib.sha256).digest()[:10]

    # 1 char de checksum rápido
    ck_char = ALPHABET[sum(packed + sig) % _BASE]

    # Codificar 14 bytes en 24 chars base31 + checksum = 25 chars
    key = _to_base32(packed + sig, 24) + ck_char
    return '-'.join(key[i:i+5] for i in range(0, 25, 5))


# ════════════════════════════════════════════════════════════════════════════
# ACTIVAR CON CLAVE (cliente)
# ════════════════════════════════════════════════════════════════════════════

def activar_con_codigo(clave: str, path: Path = None) -> "ResultadoLicencia":
    """
    Valida la clave ingresada por el cliente y guarda factupro.lic.
    """
    resultado = _validar_clave_str(clave)
    if not resultado["ok"]:
        return ResultadoLicencia(ResultadoLicencia.INVALIDO, resultado["error"])

    # Guardar licencia activada
    if path is None: path = get_license_path()
    lic = {
        "data": {
            "tipo":    resultado["tipo"],
            "dias":    resultado["dias"],
            "emitida": resultado["emitida"],
            "vence":   resultado["vence"],
        },
        "clave":    clave.upper().replace(" ", ""),
        "activado": str(date.today()),
    }
    import base64
    path.write_text(
        base64.b64encode(json.dumps(lic).encode()).decode(),
        encoding="utf-8"
    )

    dias = resultado["dias_restantes"]
    return ResultadoLicencia(ResultadoLicencia.VALIDA,
                              f"¡Activado! Licencia válida por {dias} días.",
                              lic["data"])


# ════════════════════════════════════════════════════════════════════════════
# VALIDAR LICENCIA GUARDADA
# ════════════════════════════════════════════════════════════════════════════

def validar_licencia(path: Path = None) -> "ResultadoLicencia":
    if path is None: path = get_license_path()

    if not path.exists():
        return ResultadoLicencia(ResultadoLicencia.NO_ACTIVADO,
                                  "Producto no activado. Ingresa tu clave de licencia.")
    try:
        import base64
        lic = json.loads(base64.b64decode(path.read_text(encoding="utf-8").strip()).decode())
        clave = lic.get("clave", "")
    except Exception:
        return ResultadoLicencia(ResultadoLicencia.INVALIDO, "Archivo de licencia dañado.")

    # Re-validar la clave guardada
    resultado = _validar_clave_str(clave)
    if not resultado["ok"]:
        # Si venció, mostrar mensaje específico
        if "vencida" in resultado.get("error", "").lower() or "vence" in resultado:
            return ResultadoLicencia(ResultadoLicencia.VENCIDA,
                                      resultado["error"], {"vence": resultado.get("vence","")})
        return ResultadoLicencia(ResultadoLicencia.INVALIDO, resultado["error"])

    dias = resultado["dias_restantes"]
    return ResultadoLicencia(ResultadoLicencia.VALIDA,
                              f"Licencia válida — vence {resultado['vence']} ({dias} días).",
                              resultado)


# ════════════════════════════════════════════════════════════════════════════
# VALIDAR CLAVE INTERNAMENTE
# ════════════════════════════════════════════════════════════════════════════

def _validar_clave_str(clave: str) -> dict:
    clean = clave.upper().replace('-', '').replace(' ', '').strip()

    if len(clean) != 25:
        return {"ok": False, "error": f"La clave debe tener 25 caracteres."}

    for c in clean:
        if c not in ALPHABET:
            return {"ok": False, "error": f"Carácter inválido: '{c}'."}

    # Separar datos y checksum
    key_24  = clean[:24]
    ck_char = clean[24]

    # Decodificar 24 chars → 14 bytes
    num = 0
    for c in key_24:
        num = num * _BASE + ALPHABET.index(c)
    raw = num.to_bytes(14, 'big') if num > 0 else b'\x00' * 14

    packed     = raw[:4]
    sig_stored = raw[4:14]

    # Verificar checksum
    if ALPHABET[sum(packed + sig_stored) % _BASE] != ck_char:
        return {"ok": False, "error": "Clave inválida. Verifica que la copiaste correctamente."}

    # Verificar HMAC
    sig_calc = hmac.new(_MASTER_KEY, packed, hashlib.sha256).digest()[:10]
    if not hmac.compare_digest(sig_calc, sig_stored):
        return {"ok": False, "error": "Clave no reconocida. Contacta a tu proveedor."}

    # Extraer datos
    n        = struct.unpack(">I", packed)[0]
    tipo_num = (n >> 28) & 0xF
    dias     = (n >> 16) & 0xFFF
    anio_off = (n >>  9) & 0x7F
    mes      = (n >>  5) & 0xF
    dia      = (n      ) & 0x1F

    tipo    = TIPO_MAP_R.get(tipo_num, "DESCONOCIDO")
    emitida = date(2020 + anio_off, mes, dia)
    vence   = emitida + timedelta(days=dias)
    hoy     = date.today()

    if hoy > vence:
        return {"ok": False,
                "error": f"Clave vencida el {vence}. Contacta a tu proveedor.",
                "vence": str(vence), "tipo": tipo, "emitida": str(emitida)}

    return {
        "ok": True, "tipo": tipo, "dias": dias,
        "emitida": str(emitida), "vence": str(vence),
        "dias_restantes": (vence - hoy).days,
    }


# ════════════════════════════════════════════════════════════════════════════
# RESULTADO
# ════════════════════════════════════════════════════════════════════════════

class ResultadoLicencia:
    VALIDA      = "VALIDA"
    VENCIDA     = "VENCIDA"
    INVALIDO    = "INVALIDO"
    NO_ACTIVADO = "NO_ACTIVADO"

    def __init__(self, estado: str, mensaje: str = "", data: dict = None):
        self.estado  = estado
        self.mensaje = mensaje
        self.data    = data or {}
        self.ok      = (estado == self.VALIDA)

    def dias_restantes(self) -> int:
        v = self.data.get("vence") or self.data.get("dias_restantes")
        if isinstance(v, int): return v
        if isinstance(v, str):
            try: return max(0, (date.fromisoformat(v) - date.today()).days)
            except: pass
        return 0

    def vence_str(self)   -> str: return str(self.data.get("vence",   "—"))
    def cliente_str(self) -> str: return str(self.data.get("cliente", "—"))
    def tipo_str(self)    -> str: return str(self.data.get("tipo",    "—"))
    def serial_str(self)  -> str: return str(self.data.get("serial",  "—"))


def instalar_trial_si_no_existe(): pass
