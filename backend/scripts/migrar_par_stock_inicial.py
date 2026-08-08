# -*- coding: utf-8 -*-
"""
Migracion unica: carga el Par Stock y el mapeo de Odoo del piloto
(Doña Delfina, 4 insumos) desde los JSON locales hacia Supabase.

Es un script de un solo uso -- una vez que par_stock/odoo_mapping vivan
en Supabase, la fuente de verdad pasa a ser la base de datos, no estos
JSON (que se mantienen igual para no romper la app de escritorio).

Uso: python -m backend.scripts.migrar_par_stock_inicial
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.db import get_db

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_NOMBRE = "Doña Delfina"


def cargar_json(nombre):
    path = BASE_DIR / nombre
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


db = get_db()

local_res = db.table("locales").select("id").eq("nombre", LOCAL_NOMBRE).execute()
if not local_res.data:
    raise SystemExit(f"No existe el local '{LOCAL_NOMBRE}' en Supabase. Corre supabase/schema.sql primero.")
local_id = local_res.data[0]["id"]
print(f"Local '{LOCAL_NOMBRE}' -> id={local_id}")

par_stock = cargar_json("par_stock.json").get(LOCAL_NOMBRE, {})
odoo_mapping = cargar_json("odoo_mapping.json")

migrados = 0
for key, info in par_stock.items():
    nombre, _, unidad = key.partition("||")
    mapping = odoo_mapping.get(key, {})

    db.table("par_stock").upsert({
        "local_id": local_id,
        "ingrediente_key": key,
        "unidad": unidad or "un",
        "categoria": mapping.get("categoria"),
        "par_cantidad": info["par"],
    }, on_conflict="local_id,ingrediente_key").execute()

    if mapping:
        db.table("odoo_mapping").upsert({
            "ingrediente_key": key,
            "ref": mapping.get("ref"),
            "odoo_id": mapping["odoo_id"],
            "odoo_name": mapping.get("odoo_name", nombre),
            "supplier_id": mapping["supplier_id"],
            "supplier_name": mapping.get("supplier_name", ""),
            "price": mapping.get("price", 0),
            "currency": mapping.get("currency", "CLP"),
            "last_sync": mapping.get("last_sync"),
        }, on_conflict="ingrediente_key").execute()

    migrados += 1
    print(f"  OK {nombre} ({unidad}) - par {info['par']}")

print(f"\n{migrados} insumos migrados a Supabase (par_stock + odoo_mapping).")
