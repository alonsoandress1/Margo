# -*- coding: utf-8 -*-
"""
Importa masivamente el catalogo de productos de Doña Sofía (proveedor
id=304 en Odoo) obtenido con _buscar_productos_por_proveedor.py, hacia
la tabla odoo_mapping de Supabase.

- Si el odoo_id ya existe para este proveedor (ej. los 4 del piloto:
  Salmón Ahumado, Filete Salteado, Carpaccio, Plateada), se actualiza
  el precio real -- no se duplica ni se toca el ingrediente_key ya
  curado ni el tamaño de empaque ya configurado.
- Si es nuevo, se crea con ingrediente_key = "{nombre limpio}||{unidad}".
- Cuando el mismo odoo_id aparece mas de una vez en los datos crudos de
  Odoo (con precios distintos), se usa el PRIMERO y se reportan los
  conflictos al final para que se revisen a mano.
- No crea nada en Odoo -- solo lee un volcado ya hecho y escribe en
  nuestra propia base.

Uso: PYTHONUTF8=1 python -m backend.scripts.importar_catalogo_dona_sofia
"""
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.db import get_db

PROVEEDOR_ODOO_ID = 304

# (odoo_id, ref, nombre_crudo, precio, unidad_odoo) -- tal cual salio de
# _buscar_productos_por_proveedor.py. None en odoo_id o "Servicios..." se
# descartan mas abajo.
CRUDOS = [
    (13251, "REC527", "[REC527] Pan Ciabatta Mini Und", 500.0, "Unidades"),
    (16215, "REC00144", "[REC00144] Empanadas de Carne Mechada Und", 519.0, "Unidades"),
    (16900, "REC525", "[REC525] Pan Ciabatta Taller", 1000.0, "Unidades"),
    (16214, "ELA00392", "[ELA00392] Sorrentinos de Carne Mechada Porción", 2280.0, "Unidades"),
    (15828, "REC0059", "[REC0059] Salsa Bechamel", 2500.0, "Kg"),
    (16437, "LAC00480", "[LAC00480] Queso Parmesano Trozo", 12757.0, "Kg"),
    (10164, "REC0092", "[REC0092] Champiñones Salteados Kg", 18067.0, "Kg"),
    (16826, "REC529", "[REC529] Filete para Churrascos", 23332.0, "Unidades"),
    (14031, "BOL0143", "[BOL0143] Pan Focaccia Mini", 100.0, "Unidades"),
    (12466, None, "Granola Salada Und", 472.0, "Unidades"),
    (12472, "REC264", "[REC264] Alfajores Caseros", 477.0, "Unidades"),
    (14260, "BOL0144", "[BOL0144] Pan Focaccia Sándwich", 500.0, "Unidades"),
    (12044, None, "Croquetas de Quínoa", 502.0, "Unidades"),
    (13055, "CAR409", "[CAR409] Despunte de Solomillo de Cerdo", 990.0, "Kg"),
    (10375, "LAC00226", "[LAC00226] Manteca", 1000.0, "Kg"),
    (14088, "LAC00441", "[LAC00441] Mantequilla Casera Taller", 1000.0, "Kg"),
    (14142, "BOL031", "[BOL031] Pan Rallado Especial", 1000.0, "Unidades"),
    (12689, "ABA0544", "[ABA0544] Grasa de Cerdo", 1000.0, "Kg"),
    (12458, "REC00134", "[REC00134] Demi Glace", 2521.0, "Kg"),
    (13220, "CAR421", "[CAR421] Hamburguesa Casera 200 gramos Kg", 3264.0, "Kg"),
    (14312, "REC192", "[REC192] Sorrentinos de Salmón y Pulpo Porción", 3335.0, "Unidades"),
    (14422, "VECARFON062", "[VECARFON062] Sorrentinos de Salmón y Pulpo", 3335.0, "Unidades"),
    (10850, "REC0223", "[REC0223] Peras al Oporto", 3364.0, "Kg"),
    (13538, "ABA0525", "[ABA0525] Dressing de Mango y Naranja", 3478.0, "Kg"),
    (13840, "CAR411", "[CAR411] Despuntes de Pechuga de Pollo", 3500.0, "Kg"),
    (12054, "BOL0075", "[BOL0075] Masas de Tacos Horneadas", 3663.0, "Kg"),
    (10392, "ABA00240", "[ABA00240] Masa de Tacos Bolsa 12 Und 25-28 cms Und", 3663.0, "Unidades"),
    (13537, "ABA0526", "[ABA0526] Dressing de Mostaza y Miel", 3663.0, "Kg"),
    (12042, "FRU0115", "[FRU0115] Cebolla Estofada Kg", 4017.0, "Kg"),
    (12461, "BOL0066", "[BOL0066] Crumble Dulce de Almendras Kg", 4567.0, "Kg"),
    (13950, "REC190", "[REC190] Salsa Teriyaki", 4739.0, "Kg"),
    (10795, "REC0188", "[REC0188] Crumble de Pan y Avellanas", 4968.0, "Kg"),
    (13826, "CAR0397", "[CAR0397] Carne Molida", 5000.0, "Unidades"),
    (13947, "CAR0398", "[CAR0398] Carne Molida Taller", 5000.0, "Kg"),
    (12456, "BOL0094", "[BOL0094] Strudel de Carne Mechada", 5176.0, "Unidades"),
    (12039, "CON00434", "[CON00434] Habas Peladas Kg", 5456.0, "Kg"),
    (10293, "CON00173", "[CON00173] Habas Kg", 5456.0, "Kg"),
    (13268, "LAC00475", "[LAC00475] Queso Ricota Fresca", 6296.0, "Kg"),
    (12468, "LAC00476", "[LAC00476] Queso Ricota Fresca Casera", 6296.0, "Kg"),
    (10485, "FRU00297", "[FRU00297] Pera", 6670.0, "Kg"),
    (13951, "REC0129", "[REC0129] Pastelera Elaborada", 6744.0, "Kg"),
    (13949, "REC00137", "[REC00137] Dressing de Atún", 7019.0, "Kg"),
    (13828, None, "Pechuga de Pollo para Apanar", 7171.0, "Kg"),
    (13015, "ABA0568", "[ABA0568] Mermelada de Ají Verde", 7180.0, "Kg"),
    (13829, None, "Pechuga de Pollo para Plancha", 8377.0, "Kg"),
    (13985, "LAC00468", "[LAC00468] Queso Mantecoso Laminado Taller", 8582.0, "Kg"),
    (12447, "ABA0569", "[ABA0569] Mermelada de Higo", 8873.0, "Kg"),
    (12448, "ABA0578", "[ABA0578] Papa Hilo Casera", 9627.0, "Kg"),
    (12748, "CAR441", "[CAR441] Solomillo de Cerdo", 10800.0, "Kg"),
    (12453, "LAC00472", "[LAC00472] Queso Parmesano Rallado", 12757.0, "Kg"),
    (12055, "ABA0528", "[ABA0528] Dulce de Ají", 13809.0, "Kg"),
    (10544, "LAC00338", "[LAC00338] Queso Parmesano", 14759.0, "Kg"),
    (13984, "LAC00462", "[LAC00462] Queso de Cabra Rallado", 15149.0, "Kg"),
    (12450, "PES00377", "[PES00377] Plateada Retazos", 15315.0, "Kg"),
    (12449, "PES00376", "[PES00376] Plateada Porcionada 200 gramos", 15315.0, "Kg"),
    (10509, "CAR00310", "[CAR00310] Plateada", 15315.0, "Kg"),
    (13221, "CAR419", "[CAR419] Hamburguesa Personal 100 gramos Kg", 16320.0, "Kg"),
    (14043, "CAR424", "[CAR424] Lomo Liso Porcionado 250 gramos", 17442.0, "Kg"),
    (14470, "CAR406", "[CAR406] Ganso Porcionado 120 gramos", 17984.0, "Kg"),
    (15109, "PES00375", "[PES00375] Plateada Porcionada 180 gramos", 17984.0, "Kg"),
    (12454, "PES0384", "[PES0384] Salmón Ahumado en Caliente", 18822.0, "Kg"),
    (13952, "PES0388", "[PES0388] Salmón Porcionado 160 gramos", 18822.0, "Kg"),
    (12040, None, "Camarones Pelados Kg", 19914.0, "Kg"),
    (10135, "PES0072", "[PES0072] Camarón Ecuatoriano 36/40 Crudo con Cáscara", 19914.0, "Kg"),
    (13621, "CAR415", "[CAR415] Filete Despunte (para Sándwich)", 20168.0, "Kg"),
    (12455, "PES0385", "[PES0385] Salmón Ahumado en Frío", 20443.0, "Kg"),
    (13846, "CAR435", "[CAR435] Punta Picana", 21658.0, "Kg"),
    (13956, "CAR436", "[CAR436] Punta Picana Porcionada 190 gramos Kg", 21658.0, "Kg"),
    (13948, "PES00366", "[PES00366] Despunte Salmón Ahumado en Frío", 22795.0, "Kg"),
    (13953, "PES0389", "[PES0389] Salmón Porcionado 180 gramos", 22795.0, "Kg"),
    (12041, "CAR0400", "[CAR0400] Carpaccio de Res Kg", 23109.0, "Kg"),
    (12471, "CAR413", "[CAR413] Filete Despunte", 23332.0, "Kg"),
    (12049, "CAR412", "[CAR412] Filete Bastón (Para Saltado, 160 grs)", 23332.0, "Kg"),
    (10258, "CAR00154", "[CAR00154] Filete Porcionado (Medallón 200 grs)", 23870.0, "Kg"),
    (12048, "CAR414", "[CAR414] Filete Despunte (Para Crudo)", 23870.0, "Kg"),
    (10529, "ELA00326", "[ELA00326] Pulpo", 27941.0, "Kg"),
    (13954, "ELA125", "[ELA125] Pulpo Porcionado 145 gramos Kg", 33526.0, "Kg"),
    (13955, "PES00367", "[PES00367] Despuntes de Pulpo", 33526.0, "Kg"),
    (16611, "CAR456", "[CAR456] Plateada Cruda 180 gramos", 0.0, "Kg"),
    (10450, "BOL0280", "[BOL0280] Pan Ciabatta Mini Caja", 100.0, "Unidades"),
    (10389, "CON00237", "[CON00237] Masa de Empanadas", 519.0, "Unidades"),
    (10961, "FRU00463", "[FRU00463] Flores Comestibles", 4500.0, "Unidades"),
    (12452, "LAC00471", "[LAC00471] Queso Mozzarella Rallado", 8767.0, "Kg"),
    (10577, "PES00363", "[PES00363] Salmón Fresco", 19826.0, "Kg"),
    (10708, "ELA112", "[ELA112] Molida Especial", 20460.0, "Kg"),
    (10686, "FRU00432", "[FRU00432] Zapallo Italiano", 350.0, "Unidades"),
    (10156, "FRU0085", "[FRU0085] Cebollín Atado Und.", 500.0, "Unidades"),
    (10495, "FRU00305", "[FRU00305] Pimentón Verde Und", 500.0, "Unidades"),
    (10494, "FRU00304", "[FRU00304] Pimentón Rojo Und", 600.0, "Unidades"),
    (10153, "FRU0083", "[FRU0083] Cebolla Morada Kg", 800.0, "Kg"),
    (12642, "FRU0033", "[FRU0033] Apio Mata Und", 1800.0, "Unidades"),
    (10617, "ELA00391", "[ELA00391] Sorrentinos de Calabaza Porción", 2020.0, "Unidades"),
    (10049, "FRU0019", "[FRU0019] Ajo", 2500.0, "Kg"),
    (10247, "FRU0108", "[FRU0108] Espinacas", 2900.0, "Kg"),
    (10478, "CON00293", "[CON00293] Pastelera", 5830.0, "Kg"),
    (12128, "CAR437", "[CAR437] Molida Vacuno Corriente", 20460.0, "Kg"),
    (10470, "FRU00287", "[FRU00287] Papas", 28000.0, "Kg"),
    (10119, "FRU0093", "[FRU0093] Brotes de Arveja Bandeja", 1000.0, "Unidades"),
    (10118, "FRU0063", "[FRU0063] Brotes de Alfalfa Bandeja", 1000.0, "Unidades"),
    (10491, "FRU00302", "[FRU00302] Pimentón Amarillo Und", 1000.0, "Unidades"),
    (10645, "FRU0092", "[FRU0092] Tomate Cherry", 2450.0, "Kg"),
    (10541, "LAC00337", "[LAC00337] Queso Mantecoso", 8582.0, "Kg"),
    (13873, "CAR425", "[CAR425] Lomo Liso Vacuno", 17442.0, "Kg"),
    (10178, "FRU00104", "[FRU00104] Ciboulette Atado Und.", 350.0, "Unidades"),
    (10105, "FRU0055", "[FRU0055] Berenjenas Und", 400.0, "Unidades"),
    (10328, "FRU00193", "[FRU00193] Jengibre", 3500.0, "Kg"),
    (10539, "LAC00335", "[LAC00335] Queso de Cabra", 15149.0, "Kg"),
    (10429, "FRU0107", "[FRU0107] Naranjas", 1000.0, "Kg"),
    (10380, "FRU00234", "[FRU00234] Manzanas Verde", 1400.0, "Kg"),
    (10266, "FRU00159", "[FRU00159] Frutilla", 2500.0, "Kg"),
    (10051, "FRU0021", "[FRU0021] Albahaca", 4500000.0, "Kg"),  # OJO: precio sospechoso, revisar en Odoo
    (10367, "CAR00390", "[CAR00390] Lomo Vetado Vacuno", 8071.0, "Kg"),
    (10371, "FRU00223", "[FRU00223] Mango", 1650.0, "Unidades"),
    # -- duplicados con precio distinto encontrados en la segunda pasada --
    (13537, "ABA0526", "[ABA0526] Dressing de Mostaza y Miel", 3541.57206, "Kg"),
    (13538, "ABA0525", "[ABA0525] Dressing de Mango y Naranja", 3938.80672, "Kg"),
    (10795, "REC0188", "[REC0188] Crumble de Pan y Avellanas", 5390.0, "Kg"),
    (15109, "PES00375", "[PES00375] Plateada Porcionada 180 gramos", 17717.13683, "Kg"),
    (12471, "CAR413", "[CAR413] Filete Despunte", 23396.92693, "Kg"),
    (12048, "CAR414", "[CAR414] Filete Despunte (Para Crudo)", 23473.90841, "Kg"),
    (12042, "FRU0115", "[FRU0115] Cebolla Estofada Kg", 4449.9169, "Kg"),
    (12461, "BOL0066", "[BOL0066] Crumble Dulce de Almendras Kg", 4893.44475, "Kg"),
    (12055, "ABA0528", "[ABA0528] Dulce de Ají", 10791.75586, "Kg"),
    (12049, "CAR412", "[CAR412] Filete Bastón (Para Saltado, 160 grs)", 23614.85085, "Kg"),
]

SKU_NOMBRE = {"Servicios de Asesorías Gastronómicas y Know How"}


def limpiar_nombre(nombre_crudo: str) -> str:
    return re.sub(r"^\[[^\]]+\]\s*", "", nombre_crudo).strip()


db = get_db()

prov = db.table("proveedores").select("id").eq("odoo_supplier_id", PROVEEDOR_ODOO_ID).execute()
if not prov.data:
    raise SystemExit(f"No existe el proveedor con odoo_supplier_id={PROVEEDOR_ODOO_ID} en Supabase.")
proveedor_id = prov.data[0]["id"]

existentes = db.table("odoo_mapping").select("*").eq("proveedor_id", proveedor_id).execute().data or []
por_odoo_id = {r["odoo_id"]: r for r in existentes}

vistos: dict[int, tuple] = {}
conflictos: list[tuple] = []
for odoo_id, ref, nombre_crudo, precio, unidad_odoo in CRUDOS:
    if odoo_id is None:
        continue
    nombre_limpio = limpiar_nombre(nombre_crudo)
    if nombre_limpio in SKU_NOMBRE:
        continue
    if odoo_id in vistos:
        if abs(vistos[odoo_id][2] - precio) > 1:
            conflictos.append((nombre_limpio, vistos[odoo_id][2], precio))
        continue
    vistos[odoo_id] = (ref, nombre_limpio, precio, unidad_odoo)

actualizados, creados = 0, 0
for odoo_id, (ref, nombre_limpio, precio, unidad_odoo) in vistos.items():
    unidad = "kg" if unidad_odoo == "Kg" else "un"

    if odoo_id in por_odoo_id:
        db.table("odoo_mapping").update({"price": precio}).eq("id", por_odoo_id[odoo_id]["id"]).execute()
        actualizados += 1
    else:
        key = f"{nombre_limpio}||{unidad}"
        db.table("odoo_mapping").upsert({
            "ingrediente_key": key, "proveedor_id": proveedor_id,
            "ref": ref, "odoo_id": odoo_id, "odoo_name": nombre_limpio,
            "supplier_id": PROVEEDOR_ODOO_ID, "supplier_name": "Inversiones Doña Sofía SpA",
            "price": precio, "currency": "CLP",
        }, on_conflict="ingrediente_key,proveedor_id").execute()
        creados += 1

print(f"Productos unicos procesados: {len(vistos)}")
print(f"  Actualizados (ya existian): {actualizados}")
print(f"  Creados (nuevos):           {creados}")

if conflictos:
    print(f"\n{len(conflictos)} productos con precios distintos en Odoo (se uso el primero, revisar):")
    for nombre, p1, p2 in conflictos:
        print(f"  - {nombre}: {p1} vs {p2}")
