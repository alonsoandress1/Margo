# -*- coding: utf-8 -*-
"""
Extrae la lista de productos DISTINTOS que facturó un proveedor en los
últimos N meses, leyendo "Documentos XML Recibidos" (los DTE que Odoo
recibe automaticamente del SII) -- solo lectura, no modifica nada en Odoo.

Estructura real (confirmada leyendo el Odoo real, no adivinada):
  l10n_cl.supplier.xml            -- cabecera (issuer_rut, issuer_name,
                                      date, invoice_id -- False si TODAVIA
                                      no se convirtio a factura borrador)
    -> line_ids -> l10n_cl.supplier.xml.line   (item_name, qty, product_id,
                                                 code_ids)
         -> code_ids -> l10n_cl.supplier.xml.item.code  (code_type,
                                                          code_value --
                                                          el codigo interno
                                                          del PROVEEDOR,
                                                          ej. "CodSap")

Ese code_value es mas confiable que el texto para matchear productos --
es estable entre facturas del mismo proveedor, a diferencia del texto
libre que puede variar un poco. Por eso el script junta ambos: texto Y
codigo, para poder mapear por codigo cuando exista.

Uso: python _extraer_productos_dte_proveedor.py
Las credenciales NO se guardan en ningun lado.
"""
import getpass
import json
from collections import defaultdict
from datetime import date, timedelta

from odoo_connector import OdooWebSession

print("Extraccion de productos DTE por proveedor — solo lectura, nada se guarda.\n")
url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()
user = input("Tu email de Odoo: ").strip()
password = getpass.getpass("Tu contraseña real de Odoo (no se guarda): ")
rut_proveedor = input("RUT del proveedor a buscar (ej. 76111152-3, con guión): ").strip()
meses = input("Cuantos meses atras buscar (default 3): ").strip()
meses = int(meses) if meses else 3

session = OdooWebSession(url)
ok, msg = session.connect(user, password)
password = None
if not ok:
    print(f"✗ No se pudo conectar: {msg}")
    raise SystemExit(1)
print(f"✓ {msg}\n")

desde = (date.today() - timedelta(days=meses * 30)).isoformat()
docs = session.call_kw('l10n_cl.supplier.xml', 'search_read',
    [[['issuer_rut', 'ilike', rut_proveedor], ['date', '>=', desde]]],
    {'fields': ['id', 'issuer_name', 'l10n_latam_document_number', 'date', 'invoice_id']})

if not docs:
    print(f"✗ No se encontraron documentos para el RUT '{rut_proveedor}' desde {desde}.")
    raise SystemExit(0)

nombre_proveedor = docs[0]['issuer_name']
ya_facturados = sum(1 for d in docs if d.get('invoice_id'))
print(f"✓ {len(docs)} documentos de '{nombre_proveedor}' desde {desde}")
print(f"  ({ya_facturados} ya tienen factura borrador creada, {len(docs) - ya_facturados} todavía no)\n")

doc_ids = [d['id'] for d in docs]
lineas = session.call_kw('l10n_cl.supplier.xml.line', 'search_read',
    [[['invoice_id', 'in', doc_ids]]],
    {'fields': ['item_name', 'qty', 'product_id', 'code_ids']})

code_ids = [c for l in lineas for c in l.get('code_ids', [])]
codigos_por_id = {}
if code_ids:
    codigos = session.call_kw('l10n_cl.supplier.xml.item.code', 'search_read',
        [[['id', 'in', code_ids]]], {'fields': ['code_type', 'code_value']})
    codigos_por_id = {c['id']: c for c in codigos}

# Agrupar por codigo del proveedor si existe, si no por el texto tal cual.
agrupado = defaultdict(lambda: {"veces": 0, "cantidad_total": 0.0, "nombres_vistos": set(), "ya_tiene_producto": False})
for l in lineas:
    codes = [codigos_por_id[c] for c in l.get('code_ids', []) if c in codigos_por_id]
    clave_codigo = next((f"{c['code_type']}:{c['code_value']}" for c in codes if c.get('code_value')), None)
    clave = clave_codigo or f"TEXTO:{(l.get('item_name') or '').strip()}"
    g = agrupado[clave]
    g["veces"] += 1
    g["cantidad_total"] += l.get('qty') or 0
    if l.get('item_name'):
        g["nombres_vistos"].add(l['item_name'].strip())
    if l.get('product_id'):
        g["ya_tiene_producto"] = True

print(f"--- {len(agrupado)} productos DISTINTOS encontrados ({len(lineas)} líneas en total) ---\n")
filas = []
for clave, g in sorted(agrupado.items(), key=lambda kv: -kv[1]["veces"]):
    ya = " [ya tiene product_id en Odoo]" if g["ya_tiene_producto"] else ""
    nombres = " / ".join(sorted(g["nombres_vistos"]))
    print(f"  [{g['veces']:3d}x]  {clave}  ->  {nombres}{ya}")
    filas.append({"clave": clave, "veces": g["veces"], "cantidad_total": g["cantidad_total"],
                   "nombres_vistos": sorted(g["nombres_vistos"]), "ya_tiene_product_id": g["ya_tiene_producto"]})

salida = {
    "proveedor": nombre_proveedor, "rut": rut_proveedor, "desde": desde,
    "documentos": len(docs), "documentos_sin_factura_borrador": len(docs) - ya_facturados,
    "lineas": len(lineas), "productos": filas,
}
with open("_dte_productos_extraidos.json", "w", encoding="utf-8") as f:
    json.dump(salida, f, ensure_ascii=False, indent=2)
print("\n✓ Guardado también en _dte_productos_extraidos.json.")
