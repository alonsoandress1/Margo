# -*- coding: utf-8 -*-
"""
Busca en Odoo los productos que correspondan a los insumos piloto del
Par Stock de Doña Delfina, para poder armar odoo_mapping.json.

Uso: python _buscar_productos_odoo.py
Las credenciales NO se guardan en ningún lado (mismo patron que odoo_connector.py).
"""
import getpass
from odoo_connector import OdooWebSession

TERMINOS = ['salmon', 'salmón', 'filete', 'saltea', 'salta', 'carpaccio', 'plateada']

print("Busqueda de productos Odoo — las credenciales NO se guardan.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Usuario (email): ").strip()
password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
print()
print(("✓ " if ok else "✗ ") + msg)

if ok:
    print("\nBuscando productos de compra que coincidan con los insumos piloto...\n")
    vistos = set()
    for termino in TERMINOS:
        domain = [
            ['purchase_ok', '=', True],
            ['name', 'ilike', termino],
        ]
        productos = session.call_kw('product.product', 'search_read', [domain], {
            'fields': ['id', 'name', 'default_code', 'uom_po_id', 'seller_ids'],
            'limit': 20,
        })
        for p in productos:
            if p['id'] in vistos:
                continue
            vistos.add(p['id'])
            uom = p.get('uom_po_id') or [None, '']
            print(f"  id={p['id']:<6} code={p.get('default_code') or '(sin código)':<15} "
                  f"uom={uom[1] if len(uom) > 1 else '?':<8} nombre={p['name']}")

    if not vistos:
        print("  (sin resultados — puede que los productos tengan otro nombre en Odoo,"
              " o que no estén marcados 'Se puede comprar')")

input("\nPresiona Enter para cerrar...")
