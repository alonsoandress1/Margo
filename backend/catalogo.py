"""Helpers compartidos sobre el catálogo de insumos (odoo_mapping).

Un mismo ingrediente_key puede tener hasta 3 filas (una por proveedor,
ver esquema). Estas funciones centralizan la logica de "elegir la
opcion mas barata", para no repetirla en cada router que la necesita.
"""


def productos_mas_baratos(db, keys: list[str]) -> dict[str, dict]:
    """Para cada ingrediente_key, la fila de odoo_mapping con menor precio."""
    if not keys:
        return {}
    rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data or []
    mejor: dict[str, dict] = {}
    for r in rows:
        k = r["ingrediente_key"]
        actual = mejor.get(k)
        if actual is None or (r.get("price") or 0) < (actual.get("price") or 0):
            mejor[k] = r
    return mejor
