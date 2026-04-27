"""
migrate_db.py — MPControlERP safe database migration script
Run this once to bring any existing factupro.db up to the current schema.
Usage:  python migrate_db.py [path/to/factupro.db]
"""

import sqlite3
import sys
import os
from datetime import datetime

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "factupro.db"

if not os.path.exists(DB_PATH):
    print(f"ERROR: Database not found at '{DB_PATH}'")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def existing_tables():
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in cur.fetchall()}

def existing_columns(table):
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}

def add_column(table, col, col_def):
    if col not in existing_columns(table):
        print(f"  + {table}.{col}")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    else:
        print(f"  ✓ {table}.{col} already exists")

def create_table(name, ddl):
    if name not in existing_tables():
        print(f"  + CREATE TABLE {name}")
        cur.execute(ddl)
    else:
        print(f"  ✓ table {name} already exists")

# ─── Migrations ───────────────────────────────────────────────────────────────

print("\n[1/6] empresa — add 'activa' column")
add_column("empresa", "activa", "INTEGER NOT NULL DEFAULT 1")

print("\n[2/6] clientes — add 'empresa_id' column")
add_column("clientes", "empresa_id", "TEXT")

print("\n[3/6] proveedores — add 'empresa_id' column")
add_column("proveedores", "empresa_id", "TEXT")

print("\n[4/6] productos — add 'empresa_id' column")
add_column("productos", "empresa_id", "TEXT")

print("\n[5/6] empleados — table + missing columns")
create_table("empleados", """
    CREATE TABLE empleados (
        id              TEXT PRIMARY KEY,
        empresa_id      TEXT NOT NULL,
        cedula          TEXT,
        nombre          TEXT NOT NULL,
        apellidos       TEXT,
        email           TEXT,
        telefono        TEXT,
        direccion       TEXT,
        fecha_ingreso   TEXT,
        fecha_salida    TEXT,
        tipo_contrato   TEXT DEFAULT 'INDEFINIDO',
        cargo           TEXT,
        departamento    TEXT,
        salario_base    REAL DEFAULT 0.0,
        comision_pct    REAL DEFAULT 0.0,
        afp_id          INTEGER DEFAULT 1,
        sfs_id          INTEGER DEFAULT 1,
        nss             TEXT,
        activo          INTEGER DEFAULT 1,
        notas           TEXT,
        created_at      TEXT,
        updated_at      TEXT
    )
""")
# Add comision_pct if table existed but column is missing
add_column("empleados", "comision_pct", "REAL DEFAULT 0.0")

print("\n[6/6] cliente_documentos — new table")
create_table("cliente_documentos", """
    CREATE TABLE cliente_documentos (
        id              TEXT PRIMARY KEY,
        empresa_id      TEXT NOT NULL,
        cliente_id      TEXT NOT NULL,
        nombre_archivo  TEXT NOT NULL,
        tamano_kb       INTEGER DEFAULT 0,
        contenido       BLOB NOT NULL,
        created_at      TEXT
    )
""")
# Index for fast lookup by client
cur.execute("""
    CREATE INDEX IF NOT EXISTS ix_cliente_docs_cliente
    ON cliente_documentos(cliente_id)
""")

# ─── Backfill empresa_id from existing data ───────────────────────────────────
# If there is exactly one empresa row we can safely fill any NULL empresa_id values.
print("\n[bonus] Backfilling NULL empresa_id values (if safe)…")
cur.execute("SELECT id FROM empresa LIMIT 2")
rows = cur.fetchall()
if len(rows) == 1:
    eid = rows[0][0]
    for table in ("clientes", "proveedores", "productos", "empleados"):
        if "empresa_id" in existing_columns(table):
            cur.execute(f"UPDATE {table} SET empresa_id=? WHERE empresa_id IS NULL", (eid,))
            n = cur.rowcount
            if n:
                print(f"  ✓ {table}: filled {n} row(s) with empresa_id={eid[:8]}…")
else:
    print("  ⚠  Multiple or zero empresa rows — skipping auto-backfill.")
    print("     Set empresa_id manually if needed.")

# ─── Done ─────────────────────────────────────────────────────────────────────
conn.commit()
conn.close()
print(f"\n✅  Migration complete → {DB_PATH}\n")
