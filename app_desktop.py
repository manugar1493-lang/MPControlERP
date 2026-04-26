"""
app_desktop.py — FactuPro v2.0
Muestra pantalla de activación si no hay licencia válida.
"""

import sys, os, time, socket, threading, webbrowser
from pathlib import Path
from io import StringIO

if sys.stdout is None: sys.stdout = StringIO()
if sys.stderr is None: sys.stderr = StringIO()

import logging
logging.basicConfig(level=logging.WARNING)

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
    _MEIPASS = Path(sys._MEIPASS).resolve() if hasattr(sys, "_MEIPASS") else BASE_DIR
else:
    BASE_DIR = Path(__file__).parent.resolve()
    _MEIPASS = BASE_DIR

os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

TITLE = "FactuPro — Sistema de Facturación"
LOG   = BASE_DIR / "factupro_error.log"


def find_free_port():
    for p in [8765, 8080, 8000, 8888, 9000]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p)); return p
        except OSError: continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

PORT = find_free_port()
URL  = f"http://127.0.0.1:{PORT}"


# ════════════════════════════════════════════════════════════════════════════
# PANTALLA DE ACTIVACIÓN
# ════════════════════════════════════════════════════════════════════════════

def mostrar_pantalla_activacion() -> bool:
    """
    Muestra la ventana de activación de licencia.
    Retorna True si se activó correctamente.
    """
    try:
        import tkinter as tk
        from tkinter import font as tkfont

        from licencia import activar_con_codigo, validar_licencia, get_machine_id

        activado = [False]

        root = tk.Tk()
        root.title("FactuPro — Activación")
        root.geometry("500x420")
        root.resizable(False, False)
        root.configure(bg="#0f1c2e")
        root.update_idletasks()
        x = (root.winfo_screenwidth()  - 500) // 2
        y = (root.winfo_screenheight() - 420) // 2
        root.geometry(f"500x420+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

        # Logo
        # Logo en pantalla de activación
        logo_path = _MEIPASS / "static" / "logo.png" if (_MEIPASS / "static" / "logo.png").exists() else BASE_DIR / "static" / "logo.png"
        if logo_path.exists():
            try:
                from PIL import Image, ImageTk
                img = Image.open(str(logo_path))
                img.thumbnail((220, 75))
                photo = ImageTk.PhotoImage(img)
                lbl_logo = tk.Label(root, image=photo, bg="#0f1c2e")
                lbl_logo.image = photo
                lbl_logo.pack(pady=(24, 4))
            except Exception:
                frm = tk.Frame(root, bg="#0f1c2e"); frm.pack(pady=(28,4))
                tk.Label(frm, text="Factu", font=("Helvetica",36,"bold"),
                         fg="#ffffff", bg="#0f1c2e").pack(side="left")
                tk.Label(frm, text="Pro", font=("Helvetica",36,"bold"),
                         fg="#f97316", bg="#0f1c2e").pack(side="left")
        else:
            frm = tk.Frame(root, bg="#0f1c2e"); frm.pack(pady=(28,4))
            tk.Label(frm, text="Factu", font=("Helvetica",36,"bold"),
                     fg="#ffffff", bg="#0f1c2e").pack(side="left")
            tk.Label(frm, text="Pro", font=("Helvetica",36,"bold"),
                     fg="#f97316", bg="#0f1c2e").pack(side="left")
        tk.Label(root, text="Sistema de Facturación · República Dominicana",
                 font=("Helvetica",9), fg="#64748b", bg="#0f1c2e").pack()

        # Separador
        tk.Frame(root, bg="#1e304a", height=1).pack(fill="x", pady=16, padx=30)

        tk.Label(root, text="🔑  Activación de Licencia",
                 font=("Helvetica",13,"bold"), fg="#ffffff", bg="#0f1c2e").pack()
        tk.Label(root,
                 text="Ingresa la clave de licencia que recibiste\nde tu proveedor FactuPro.",
                 font=("Helvetica",9), fg="#94a3b8", bg="#0f1c2e",
                 justify="center").pack(pady=(6,8))

        # Formato de ejemplo
        tk.Label(root, text="Formato: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX",
                 font=("Courier",9), fg="#374151", bg="#0f1c2e").pack(pady=(0,10))

        tk.Label(root, text="Clave de Licencia:",
                 font=("Helvetica",10,"bold"), fg="#cbd5e1", bg="#0f1c2e").pack(anchor="w", padx=40)

        # Entry simple de una sola línea
        entry_frame = tk.Frame(root, bg="#f97316", padx=2, pady=2)
        entry_frame.pack(padx=40, fill="x")
        entry = tk.Entry(entry_frame,
                         font=("Courier", 13, "bold"),
                         bg="#162236", fg="#f97316",
                         insertbackground="#f97316",
                         relief="flat", bd=8,
                         justify="center")
        entry.pack(fill="x")
        entry.focus_set()

        # Botón pegar
        btn_pegar = tk.Button(root, text="📋  Pegar clave",
                              font=("Helvetica",8), bg="#1e304a", fg="#94a3b8",
                              relief="flat", cursor="hand2",
                              padx=8, pady=3)
        btn_pegar.pack(anchor="e", padx=42)

        def pegar_clave():
            try:
                txt = root.clipboard_get().strip().upper().replace(" ","")
                entry.delete(0, "end")
                entry.insert(0, txt)
                entry.focus_set()
            except Exception: pass
        btn_pegar.config(command=pegar_clave)

        # Mensaje de estado
        msg_var = tk.StringVar(value="")
        msg_lbl = tk.Label(root, textvariable=msg_var,
                           font=("Helvetica",9), bg="#0f1c2e",
                           fg="#94a3b8", wraplength=420)
        msg_lbl.pack(pady=(10,0))

        def do_activate(event=None):
            # Leer clave — Entry usa .get() sin argumentos
            clave = entry.get().strip().upper().replace(" ", "")
            if not clave:
                msg_var.set("⚠  Ingresa la clave de licencia.")
                msg_lbl.config(fg="#f97316")
                return

            btn_activar.config(state="disabled", text="Verificando...")
            root.update()

            try:
                resultado = activar_con_codigo(clave)
            except Exception as e:
                msg_var.set(f"❌ Error interno: {e}")
                msg_lbl.config(fg="#ef4444")
                btn_activar.config(state="normal", text="  Activar  ")
                return

            if resultado.ok:
                msg_var.set(f"✅ {resultado.mensaje}")
                msg_lbl.config(fg="#22c55e")
                btn_activar.config(text="✅ Activado — Iniciando...")
                activado[0] = True
                root.after(1500, root.destroy)
            else:
                msg_var.set(f"❌ {resultado.mensaje}")
                msg_lbl.config(fg="#ef4444")
                btn_activar.config(state="normal", text="  Activar  ")

        entry.bind("<Return>", do_activate)

        # Botón activar
        btn_activar = tk.Button(root, text="  Activar  ",
                                font=("Helvetica",11,"bold"),
                                bg="#f97316", fg="white", relief="flat",
                                activebackground="#ea6b0e", cursor="hand2",
                                command=do_activate, padx=20, pady=10)
        btn_activar.pack(pady=5)

        # Machine ID
        try:
            mid = get_machine_id()
            tk.Label(root,
                     text=f"ID del equipo: {mid[:20]}...",
                     font=("Courier",8), fg="#374151", bg="#0f1c2e").pack()
            tk.Label(root,
                     text="(Envía este ID a tu proveedor si necesitas activación por equipo)",
                     font=("Helvetica",7), fg="#1e3a5f", bg="#0f1c2e").pack()
        except Exception:
            pass

        root.mainloop()
        return activado[0]

    except Exception as e:
        print(f"Error en pantalla de activación: {e}")
        return False


def mostrar_licencia_vencida(resultado):
    """Ventana de bloqueo cuando la licencia venció."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("FactuPro — Licencia Vencida")
        root.geometry("480x320")
        root.resizable(False, False)
        root.configure(bg="#0f1c2e")
        root.update_idletasks()
        x = (root.winfo_screenwidth()  - 480) // 2
        y = (root.winfo_screenheight() - 320) // 2
        root.geometry(f"480x320+{x}+{y}")
        root.protocol("WM_DELETE_WINDOW", root.destroy)

        tk.Label(root, text="🔒", font=("Helvetica",48), bg="#0f1c2e").pack(pady=(24,4))
        tk.Label(root, text="Licencia Vencida",
                 font=("Helvetica",20,"bold"), fg="#ffffff", bg="#0f1c2e").pack()

        msg = resultado.mensaje if resultado else "Tu licencia ha expirado."
        if resultado and resultado.data:
            vence   = resultado.data.get("vence","—")
            cliente = resultado.data.get("cliente","—")
            msg     = f"La licencia de '{cliente}' venció el {vence}."

        tk.Label(root, text=msg, font=("Helvetica",11),
                 fg="#94a3b8", bg="#0f1c2e", wraplength=420).pack(pady=10)
        tk.Label(root,
                 text="Contacta a tu proveedor FactuPro para renovar tu licencia.",
                 font=("Helvetica",10), fg="#64748b", bg="#0f1c2e").pack()

        # Opción de ingresar nuevo código
        def ingresar_nuevo_codigo():
            root.destroy()
            ok = mostrar_pantalla_activacion()
            if ok:
                from licencia import validar_licencia
                nuevo_resultado = validar_licencia()
                if nuevo_resultado.ok:
                    aviso_dias_restantes(nuevo_resultado)
                    _arrancar(nuevo_resultado.dias_restantes())
                else:
                    mostrar_licencia_vencida(nuevo_resultado)
            # Si ok es False el usuario cerró la ventana sin activar → no hacer nada

        tk.Button(root, text="  Ingresar nuevo código  ",
                  font=("Helvetica",10,"bold"),
                  bg="#f97316", fg="white", relief="flat",
                  cursor="hand2",
                  command=ingresar_nuevo_codigo,
                  padx=16, pady=8).pack(pady=(16,4))

        tk.Button(root, text="Cerrar",
                  font=("Helvetica",9),
                  bg="#1e304a", fg="#94a3b8", relief="flat",
                  cursor="hand2", command=root.destroy,
                  padx=12, pady=6).pack()

        root.mainloop()
    except Exception as e:
        print(f"Licencia vencida: {e}")


def aviso_dias_restantes(resultado):
    if not resultado or resultado.dias_restantes() > 7: return
    try:
        import tkinter as tk, tkinter.messagebox as mb
        r = tk.Tk(); r.withdraw()
        dias = resultado.dias_restantes()
        mb.showwarning("FactuPro — Licencia por vencer",
                       f"⚠️ Tu licencia vence en {dias} día{'s' if dias != 1 else ''}.\n\n"
                       "Contacta a tu proveedor para renovarla.")
        r.destroy()
    except Exception: pass


# ── Servidor ──────────────────────────────────────────────────────────────────

def _run_server():
    try:
        # Limpiar static/ para forzar copia fresca desde _MEIPASS
        # Esto garantiza que el instalador siempre use el frontend actualizado
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            import shutil
            meipass_static = _MEIPASS / "static"
            exe_static     = BASE_DIR  / "static"
            if meipass_static.exists():
                try:
                    if exe_static.exists():
                        shutil.rmtree(str(exe_static))
                    shutil.copytree(str(meipass_static), str(exe_static))
                except Exception:
                    pass

        os.environ["PORT"] = str(PORT)
        import uvicorn
        from main import app
        uvicorn.run(app, host="127.0.0.1", port=PORT,
                    log_level="warning", access_log=False)
    except Exception:
        import traceback
        try:
            LOG.write_text(f"PORT: {PORT}\n\n{traceback.format_exc()}", encoding="utf-8")
        except Exception: pass


def start_server():
    threading.Thread(target=_run_server, daemon=True, name="uvicorn").start()


def wait_server(timeout=30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5): return True
        except OSError: time.sleep(0.25)
    return False


def splash_window(dias_rest=None):
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        root.title("FactuPro"); root.geometry("400x210")
        root.resizable(False, False); root.configure(bg="#0f1c2e")
        root.overrideredirect(True); root.update_idletasks()
        x = (root.winfo_screenwidth()-400)//2; y = (root.winfo_screenheight()-210)//2
        root.geometry(f"400x210+{x}+{y}")
        # Logo
        logo_path = _MEIPASS / "static" / "logo.png" if (_MEIPASS / "static" / "logo.png").exists() else BASE_DIR / "static" / "logo.png"
        if logo_path.exists():
            try:
                from PIL import Image, ImageTk
                img = Image.open(str(logo_path))
                img.thumbnail((200, 70))
                photo = ImageTk.PhotoImage(img)
                lbl_logo = tk.Label(root, image=photo, bg="#0f1c2e")
                lbl_logo.image = photo
                lbl_logo.pack(pady=(20, 4))
            except Exception:
                f = tk.Frame(root, bg="#0f1c2e"); f.pack(expand=True)
                tk.Label(f, text="Factu", font=("Helvetica",32,"bold"),
                         fg="#ffffff", bg="#0f1c2e").pack(side="left")
                tk.Label(f, text="Pro", font=("Helvetica",32,"bold"),
                         fg="#f97316", bg="#0f1c2e").pack(side="left")
        else:
            f = tk.Frame(root, bg="#0f1c2e"); f.pack(expand=True)
            tk.Label(f, text="Factu", font=("Helvetica",32,"bold"),
                     fg="#ffffff", bg="#0f1c2e").pack(side="left")
            tk.Label(f, text="Pro", font=("Helvetica",32,"bold"),
                     fg="#f97316", bg="#0f1c2e").pack(side="left")
        tk.Label(root, text="Sistema de Facturación · República Dominicana",
                 font=("Helvetica",9), fg="#64748b", bg="#0f1c2e").pack()
        if dias_rest is not None:
            color = "#f97316" if dias_rest <= 7 else "#64748b"
            tk.Label(root, text=f"Licencia activa — {dias_rest} días restantes",
                     font=("Helvetica",8), fg=color, bg="#0f1c2e").pack()
        bar = ttk.Progressbar(root, mode="indeterminate", length=320)
        bar.pack(pady=8); bar.start(10)
        lbl = tk.Label(root, text="Iniciando…", font=("Helvetica",9),
                       fg="#94a3b8", bg="#0f1c2e"); lbl.pack()
        return root, lbl
    except Exception: return None, None


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    try:
        from licencia import validar_licencia
    except ImportError:
        # Sin módulo de licencia, arrancar directamente
        _arrancar()
        return

    resultado = validar_licencia()

    if resultado.estado == resultado.NO_ACTIVADO:
        # Primera vez — mostrar pantalla de activación
        ok = mostrar_pantalla_activacion()
        if not ok:
            sys.exit(0)
        resultado = validar_licencia()  # releer tras activación

    if resultado.estado == resultado.VENCIDA:
        mostrar_licencia_vencida(resultado)
        return

    if resultado.estado == resultado.INVALIDO:
        mostrar_licencia_vencida(resultado)
        return

    if not resultado.ok:
        mostrar_licencia_vencida(resultado)
        return

    # Aviso si quedan pocos días
    aviso_dias_restantes(resultado)

    _arrancar(resultado.dias_restantes())


def _arrancar(dias_rest=None):
    start_server()
    splash, lbl = splash_window(dias_rest)
    ok = False

    if splash:
        def _wait():
            nonlocal ok
            ok = wait_server()
            try: lbl.config(text="¡Listo!" if ok else "⚠ Error")
            except Exception: pass
            time.sleep(0.6); splash.quit()
        threading.Thread(target=_wait, daemon=True).start()
        splash.mainloop()
        try: splash.destroy()
        except Exception: pass
    else:
        ok = wait_server()

    if not ok:
        msg = f"El servidor no pudo iniciarse en el puerto {PORT}."
        if LOG.exists():
            msg += f"\n\nLog:\n{LOG.read_text(encoding='utf-8')[:1000]}"
        try:
            import tkinter.messagebox as mb
            mb.showerror("FactuPro — Error", msg)
        except Exception: print(msg)
        return

    try:
        import webview
        webview.create_window(TITLE, URL, width=1280, height=800,
                              min_size=(900,600), resizable=True)
        webview.start(debug=False)
    except Exception:
        webbrowser.open(URL)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
