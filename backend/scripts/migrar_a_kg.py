# -*- coding: utf-8 -*-
"""
Migracion unica: cambia la unidad por defecto de gramos a kilogramos
para el piloto de Doña Delfina. Convierte par_stock, odoo_mapping y los
items de pedidos existentes (cantidad / 1000, unidad 'g' -> 'kg',
ingrediente_key con sufijo '||kg').

El resto del sistema (sugerencia, Generar OC) ya es agnostico a la
unidad -- no requiere cambios de codigo, solo de datos.

Uso: PYTHONUTF8=1 python -m backend.scripts.migrar_a_kg
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.db import get_db

db = get_db()


def nueva_key(key: str) -> str:
    nombre, _, unidad = key.partition("||")
    return f"{nombre}||kg" if unidad == "g" else key


# ── par_stock ────────────────────────────────────────────────────────
for r in db.table("par_stock").select("*").eq("unidad", "g").execute().data:
    db.table("par_stock").update({
        "ingrediente_key": nueva_key(r["ingrediente_key"]),
        "unidad": "kg",
        "par_cantidad": r["par_cantidad"] / 1000,
    }).eq("local_id", r["local_id"]).eq("ingrediente_key", r["ingrediente_key"]).execute()
    print(f"par_stock: {r['ingrediente_key']} -> {nueva_key(r['ingrediente_key'])} ({r['par_cantidad']} -> {r['par_cantidad']/1000})")

# ── odoo_mapping ─────────────────────────────────────────────────────
for r in db.table("odoo_mapping").select("*").execute().data:
    if not r["ingrediente_key"].endswith("||g"):
        continue
    nk = nueva_key(r["ingrediente_key"])
    db.table("odoo_mapping").update({"ingrediente_key": nk}).eq("ingrediente_key", r["ingrediente_key"]).execute()
    print(f"odoo_mapping: {r['ingrediente_key']} -> {nk}")

# ── pedidos (items existentes) ──────────────────────────────────────
for p in db.table("pedidos").select("*").execute().data:
    items = p["items"]
    cambiado = False
    nuevos_items = []
    for item in items:
        if (item.get("unidad") or "").lower() == "g":
            item = dict(item)
            item["cantidad"] = item["cantidad"] / 1000
            item["unidad"] = "kg"
            if item.get("ingrediente_key"):
                item["ingrediente_key"] = nueva_key(item["ingrediente_key"])
            cambiado = True
        nuevos_items.append(item)
    if cambiado:
        db.table("pedidos").update({"items": nuevos_items}).eq("id", p["id"]).execute()
        print(f"pedido {p['id']}: items migrados a kg")

print("\nListo.")
