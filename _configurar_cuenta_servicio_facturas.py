# -*- coding: utf-8 -*-
"""
Descubre el nombre de la base de datos de Odoo -- lo único que falta para
poder usar OdooClient (XML-RPC) con tu contraseña real en el cron nocturno
de facturas (sin nadie presente). Pide tu email + contraseña REAL una sola
vez, solo para esto -- no se guarda en ningún lado, ni se manda a ningún
servidor propio, solo se usa en memoria para esta prueba puntual.

Uso: python _configurar_cuenta_servicio_facturas.py
"""
import getpass

from odoo_connector import descubrir_db

print("Descubrimiento de base de datos Odoo — nada se guarda.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Tu email de Odoo: ").strip()
password = getpass.getpass("Tu contraseña real de Odoo (solo para este paso, no se guarda): ")

try:
    db = descubrir_db(url, user, password)
except Exception as e:
    print(f"✗ No se pudo descubrir la base de datos: {e}")
    raise SystemExit(1)
finally:
    password = None  # ya no hace falta, se limpia de la memoria del script

print(f"✓ Base de datos encontrada: {db}")
print("\nGuarda esto en Render (Environment) y en los Secrets de GitHub Actions:")
print(f"  ODOO_DB   = {db}")
print(f"  ODOO_FACTURAS_USER = {user}")
print("  ODOO_FACTURAS_PASSWORD = <tu contraseña real de Odoo>")
