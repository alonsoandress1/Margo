from postgrest.exceptions import APIError


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
    duplicar (mismo dato reingresado a mano o por reimportacion de planilla).

    Se inserta primero (nunca se lee antes) -- un indice unico parcial en
    Postgres (local_id, ingrediente_key, fecha where origen='entrega_cocina',
    ver _migracion_entrega_cocina_unica.sql) es lo que de verdad garantiza
    que no queden dos filas para el mismo local/insumo/dia si dos clicks (o
    dos pestañas) caen casi juntos -- un chequeo "leer primero" no alcanza,
    los dos podrian pasar la lectura antes de que cualquiera inserte. Si el
    insert choca contra ese indice, se actualiza la fila que ya gano la
    carrera en vez de duplicar."""
    nota = nota or f"Entrega a Cocina ({fecha})"
    fecha_iso = f"{fecha}T00:00:00+00:00"
    try:
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "egreso",
            "cantidad": cantidad, "origen": "entrega_cocina", "nota": nota,
            "fecha": fecha_iso, "created_by": created_by,
        }).execute()
    except APIError as e:
        if e.code != "23505":
            raise
        existente = db.table("bodega_movimientos").select("id") \
            .eq("local_id", local_id).eq("ingrediente_key", ingrediente_key) \
            .eq("origen", "entrega_cocina") \
            .gte("fecha", f"{fecha}T00:00:00+00:00").lt("fecha", f"{fecha}T23:59:59.999999+00:00") \
            .execute()
        if existente.data:
            db.table("bodega_movimientos").update({"cantidad": cantidad, "nota": nota}) \
                .eq("id", existente.data[0]["id"]).execute()


def registrar_venta_descuento(db, local_id: str, ingrediente_key: str, fecha: str, cantidad: float,
                               nota: str | None = None) -> None:
    """Registra (o reemplaza) el egreso de Bodega por ventas del dia para un
    insumo, calculado desde ventas_recetas (plato vendido -> ingrediente).
    Mismo patron de idempotencia que registrar_entrega_cocina (insert
    primero, indice unico parcial en Postgres por origen='venta_tcpos', ver
    _migracion_venta_tcpos_unica.sql) -- si se reimporta el reporte de
    ventas de un dia ya procesado, esto actualiza la cantidad en vez de
    duplicar el descuento."""
    nota = nota or f"Ventas TCPOS ({fecha})"
    fecha_iso = f"{fecha}T00:00:00+00:00"
    try:
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "egreso",
            "cantidad": cantidad, "origen": "venta_tcpos", "nota": nota,
            "fecha": fecha_iso,
        }).execute()
    except APIError as e:
        if e.code != "23505":
            raise
        existente = db.table("bodega_movimientos").select("id") \
            .eq("local_id", local_id).eq("ingrediente_key", ingrediente_key) \
            .eq("origen", "venta_tcpos") \
            .gte("fecha", f"{fecha}T00:00:00+00:00").lt("fecha", f"{fecha}T23:59:59.999999+00:00") \
            .execute()
        if existente.data:
            db.table("bodega_movimientos").update({"cantidad": cantidad, "nota": nota}) \
                .eq("id", existente.data[0]["id"]).execute()
