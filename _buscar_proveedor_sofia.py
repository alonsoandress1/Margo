# -*- coding: utf-8 -*-
"""
Busca contactos/proveedores en Odoo que coincidan con "Sofia"/"Sofía".

Uso: python _buscar_proveedor_sofia.py
Las credenciales NO se guardan en ningún lado.
"""
import getpass
from odoo_connector import OdooWebSession

print("Busqueda de proveedor 'Sofia' en Odoo — las credenciales NO se guardan.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Usuario (email): ").strip()
password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
print()
print(("✓ " if ok else "✗ ") + msg)

if ok:
    print("\nContactos que coinciden con 'sofia' (nombre) o '77500046-5' (RUT):\n")
    domain = ['|', ['name', 'ilike', 'sofia'], ['vat', 'ilike', '77500046']]
    partners = session.call_kw('res.partner', 'search_read', [domain], {
        'fields': ['id', 'name', 'vat', 'supplier_rank', 'email', 'phone'],
        'limit': 20,
    })
    if not partners:
        print("  (sin resultados — no existe ningún contacto con ese nombre/RUT en Odoo)")
    for p in partners:
        tipo = 'PROVEEDOR' if p.get('supplier_rank', 0) > 0 else 'contacto (no marcado como proveedor)'
        print(f"  id={p['id']:<6} {p['name']:<35} vat={p.get('vat') or '-':<15} "
              f"[{tipo}]  email={p.get('email') or '-'}")

input("\nPresiona Enter para cerrar...")
