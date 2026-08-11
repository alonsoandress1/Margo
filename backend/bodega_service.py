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
