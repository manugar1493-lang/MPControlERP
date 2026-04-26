"""
generar_licencia.py — FactuPro
Herramienta EXCLUSIVA del vendedor.
NO distribuir al cliente.
"""
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from licencia import generar_clave, _validar_clave_str

def sep(c="─", n=52): print(c * n)

def main():
    print()
    sep("═")
    print("  FactuPro — Generador de Claves de Licencia")
    sep("═")
    print()
    print("  1. Generar clave para un cliente")
    print("  2. Validar una clave existente")
    print()
    op = input("Opción [1/2]: ").strip()

    if op == "2":
        clave = input("\nIngresa la clave a validar: ").strip()
        r = _validar_clave_str(clave)
        print()
        sep()
        if r["ok"]:
            print(f"  ✅ CLAVE VÁLIDA")
            print(f"  Tipo:    {r['tipo']}")
            print(f"  Vence:   {r['vence']}")
            print(f"  Días:    {r['dias_restantes']} restantes")
        else:
            print(f"  ❌ CLAVE INVÁLIDA")
            print(f"  Error: {r['error']}")
        sep()
        input("\nEnter para salir...")
        return

    print()
    sep()
    print("  NUEVA CLAVE DE LICENCIA")
    sep()
    print()
    print("  Tipo de licencia:")
    print("   1. MENSUAL      —  30 días")
    print("   2. TRIMESTRAL   —  90 días")
    print("   3. SEMESTRAL    — 180 días")
    print("   4. ANUAL        — 365 días")
    print("   5. PRUEBA       —  15 días")
    print("   6. PERSONALIZADO")
    print()
    op2 = input("Opción [1-6]: ").strip()

    tipos = {"1":("MENSUAL",30),"2":("TRIMESTRAL",90),"3":("SEMESTRAL",180),
             "4":("ANUAL",365),"5":("TRIAL",15)}

    if op2 == "6":
        tipo = "CUSTOM"
        dias = int(input("¿Cuántos días? ").strip() or "30")
    else:
        tipo, dias = tipos.get(op2, ("MENSUAL", 30))

    clave = generar_clave(dias=dias, tipo=tipo)
    vence = date.today() + timedelta(days=dias)

    print()
    sep("═")
    print("  ✅ CLAVE GENERADA")
    sep("═")
    print()
    print(f"  {clave}")
    print()
    print(f"  Tipo:   {tipo}")
    print(f"  Días:   {dias}")
    print(f"  Vence:  {vence}")
    sep("═")
    print()
    print("  Envía esta clave al cliente.")
    print("  Al abrir FactuPro por primera vez")
    print("  se la pedirá para activar el sistema.")
    print()

    # Guardar
    nombre = f"clave_{tipo}_{date.today()}.txt".replace(" ","_")
    ruta = Path(__file__).parent / nombre
    ruta.write_text(
        f"FactuPro — Clave de Licencia\n{'='*40}\n"
        f"Clave:  {clave}\nTipo:   {tipo}\nVence:  {vence}\n",
        encoding="utf-8"
    )
    print(f"  Guardado en: {ruta}")
    input("\nEnter para salir...")

if __name__ == "__main__":
    main()
