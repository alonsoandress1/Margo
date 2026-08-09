# -*- coding: utf-8 -*-
"""
Importa el catalogo de platos desde ArticleAnalysisReport.xls (reporte
de ventas por articulo, exportado del POS) a la tabla `platos`.

El reporte no trae ingredientes -- solo SKU y nombre de cada articulo
vendido. Los ingredientes de cada plato se siguen asignando a mano
desde la pantalla Recetas.

Uso: PYTHONUTF8=1 python -m backend.scripts.importar_platos
"""
from pathlib import Path

import xlrd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.db import get_db

BASE_DIR = Path(__file__).resolve().parents[2]
REPORTE = BASE_DIR / "ArticleAnalysisReport.xls"
LOCAL_NOMBRE = "Doña Delfina"


def parsear_platos(path: Path) -> list[tuple[str, str]]:
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    platos = []
    for r in range(21, sh.nrows):
        sku = str(sh.cell_value(r, 0)).strip()
        nombre = str(sh.cell_value(r, 1)).strip()
        if not sku or sku in ("Grupo", "Total Grupo", "Total") or sku.startswith("Total"):
            continue
        if not nombre or nombre.lower() == "redondeo":
            continue
        platos.append((sku, nombre))
    return platos


db = get_db()

local_res = db.table("locales").select("id").eq("nombre", LOCAL_NOMBRE).execute()
if not local_res.data:
    raise SystemExit(f"No existe el local '{LOCAL_NOMBRE}' en Supabase.")
local_id = local_res.data[0]["id"]

platos = parsear_platos(REPORTE)
print(f"{len(platos)} platos encontrados en el reporte.")

existentes = db.table("platos").select("sku").eq("local_id", local_id).execute().data or []
skus_existentes = {p["sku"] for p in existentes}

nuevos = [{"local_id": local_id, "sku": sku, "nombre": nombre}
          for sku, nombre in platos if sku not in skus_existentes]

if not nuevos:
    print("No hay platos nuevos que importar (ya estaban todos).")
else:
    # insertar en lotes para no exceder el limite de una sola request
    LOTE = 100
    for i in range(0, len(nuevos), LOTE):
        db.table("platos").insert(nuevos[i:i + LOTE]).execute()
    print(f"{len(nuevos)} platos nuevos importados para '{LOCAL_NOMBRE}'.")

print(f"Total en catalogo ahora: {len(skus_existentes) + len(nuevos)}")
