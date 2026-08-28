"""Helpers compartidos sobre el catálogo de insumos (odoo_mapping).

Un mismo ingrediente_key puede tener hasta 3 filas (una por proveedor,
ver esquema). Estas funciones centralizan la logica de "elegir la
opcion mas barata", para no repetirla en cada router que la necesita.
"""
from .schemas import ProductoOut


def adivinar_unidad_odoo(nombre_uom: str | None) -> str | None:
    """Adivina kg/un a partir del nombre de una unidad de medida de Odoo
    (uom_po_id[1]) -- mismo criterio usado en proveedores.py::verificar_unidades
    y en _adivinarUnidadOdoo del frontend, centralizado aca para que los
    tres nunca diverjan entre si."""
    n = (nombre_uom or '').lower()
    if 'kg' in n or 'kilo' in n:
        return 'kg'
    if 'unid' in n:
        return 'un'
    return None


def _producto_de(row: dict) -> ProductoOut:
    return ProductoOut(
        id=row["id"], ingrediente_key=row["ingrediente_key"], nombre=row["ingrediente_key"].split("||")[0],
        unidad=row["ingrediente_key"].split("||")[1] if "||" in row["ingrediente_key"] else "",
        proveedor_id=row["proveedor_id"], odoo_id=row["odoo_id"], odoo_name=row["odoo_name"],
        ref=row.get("ref"), precio=row.get("price", 0), tamano_empaque=row.get("tamano_empaque"),
        unidad_odoo=row.get("unidad_odoo"), precio_negociado=row.get("precio_negociado"),
    )


def _precio_comparacion(r: dict) -> float:
    """Precio a usar para comparar proveedores entre si -- un precio
    pactado real (precio_negociado) siempre le gana al campo price de uso
    libre, mismo criterio que ya se usa para fijar el precio de la linea
    al generar una OC (ver pedidos.py). Sin esto, productos_mas_baratos
    podia elegir un proveedor sin ningun acuerdo (price mas bajo pero sin
    respaldo real) por sobre uno con un precio pactado mas barato todavia,
    justo el error que "Ahorro por Acuerdos" existe para detectar."""
    negociado = r.get("precio_negociado")
    return negociado if negociado is not None else (r.get("price") or 0)


def productos_mas_baratos(db, keys: list[str]) -> dict[str, dict]:
    """Para cada ingrediente_key, la fila de odoo_mapping mas barata (ver
    _precio_comparacion) entre los proveedores todavia activos -- un
    proveedor eliminado (soft-delete, ver proveedores.py::eliminar_proveedor)
    no debe seguir siendo candidato a "mas barato" para sugerencia de
    compra ni generar_oc, aunque sus filas de odoo_mapping sigan existiendo
    (se conservan por el historial)."""
    if not keys:
        return {}
    rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data or []
    proveedor_ids = {r["proveedor_id"] for r in rows if r.get("proveedor_id")}
    activos = {p["id"] for p in db.table("proveedores").select("id").in_("id", list(proveedor_ids))
               .eq("activo", True).execute().data or []} if proveedor_ids else set()
    mejor: dict[str, dict] = {}
    for r in rows:
        if r.get("proveedor_id") and r["proveedor_id"] not in activos:
            continue
        k = r["ingrediente_key"]
        actual = mejor.get(k)
        if actual is None or _precio_comparacion(r) < _precio_comparacion(actual):
            mejor[k] = r
    return mejor
