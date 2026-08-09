# -*- coding: utf-8 -*-
"""
Busca TODOS los productos configurados en Odoo para un proveedor dado
(via product.supplierinfo), para poder registrarlos en el catálogo de
Proveedores de la plataforma. Solo lectura -- no crea ni modifica nada
en Odoo.

Uso: python _buscar_productos_por_proveedor.py
Las credenciales NO se guardan en ningún lado -- correlas en tu propia
terminal, nunca las pegues en el chat.
"""
import getpass

from odoo_connector import OdooWebSession

PROVEEDOR_ID = 304  # Inversiones Doña Sofía SpA (ya confirmado antes)

print("Busqueda de productos por proveedor en Odoo — las credenciales NO se guardan.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Usuario (email): ").strip()
password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
print()
print(("✓ " if ok else "✗ ") + msg)

if ok:
    supplierinfo = session.call_kw(
        'product.supplierinfo', 'search_read',
        [[['partner_id', '=', PROVEEDOR_ID]]],
        {'fields': ['product_id', 'product_tmpl_id', 'product_name', 'product_code', 'price', 'currency_id', 'min_qty', 'delay']})

    print(f"\n{len(supplierinfo)} productos configurados para el proveedor id={PROVEEDOR_ID}:\n")

    # product_id (variante) suele venir vacio -- Odoo guarda esto a nivel de
    # product_tmpl_id (plantilla) la mayoria de las veces
    tmpl_ids = [s['product_tmpl_id'][0] for s in supplierinfo if s.get('product_tmpl_id')]
    plantillas = {}
    if tmpl_ids:
        rows = session.call_kw('product.template', 'search_read',
            [[['id', 'in', tmpl_ids]]],
            {'fields': ['id', 'display_name', 'default_code', 'uom_id']})
        plantillas = {r['id']: r for r in rows}
        # product.product real (para el odoo_id que usa create_purchase_order)
        variantes = session.call_kw('product.product', 'search_read',
            [[['product_tmpl_id', 'in', tmpl_ids]]],
            {'fields': ['id', 'product_tmpl_id']})
        variante_por_tmpl = {}
        for v in variantes:
            tid = v['product_tmpl_id'][0]
            variante_por_tmpl.setdefault(tid, v['id'])  # primera variante si hay varias
    else:
        variante_por_tmpl = {}

    for s in supplierinfo:
        tid = s['product_tmpl_id'][0] if s.get('product_tmpl_id') else None
        tmpl = plantillas.get(tid, {})
        pid = variante_por_tmpl.get(tid)
        uom = tmpl.get('uom_id') or [None, '?']
        currency = s.get('currency_id') or [None, '?']
        print(f"  odoo_id={pid}  ref={tmpl.get('default_code') or s.get('product_code') or '-'}")
        print(f"     nombre: {tmpl.get('display_name') or s.get('product_name') or '(sin nombre)'}")
        print(f"     precio: {s.get('price')} {currency[1]}   unidad Odoo: {uom[1]}   min_qty: {s.get('min_qty')}")
        print()

input("\nPresiona Enter para cerrar...")
