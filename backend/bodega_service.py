def stock_bodega_por_insumo(db, local_id: str, keys: list[str]) -> dict[str, float]:
    """Stock actual de Bodega por insumo -- suma del ledger completo de
    bodega_movimientos (ingreso +, egreso -). Logica centralizada aca porque
    tanto Inventario como la sugerencia de compra de Pedidos la necesitan
    igual; antes estaba duplicada en los dos routers."""
    if not keys:
        return {}
    rows = db.table("bodega_movimientos").select("ingrediente_key,tipo,cantidad") \
        .eq("local_id", local_id).in_("ingrediente_key", keys).execute().data or []
    stock: dict[str, float] = {}
    for m in rows:
        signo = -1 if m["tipo"] == "egreso" else 1
        stock[m["ingrediente_key"]] = stock.get(m["ingrediente_key"], 0) + signo * m["cantidad"]
    return stock


def registrar_entrega_cocina(db, local_id: str, ingrediente_key: str, fecha: str, cantidad: float,
                              created_by: str | None = None, nota: str | None = None) -> None:
    """Registra (o reemplaza) el egreso de Bodega -> Cocina de un insumo para
    un dia. bodega_movimientos es un libro append-only -- si ya existe un
    egreso 'entrega_cocina' para ese local/insumo/dia, se actualiza en vez de
    duplicar (mismo dato reingresado a mano o por reimportacion de planilla)."""
    nota = nota or f"Entrega a Cocina ({fecha})"
    ya = db.table("bodega_movimientos").select("id") \
        .eq("local_id", local_id).eq("ingrediente_key", ingrediente_key) \
        .eq("origen", "entrega_cocina") \
        .gte("fecha", f"{fecha}T00:00:00+00:00").lt("fecha", f"{fecha}T23:59:59.999999+00:00") \
        .execute()
    if ya.data:
        db.table("bodega_movimientos").update({"cantidad": cantidad, "nota": nota}) \
            .eq("id", ya.data[0]["id"]).execute()
    else:
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "egreso",
            "cantidad": cantidad, "origen": "entrega_cocina", "nota": nota,
            "fecha": f"{fecha}T00:00:00+00:00", "created_by": created_by,
        }).execute()
