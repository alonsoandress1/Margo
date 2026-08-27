from datetime import date, timedelta

from postgrest.exceptions import APIError


DIAS_HISTORIAL_PRONOSTICO = 84  # ~12 semanas -- acota la consulta a medida que crece el historial


def _mermas_a_compras(db, local_id: str, keys: list[str]) -> dict[str, str]:
    """mermas_compras_vinculo (pantalla "Vincular insumos", autoservicio del
    usuario -- nunca adivinado por nombre) dice que clave de Mermas
    corresponde a que clave de Compras/Odoo. Mermas (catalogo separado,
    sembrado del Excel) y Compras/Odoo (par_stock) son catalogos
    independientes -- las entregas a cocina de la mayoria de los insumos
    quedan grabadas bajo la clave de MERMAS, no la de Compras (confirmado
    con datos reales: de 48 insumos en Mermas y 41 en Compras, solo 1
    coincidia). Devuelve {clave_mermas: clave_compras} para los insumos de
    `keys` que ya tengan vinculo -- usado tanto por el pronostico de
    consumo como por el Stock de Bodega real, para que ambos vean las
    entregas de Mermas sin importar bajo que clave quedaron grabadas."""
    if not keys:
        return {}
    vinculos = db.table("mermas_compras_vinculo").select("mermas_ingrediente_key,compras_ingrediente_key") \
        .eq("local_id", local_id).in_("compras_ingrediente_key", keys).execute().data or []
    return {v["mermas_ingrediente_key"]: v["compras_ingrediente_key"] for v in vinculos}


def consumo_promedio_por_dia_semana(db, local_id: str, keys: list[str]) -> dict[str, dict[int, float]]:
    """Para cada insumo, promedio de egresos de bodega_movimientos (entrega_cocina
    + venta_tcpos, cualquier origen -- son las mismas fuentes que ya restan del
    Stock de Bodega calculado, ver stock_bodega_por_insumo) agrupado por dia de
    la semana (0=Lunes..6=Domingo, misma convencion que date.weekday() ya usada
    en mermas.py). Usado para sumar consumo proyectado a la sugerencia de
    compra mientras llega un pedido (ver dias_entrega en proveedores).

    Si varios egresos caen el mismo dia para el mismo insumo (ej.
    entrega_cocina Y venta_tcpos el mismo dia), se suman antes de promediar --
    un dia con dos origenes cuenta como UNA muestra, no dos.

    Si un dia de la semana puntual no tiene ninguna muestra, se usa el
    promedio general del insumo (todas las muestras, cualquier dia) en vez de
    0 -- con solo 1-2 semanas de historial real (venta_tcpos empezo el
    2026-08-18, entrega_cocina el 2026-08-11), la mayoria de los dias van a
    caer en este fallback por ahora, y va a mejorar solo con el tiempo. Un
    insumo sin ninguna muestra en absoluto no aparece en el resultado -- el
    llamador debe tratar eso como 0 (mismo comportamiento que antes de este
    pronostico).

    Ver _mermas_a_compras -- se usa aca para traducir cada fila ANTES de
    agrupar, asi el historial de Mermas cae en el bucket correcto del
    insumo de Compras."""
    if not keys:
        return {}
    mermas_a_compras = _mermas_a_compras(db, local_id, keys)
    keys_a_consultar = list(set(keys) | set(mermas_a_compras.keys()))

    desde = (date.today() - timedelta(days=DIAS_HISTORIAL_PRONOSTICO)).isoformat()
    rows = db.table("bodega_movimientos").select("ingrediente_key,cantidad,fecha") \
        .eq("local_id", local_id).eq("tipo", "egreso").in_("ingrediente_key", keys_a_consultar) \
        .gte("fecha", f"{desde}T00:00:00+00:00").execute().data or []

    por_dia: dict[tuple[str, str], float] = {}
    for r in rows:
        key = mermas_a_compras.get(r["ingrediente_key"], r["ingrediente_key"])
        k = (key, r["fecha"][:10])
        por_dia[k] = por_dia.get(k, 0) + r["cantidad"]

    suma_por_dow: dict[str, dict[int, float]] = {}
    cuenta_por_dow: dict[str, dict[int, int]] = {}
    for (key, dia), cantidad in por_dia.items():
        dow = date.fromisoformat(dia).weekday()
        suma_por_dow.setdefault(key, {})[dow] = suma_por_dow.setdefault(key, {}).get(dow, 0) + cantidad
        cuenta_por_dow.setdefault(key, {})[dow] = cuenta_por_dow.setdefault(key, {}).get(dow, 0) + 1

    promedios: dict[str, dict[int, float]] = {}
    for key, suma in suma_por_dow.items():
        cuenta = cuenta_por_dow[key]
        promedio_general = sum(suma.values()) / sum(cuenta.values())
        promedios[key] = {
            dow: (suma[dow] / cuenta[dow]) if dow in cuenta else promedio_general
            for dow in range(7)
        }
    return promedios


def stock_bodega_por_insumo(db, local_id: str, keys: list[str]) -> dict[str, float]:
    """Stock actual de Bodega por insumo -- suma del ledger completo de
    bodega_movimientos (ingreso +, egreso -). Logica centralizada aca porque
    tanto Inventario como la sugerencia de compra de Pedidos la necesitan
    igual; antes estaba duplicada en los dos routers.

    Ver _mermas_a_compras -- traduce cada fila ANTES de sumar, para que un
    egreso registrado en Entregas a Cocina bajo la clave de Mermas (ej.
    "Pastelera") descuente del insumo de Compras correcto (ej. "Pastelera
    Elaborada") aunque sea una clave distinta. Sin esto, el vinculo solo
    alimentaba el pronostico de consumo pero el Stock de Bodega mostrado en
    Inventario/Par Stock seguia sin verlo -- bug real encontrado por el
    usuario (entrego "Pastelera" y no se descontaba de "Pastelera Elaborada").

    Un Conteo Fisico ("ajuste") es una foto real de lo que hay HOY -- tiene
    que resetear el saldo a esa fecha, no sumarse como un movimiento mas
    encima de TODO el historial anterior. Sin esto, vincular un insumo con
    historial previo (ventas/entregas de Mermas de antes del conteo, recien
    visibles gracias al vinculo) resta ese historial igual, aunque el
    conteo ya deberia haber sido la foto real de ese momento -- bug real
    encontrado por el usuario (Stock de Bodega en negativo justo despues de
    vincular insumos con historial). Por insumo, se busca la fecha del
    ajuste mas reciente entre TODAS sus claves vinculadas y se suma solo
    desde ahi (el ajuste mismo incluido) -- sin ningun ajuste previo, se
    comporta igual que antes (suma todo). Redondeado a 3 decimales (el
    ruido de precision flotante al sumar muchos decimales, ej.
    -19.259999999999998, tambien lo reporto el usuario) y nunca negativo --
    stock fisico real no puede serlo, un negativo aca es señal de que hace
    falta un conteo nuevo, no un numero para mostrar tal cual."""
    if not keys:
        return {}
    mermas_a_compras = _mermas_a_compras(db, local_id, keys)
    keys_a_consultar = list(set(keys) | set(mermas_a_compras.keys()))

    rows = db.table("bodega_movimientos").select("ingrediente_key,tipo,cantidad,fecha") \
        .eq("local_id", local_id).in_("ingrediente_key", keys_a_consultar).execute().data or []
    por_key: dict[str, list[dict]] = {}
    for m in rows:
        key = mermas_a_compras.get(m["ingrediente_key"], m["ingrediente_key"])
        por_key.setdefault(key, []).append(m)

    stock: dict[str, float] = {}
    for key, movimientos in por_key.items():
        desde = max((m["fecha"] for m in movimientos if m["tipo"] == "ajuste"), default=None)
        total = sum(
            (-1 if m["tipo"] == "egreso" else 1) * m["cantidad"]
            for m in movimientos if not desde or m["fecha"] >= desde
        )
        stock[key] = max(0.0, round(total, 3))
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
