# -*- coding: utf-8 -*-
"""
Genera una Orden de Compra real en Odoo para el piloto de Doña Delfina
(4 insumos, proveedor Inversiones Doña Sofía SpA).

Flujo:
  1. Calcula la sugerencia de compra (Par Stock + Stock Bodega + Stock
     Cocina + pronóstico) — reutiliza core.py, nada nuevo.
  2. Muestra el resumen y pide confirmación explícita antes de crear nada
     en Odoo (punto humano #1, versión de prueba en terminal).
  3. Si se confirma, crea el Draft PO en Odoo y registra po_tracking.

Uso: python generar_oc_prueba.py
Las credenciales de Odoo NO se guardan en ningún lado.
NO crea proveedores ni productos — solo usa los que ya existen en Odoo
(ver odoo_mapping.json). Si algo no está mapeado, se omite y se avisa.
"""
import getpass
from datetime import datetime
import core
from odoo_connector import OdooWebSession

LOCAL = 'Doña Delfina'

print("Generar Orden de Compra — Doña Delfina (piloto, 4 insumos)\n")

# 1) Calcular sugerencia con lo que ya existe en core.py
mapping = core.load_odoo_mapping()
if not mapping:
    print("No hay odoo_mapping.json — nada que ofrecer. Cancelado.")
    raise SystemExit

raw, recetas = core.load_recetas()
history = core.load_history(core.get_folder())
model = core.build_model(history)
name_to_sku = core.build_name_to_sku(history)
hoy = datetime.now()

stock_cocina = core.load_stock_cocina(LOCAL, hoy, excel_path='Mermas v3.xlsx')
sugerencia = core.compute_compra_sugerida_bodega(
    LOCAL, model, hoy, horizon=3, k_factor=core.K_SAFETY,
    recetas=recetas, name_to_sku=name_to_sku, stock_cocina=stock_cocina)

# 2) Filtrar a insumos mapeados a Odoo con algo que comprar
lineas = []
for key, info in mapping.items():
    sug = sugerencia.get(key)
    if not sug or sug['sugerido'] <= 0:
        continue
    kg = round(sug['sugerido'] / 1000, 2)   # nuestras cantidades están en gramos, Odoo en Kg
    lineas.append({
        'key':         key,
        'nombre':      info['odoo_name'],
        'product_id':  info['odoo_id'],
        'cantidad_kg': kg,
        'precio':      info.get('price', 0) or 0,
    })

if not lineas:
    print("No hay nada que comprar según la sugerencia actual (todo cubierto). Cancelado.")
    raise SystemExit

print("Resumen de la Orden de Compra propuesta:")
print(f"  Proveedor: {mapping[lineas[0]['key']]['supplier_name']}")
print(f"  Local: {LOCAL}\n")
total = 0.0
for l in lineas:
    subtotal = l['cantidad_kg'] * l['precio']
    total += subtotal
    print(f"  - {l['nombre']:<40} {l['cantidad_kg']:>8.2f} Kg  "
          f"x ${l['precio']:>8.0f} = ${subtotal:>10.0f}")
print(f"\n  TOTAL ESTIMADO: ${total:,.0f}")
if all(l['precio'] == 0 for l in lineas):
    print("  (precio en 0 — no hay precio configurado en Odoo todavía, se completa al revisar la OC)")

confirmar = input("\n¿Confirmas crear esta Orden de Compra en Odoo? (si/no): ").strip().lower()
if confirmar not in ('si', 's', 'yes', 'y'):
    print("Cancelado — no se creó nada.")
    raise SystemExit

# 3) Conectar y crear
print("\nConectando a Odoo...")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Usuario (email): ").strip()
password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
print()
print(("✓ " if ok else "✗ ") + msg)
if not ok:
    input("\nPresiona Enter para cerrar...")
    raise SystemExit

partner_id = mapping[lineas[0]['key']]['supplier_id']
po_lines = [{
    'product_id':  l['product_id'],
    'name':        l['nombre'],
    'product_qty': l['cantidad_kg'],
    'price_unit':  l['precio'],
} for l in lineas]

po_id, po_name = session.create_purchase_order(
    partner_id, po_lines, notes=f'Generado automáticamente — piloto {LOCAL}')

core.registrar_po_tracking(po_id, po_name, LOCAL,
    mapping[lineas[0]['key']]['supplier_name'], categoria='Proteínas',
    creado_por=user)

print(f"\n✓ Orden de Compra creada: {po_name} (id={po_id})")
print(f"  Revisar en: {url.rstrip('/')}/odoo/purchase/{po_id}")
input("\nPresiona Enter para cerrar...")
