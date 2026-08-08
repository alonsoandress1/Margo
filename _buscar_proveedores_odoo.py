# -*- coding: utf-8 -*-
"""
Busca proveedor y precio de los 4 productos Odoo ya identificados para el
piloto de Par Stock (Doña Delfina), vía product.supplierinfo.

Uso: python _buscar_proveedores_odoo.py
Las credenciales NO se guardan en ningún lado.
"""
import getpass
from odoo_connector import OdooWebSession

PRODUCTOS = {
    'Salmón Ahumado en caliente||g': 12454,  # PES0384
    'Filete Salteado||g':            12049,  # CAR412
    'Carpaccio||g':                  12041,  # CAR0400
    'Plateada||g':                   10509,  # CAR00310
}

print("Busqueda de proveedores/precios Odoo — las credenciales NO se guardan.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Usuario (email): ").strip()
password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
print()
print(("✓ " if ok else "✗ ") + msg)

if ok:
    print("\nProveedores por producto:\n")
    ids = list(PRODUCTOS.values())
    supplierinfo = session.call_kw('product.supplierinfo', 'search_read',
        [[['product_id', 'in', ids]]],
        {'fields': ['product_id', 'partner_id', 'price', 'currency_id', 'min_qty', 'delay']})

    por_producto = {}
    for s in supplierinfo:
        pid = s['product_id'][0] if isinstance(s['product_id'], list) else s['product_id']
        por_producto.setdefault(pid, []).append(s)

    for key, pid in PRODUCTOS.items():
        print(f"  {key}  (product_id={pid})")
        entries = por_producto.get(pid, [])
        if not entries:
            print("     (sin proveedor/precio configurado en Odoo)")
        for s in entries:
            partner = s.get('partner_id') or [None, '?']
            currency = s.get('currency_id') or [None, '?']
            print(f"     proveedor: {partner[1]} (id={partner[0]})  "
                  f"precio: {s.get('price')} {currency[1]}  "
                  f"min_qty: {s.get('min_qty')}  delay: {s.get('delay')}d")
        print()

input("\nPresiona Enter para cerrar...")
