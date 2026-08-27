from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from postgrest.exceptions import APIError

from ..bodega_service import registrar_entrega_cocina
from ..catalogo import productos_mas_baratos
from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..excel_exporter import exportar_dia
from ..schemas import (ChocolateIn, ChocolateOut, EntregaIn, MermaItem, MermaSeguimientoIn, PasteleriaIn,
                       PasteleriaOut, PlatoVentaOut, ProteinaProduccionIn, ProteinaProduccionOut,
                       RecetaVentaIn, RecetaVentaLineaOut, ResumenDiferenciaItem, StockCocinaIn,
                       VinculoIn, VinculoOut)

router = APIRouter(prefix="/mermas", tags=["mermas"])


def _dia_anterior(fecha: str) -> str:
    return (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()


def _lunes_de_la_semana(fecha_iso: str) -> date:
    d = date.fromisoformat(fecha_iso)
    return d - timedelta(days=d.weekday())  # weekday() 0=Lunes


def _stock_inicial_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """El Stock Inicial de un dia es el Stock Informado (conteo fisico) del
    dia anterior -- se arrastra, igual que en la planilla."""
    fecha_ant = _dia_anterior(fecha)
    rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada") \
        .eq("local_id", local_id).eq("fecha", fecha_ant).execute().data or []
    return {r["ingrediente_key"]: r["cantidad_informada"] for r in rows}


def _entregas_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Entregas de Bodega a Cocina ese dia (bodega_movimientos, origen
    entrega_cocina -- via importar planilla o registrado a mano en
    Inventario)."""
    rows = db.table("bodega_movimientos").select("ingrediente_key,cantidad") \
        .eq("local_id", local_id).eq("origen", "entrega_cocina") \
        .gte("fecha", f"{fecha}T00:00:00+00:00").lt("fecha", f"{fecha}T23:59:59.999999+00:00") \
        .execute().data or []
    resultado: dict[str, float] = {}
    for r in rows:
        resultado[r["ingrediente_key"]] = resultado.get(r["ingrediente_key"], 0) + r["cantidad"]
    return resultado


def _produccion_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Cantidad producida internamente en Cocina ese dia, por producto final,
    sumando las 3 fuentes fijas del Excel: proteinas transformadas, pasteleria
    y chocolates entregados. Cuando un insumo tiene produccion ese dia, SU
    Entregas del dia (tabla resumen) viene de aca, no de Bodega -- igual que
    la formula real de la planilla."""
    resultado: dict[str, float] = {}

    recetas = db.table("produccion_proteinas_recetas").select("id,producto_final_key") \
        .eq("local_id", local_id).execute().data or []
    receta_id_a_key = {r["id"]: r["producto_final_key"] for r in recetas if r["producto_final_key"]}
    if receta_id_a_key:
        diarias = db.table("produccion_proteinas_diaria").select("receta_id,cantidad_producida") \
            .eq("fecha", fecha).in_("receta_id", list(receta_id_a_key.keys())).execute().data or []
        for r in diarias:
            key = receta_id_a_key.get(r["receta_id"])
            if key and r["cantidad_producida"]:
                resultado[key] = resultado.get(key, 0) + r["cantidad_producida"]

    pasteleria = db.table("pasteleria_diaria").select("producto_key,cantidad_producida") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    for r in pasteleria:
        if r["cantidad_producida"]:
            resultado[r["producto_key"]] = resultado.get(r["producto_key"], 0) + r["cantidad_producida"]

    chocolates = db.table("chocolates_diaria").select("producto_key,cantidad_entregada") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    for r in chocolates:
        if r["cantidad_entregada"]:
            resultado[r["producto_key"]] = resultado.get(r["producto_key"], 0) + r["cantidad_entregada"]

    return resultado


def _mermas_produccion_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Mermas de la conversion materia prima -> producto final (columna
    'Mermas (Kg)' del bloque de proteinas), sumadas al producto final. Se
    suman a las mermas por causa del propio insumo en el bloque Control de
    Stock -- igual que la formula real (ej. Mermas de Chupe = J258, la
    columna Mermas de la fila 'Salmón Ahumado en frío -> Chupe')."""
    recetas = db.table("produccion_proteinas_recetas").select("id,producto_final_key") \
        .eq("local_id", local_id).execute().data or []
    receta_id_a_key = {r["id"]: r["producto_final_key"] for r in recetas if r["producto_final_key"]}
    if not receta_id_a_key:
        return {}
    diarias = db.table("produccion_proteinas_diaria").select("receta_id,mermas") \
        .eq("fecha", fecha).in_("receta_id", list(receta_id_a_key.keys())).execute().data or []
    resultado: dict[str, float] = {}
    for r in diarias:
        key = receta_id_a_key.get(r["receta_id"])
        if key and r["mermas"]:
            resultado[key] = resultado.get(key, 0) + r["mermas"]
    return resultado


def _ventas_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Consumo de insumo por las ventas del dia: ventas_historial (por
    plato, ya automatizado desde TCPOS) x el factor de ventas_recetas --
    la receta EMBEBIDA en el bloque VENTAS del Excel real (filas 66-153),
    sembrada una sola vez, igual patron que mermas_seguimiento. Es una
    tabla propia y desacoplada de 'recetas' (esa es la del modulo de
    Compras/Pedidos -- un sistema distinto, sin relacion con el Excel).
    Se matchea por plato_sku, no por plato_id, porque asi viene guardado
    ventas_historial."""
    ventas = db.table("ventas_historial").select("plato_sku,cantidad") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    cantidad_por_sku: dict[str, float] = {}
    for v in ventas:
        cantidad_por_sku[v["plato_sku"]] = cantidad_por_sku.get(v["plato_sku"], 0) + v["cantidad"]
    if not cantidad_por_sku:
        return {}

    recetas = db.table("ventas_recetas").select("plato_sku,ingrediente_key,cantidad") \
        .eq("local_id", local_id).in_("plato_sku", list(cantidad_por_sku.keys())).execute().data or []

    resultado: dict[str, float] = {}
    for r in recetas:
        key = r.get("ingrediente_key")
        if not key:
            continue
        vendido = cantidad_por_sku.get(r["plato_sku"], 0)
        resultado[key] = resultado.get(key, 0) + vendido * r["cantidad"]
    return resultado


@router.get("", response_model=list[MermaItem])
def listar_mermas(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Vista tipo planilla del dia: Stock Inicial (arrastrado de ayer),
    Entregas y Ventas se calculan solas; Mermas y Stock Informado se
    ingresan a mano. Por defecto muestra AYER -- es el dia cuyas ventas ya
    estan completas y disponibles (la automatizacion trae las ventas de
    ayer cada madrugada, igual que antes se pegaban a mano)."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()

    # Lista fija: copia identica de la planilla, no depende de si el insumo
    # ya esta registrado como producto de compra en Proveedores/Par Stock.
    seguimiento = db.table("mermas_seguimiento").select("*").eq("local_id", local_id).order("ingrediente_key").execute().data or []
    if not seguimiento:
        return []
    keys = [r["ingrediente_key"] for r in seguimiento]

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada,mermas_total,mermas_desglose") \
        .eq("local_id", local_id).eq("fecha", fecha).in_("ingrediente_key", keys).execute().data or []
    informado = {c["ingrediente_key"]: c for c in cocina_rows}

    stock_inicial = _stock_inicial_por_insumo(db, local_id, fecha)
    entregas_bodega = _entregas_por_insumo(db, local_id, fecha)
    produccion = _produccion_por_insumo(db, local_id, fecha)
    mermas_produccion = _mermas_produccion_por_insumo(db, local_id, fecha)
    ventas = _ventas_por_insumo(db, local_id, fecha)
    # precio es un enriquecimiento opcional -- si el insumo todavia no esta
    # en el catalogo de Proveedores, simplemente no hay precio (0), no bloquea nada.
    precios = productos_mas_baratos(db, keys)

    resultado = []
    for r in seguimiento:
        key = r["ingrediente_key"]
        fila_cocina = informado.get(key) or {}
        desglose = fila_cocina.get("mermas_desglose") or {}
        mermas_total = (fila_cocina.get("mermas_total") or 0) + mermas_produccion.get(key, 0)
        # Entregas y Mermas del dia -- SIEMPRE calculados, nunca editables
        # aca (igual que en la planilla real: son formulas que apuntan a
        # bloques separados -- "Entregas a Cocina"/Produccion para Entregas,
        # "Control de Stock" (desglose por causa) para Mermas -- nunca se
        # tipean directo en esta tabla resumen).
        resultado.append(MermaItem(
            ingrediente_key=key, nombre=r["nombre"],
            unidad=r["unidad"], categoria=None, tramo=r.get("tramo", "kg"), fecha=fecha,
            cantidad_informada=fila_cocina.get("cantidad_informada"),
            mermas_total=mermas_total if (fila_cocina or mermas_produccion.get(key)) else None,
            mermas_produccion=desglose.get("produccion"),
            mermas_defectuosos=desglose.get("defectuosos"),
            mermas_clientes=desglose.get("clientes"),
            mermas_cortesia=desglose.get("cortesia"),
            mermas_reutilizar=desglose.get("reutilizar"),
            stock_inicial=stock_inicial.get(key, 0),
            entregas=entregas_bodega.get(key, 0) + produccion.get(key, 0),
            entrega_bodega=entregas_bodega.get(key, 0),
            ventas=round(ventas.get(key, 0), 3),
            precio=precios.get(key, {}).get("price", 0),
        ))
    return resultado


@router.post("", status_code=201)
def registrar_merma(body: StockCocinaIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede registrar mermas")
    verificar_acceso_local(claims, body.local_id)
    fecha = body.fecha or (date.today() - timedelta(days=1)).isoformat()

    desglose = {
        k: v for k, v in {
            "produccion": body.mermas_produccion, "defectuosos": body.mermas_defectuosos,
            "clientes": body.mermas_clientes, "cortesia": body.mermas_cortesia,
            "reutilizar": body.mermas_reutilizar,
        }.items() if v is not None
    }

    db = get_db()
    res = db.table("stock_cocina").upsert({
        "local_id": body.local_id,
        "ingrediente_key": body.ingrediente_key,
        "fecha": fecha,
        "cantidad_informada": body.cantidad_informada,
        "mermas_total": sum(desglose.values()) if desglose else None,
        "mermas_desglose": desglose or None,
        "created_by": claims["sub"],
    }, on_conflict="local_id,ingrediente_key,fecha").execute()
    return res.data[0]


@router.post("/entregas", status_code=201)
def registrar_entrega(body: EntregaIn, claims: dict = Depends(get_current_claims)):
    """Bloque separado 'Entregas a Cocina / Salida de Bodega' -- igual que en
    la planilla real, es su propia lista, no una celda de la tabla resumen."""
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede registrar entregas")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    registrar_entrega_cocina(db, body.local_id, body.ingrediente_key, body.fecha, body.cantidad, created_by=claims["sub"])
    return {"ok": True}


def _requiere_editor(claims: dict, accion: str):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"El rol observador no puede {accion}")


@router.post("/seguimiento", status_code=status.HTTP_201_CREATED)
def agregar_seguimiento(body: MermaSeguimientoIn, claims: dict = Depends(get_current_claims)):
    """Agrega un insumo nuevo al catalogo fijo de Mermas (mermas_seguimiento)
    -- hasta ahora esa lista era de solo lectura en la app (sembrada una
    sola vez desde el Excel real), asi que insumos que Doña Sofía vende
    pero que no estaban en la planilla original (ej. Demi Glace, Pastelera
    Elaborada -- bases/salsas, no proteinas ni platos de pasteleria) no
    tenian donde registrar su entrega a cocina. No requiere que cocina
    informe un "Stock Informado" diario para este insumo -- eso es
    independiente de Entregas a Cocina, y si nunca se completa el reporte
    de Mermas/Diferencias simplemente lo omite (ver _diferencias_del_dia),
    sin romper nada. Tampoco rompe el Excel real -- exportar_dia solo
    escribe en las filas que existen en la plantilla fisica, cualquier
    insumo nuevo sin fila mapeada se omite ahi tambien."""
    _requiere_editor(claims, "agregar insumos a Mermas")
    verificar_acceso_local(claims, body.local_id)
    if body.tramo not in ("kg", "unidades"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tramo debe ser 'kg' o 'unidades'")
    db = get_db()
    ingrediente_key = f"{body.nombre}||{body.unidad}"
    existente = db.table("mermas_seguimiento").select("ingrediente_key") \
        .eq("local_id", body.local_id).eq("ingrediente_key", ingrediente_key).execute().data
    if existente:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ese insumo ya existe en el catálogo de Mermas")
    try:
        db.table("mermas_seguimiento").insert({
            "local_id": body.local_id, "ingrediente_key": ingrediente_key, "nombre": body.nombre,
            "unidad": body.unidad, "tramo": body.tramo,
        }).execute()
    except APIError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo agregar: {e.message}")
    return {"ok": True}


@router.delete("/seguimiento", status_code=status.HTTP_204_NO_CONTENT)
def quitar_seguimiento(local_id: str, ingrediente_key: str, claims: dict = Depends(get_current_claims)):
    """Quita un insumo agregado por error -- no toca ningun historico ya
    guardado en stock_cocina/bodega_movimientos para ese insumo."""
    _requiere_editor(claims, "quitar insumos de Mermas")
    verificar_acceso_local(claims, local_id)
    db = get_db()
    db.table("mermas_seguimiento").delete().eq("local_id", local_id).eq("ingrediente_key", ingrediente_key).execute()


@router.get("/vinculos", response_model=list[VinculoOut])
def listar_vinculos(local_id: str, claims: dict = Depends(get_current_claims)):
    """Cada insumo de Mermas (catalogo fijo, mermas_seguimiento) junto con su
    vinculo actual a un insumo de Compras/Odoo, si ya se vinculo -- para la
    pantalla "Vincular insumos". Mermas y Compras son catalogos
    independientes (Mermas viene del Excel, Compras de Odoo/par_stock) --
    sin este vinculo, las entregas a cocina que se registran bajo la clave
    de Mermas nunca alimentan el pronostico de consumo de la sugerencia de
    compra (ver bodega_service.py::consumo_promedio_por_dia_semana)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()
    seguimiento = db.table("mermas_seguimiento").select("ingrediente_key,unidad").eq("local_id", local_id).order("ingrediente_key").execute().data or []
    if not seguimiento:
        return []
    vinculos = db.table("mermas_compras_vinculo").select("mermas_ingrediente_key,compras_ingrediente_key") \
        .eq("local_id", local_id).execute().data or []
    compras_por_mermas = {v["mermas_ingrediente_key"]: v["compras_ingrediente_key"] for v in vinculos}
    return [
        VinculoOut(
            mermas_ingrediente_key=r["ingrediente_key"], mermas_nombre=r["ingrediente_key"].split("||")[0],
            mermas_unidad=r["unidad"], compras_ingrediente_key=compras_por_mermas.get(r["ingrediente_key"]),
            compras_nombre=(compras_por_mermas[r["ingrediente_key"]].split("||")[0]
                            if r["ingrediente_key"] in compras_por_mermas else None),
        )
        for r in seguimiento
    ]


@router.put("/vinculos", status_code=status.HTTP_204_NO_CONTENT)
def fijar_vinculo(body: VinculoIn, claims: dict = Depends(get_current_claims)):
    """Vincula un insumo de Mermas con su equivalente en Compras/Odoo --
    autoservicio explicito del usuario (no adivinado por nombre), para no
    depender de una migracion cada vez que agregan un producto nuevo."""
    _requiere_editor(claims, "vincular insumos")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    db.table("mermas_compras_vinculo").upsert({
        "local_id": body.local_id, "mermas_ingrediente_key": body.mermas_ingrediente_key,
        "compras_ingrediente_key": body.compras_ingrediente_key, "vinculado_por": claims["sub"],
        "vinculado_en": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="local_id,mermas_ingrediente_key").execute()


@router.delete("/vinculos", status_code=status.HTTP_204_NO_CONTENT)
def quitar_vinculo(local_id: str, mermas_ingrediente_key: str, claims: dict = Depends(get_current_claims)):
    """Quita un vinculo puesto por error -- el insumo de Mermas vuelve a
    quedar sin vincular, no borra ningun dato historico de Mermas."""
    _requiere_editor(claims, "vincular insumos")
    verificar_acceso_local(claims, local_id)
    db = get_db()
    db.table("mermas_compras_vinculo").delete() \
        .eq("local_id", local_id).eq("mermas_ingrediente_key", mermas_ingrediente_key).execute()


@router.get("/recetas-venta", response_model=list[PlatoVentaOut])
def listar_recetas_venta(local_id: str, claims: dict = Depends(get_current_claims)):
    """Cada plato realmente vendido (de ventas_historial, ultimos ~120 dias
    para no traer platos descontinuados) junto con sus lineas actuales de
    ventas_recetas -- la tabla que de verdad alimenta bodega_movimientos
    (ver _ventas_por_insumo) y por lo tanto el pronostico de consumo. Un
    plato sin ninguna linea igual aparece (lineas=[]) para poder verlo como
    pendiente en "Vincular platos". Distinto del otro sistema de recetas
    (recetas.py/platos.py, ingrediente en texto libre, sin relacion con el
    consumo real -- no confundir)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()
    desde = (date.today() - timedelta(days=120)).isoformat()
    ventas = db.table("ventas_historial").select("plato_sku,plato_nombre") \
        .eq("local_id", local_id).gte("fecha", desde).execute().data or []
    nombre_por_sku: dict[str, str] = {}
    for v in ventas:
        nombre_por_sku.setdefault(v["plato_sku"], v["plato_nombre"])

    recetas = db.table("ventas_recetas").select("plato_sku,ingrediente_key,cantidad") \
        .eq("local_id", local_id).execute().data or []
    lineas_por_plato: dict[str, list[RecetaVentaLineaOut]] = {}
    for r in recetas:
        lineas_por_plato.setdefault(r["plato_sku"], []).append(RecetaVentaLineaOut(
            ingrediente_key=r["ingrediente_key"], ingrediente_nombre=r["ingrediente_key"].split("||")[0],
            cantidad=r["cantidad"],
        ))
        nombre_por_sku.setdefault(r["plato_sku"], r["plato_sku"])  # receta vieja de un plato que ya no vende recientemente

    platos = [
        PlatoVentaOut(plato_sku=sku, plato_nombre=nombre, lineas=lineas_por_plato.get(sku, []))
        for sku, nombre in nombre_por_sku.items()
    ]
    return sorted(platos, key=lambda p: p.plato_nombre)


@router.put("/recetas-venta", status_code=status.HTTP_204_NO_CONTENT)
def fijar_receta_venta(body: RecetaVentaIn, claims: dict = Depends(get_current_claims)):
    """Agrega o edita cuanto de un insumo consume UNA unidad vendida de un
    plato -- autoservicio explicito del usuario ("todo producto de la
    planta ira enlazado a cada plato"), nunca adivinado. ingrediente_key
    debe ser un insumo real de Compras/Odoo (el mismo picker que usa
    "Vincular insumos", desde /par-stock) -- asi la venta descuenta directo
    del insumo correcto."""
    _requiere_editor(claims, "editar recetas de venta")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    db.table("ventas_recetas").upsert({
        "local_id": body.local_id, "plato_sku": body.plato_sku,
        "ingrediente_key": body.ingrediente_key, "cantidad": body.cantidad,
    }, on_conflict="local_id,plato_sku,ingrediente_key").execute()


@router.delete("/recetas-venta", status_code=status.HTTP_204_NO_CONTENT)
def quitar_receta_venta(local_id: str, plato_sku: str, ingrediente_key: str, claims: dict = Depends(get_current_claims)):
    """Quita una linea de receta de venta puesta por error."""
    _requiere_editor(claims, "editar recetas de venta")
    verificar_acceso_local(claims, local_id)
    db = get_db()
    db.table("ventas_recetas").delete() \
        .eq("local_id", local_id).eq("plato_sku", plato_sku).eq("ingrediente_key", ingrediente_key).execute()


@router.get("/proteinas", response_model=list[ProteinaProduccionOut])
def listar_proteinas(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Bloque fijo 'Entregas de proteínas para producciones de cocina' --
    la lista de pares materia prima -> producto final es fija (catálogo
    produccion_proteinas_recetas), solo se cargan cantidades del día."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()
    recetas = db.table("produccion_proteinas_recetas").select("*") \
        .eq("local_id", local_id).order("orden").execute().data or []
    if not recetas:
        return []
    diarias = db.table("produccion_proteinas_diaria").select("*") \
        .eq("fecha", fecha).in_("receta_id", [r["id"] for r in recetas]).execute().data or []
    por_receta = {d["receta_id"]: d for d in diarias}
    return [
        ProteinaProduccionOut(
            receta_id=r["id"], orden=r["orden"],
            materia_prima_nombre=r["materia_prima_nombre"], materia_prima_unidad=r["materia_prima_unidad"],
            producto_final_nombre=r["producto_final_nombre"], producto_final_unidad=r["producto_final_unidad"],
            cantidad_consumida=(por_receta.get(r["id"]) or {}).get("cantidad_consumida"),
            cantidad_producida=(por_receta.get(r["id"]) or {}).get("cantidad_producida"),
            mermas=(por_receta.get(r["id"]) or {}).get("mermas"),
        )
        for r in recetas
    ]


@router.post("/proteinas", status_code=201)
def registrar_proteina(body: ProteinaProduccionIn, claims: dict = Depends(get_current_claims)):
    _requiere_editor(claims, "registrar producción de proteínas")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    db.table("produccion_proteinas_diaria").upsert({
        "receta_id": body.receta_id, "fecha": body.fecha,
        "cantidad_consumida": body.cantidad_consumida, "cantidad_producida": body.cantidad_producida,
        "mermas": body.mermas, "created_by": claims["sub"],
    }, on_conflict="receta_id,fecha").execute()
    return {"ok": True}


@router.get("/pasteleria", response_model=list[PasteleriaOut])
def listar_pasteleria(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Bloque fijo 'Registro Producciones Pastelería' -- lista fija de
    productos (catálogo pasteleria_seguimiento), solo se carga la cantidad
    producida del día."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()
    seguimiento = db.table("pasteleria_seguimiento").select("*").eq("local_id", local_id).execute().data or []
    if not seguimiento:
        return []
    diarias = db.table("pasteleria_diaria").select("*") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    por_producto = {d["producto_key"]: d for d in diarias}
    return [
        PasteleriaOut(
            producto_key=s["producto_key"], producto_nombre=s["producto_nombre"], unidad=s["unidad"],
            cantidad_producida=(por_producto.get(s["producto_key"]) or {}).get("cantidad_producida"),
        )
        for s in seguimiento
    ]


@router.post("/pasteleria", status_code=201)
def registrar_pasteleria(body: PasteleriaIn, claims: dict = Depends(get_current_claims)):
    _requiere_editor(claims, "registrar producción de pastelería")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    db.table("pasteleria_diaria").upsert({
        "local_id": body.local_id, "producto_key": body.producto_key, "fecha": body.fecha,
        "cantidad_producida": body.cantidad_producida, "created_by": claims["sub"],
    }, on_conflict="local_id,producto_key,fecha").execute()
    return {"ok": True}


@router.get("/chocolates", response_model=list[ChocolateOut])
def listar_chocolates(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Bloque fijo 'Registro de Chocolates' -- lista fija de productos
    (catálogo chocolates_seguimiento), solo se cargan Cantidad Entregada y
    Cantidad Utilizada del día."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()
    seguimiento = db.table("chocolates_seguimiento").select("*").eq("local_id", local_id).execute().data or []
    if not seguimiento:
        return []
    diarias = db.table("chocolates_diaria").select("*") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    por_producto = {d["producto_key"]: d for d in diarias}
    return [
        ChocolateOut(
            producto_key=s["producto_key"], producto_nombre=s["producto_nombre"], unidad=s["unidad"],
            cantidad_entregada=(por_producto.get(s["producto_key"]) or {}).get("cantidad_entregada"),
            cantidad_utilizada=(por_producto.get(s["producto_key"]) or {}).get("cantidad_utilizada"),
        )
        for s in seguimiento
    ]


@router.post("/chocolates", status_code=201)
def registrar_chocolate(body: ChocolateIn, claims: dict = Depends(get_current_claims)):
    _requiere_editor(claims, "registrar chocolates")
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    db.table("chocolates_diaria").upsert({
        "local_id": body.local_id, "producto_key": body.producto_key, "fecha": body.fecha,
        "cantidad_entregada": body.cantidad_entregada, "cantidad_utilizada": body.cantidad_utilizada,
        "created_by": claims["sub"],
    }, on_conflict="local_id,producto_key,fecha").execute()
    return {"ok": True}


@router.get("/exportar")
def exportar(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Genera el Excel real 'Inventario Cocina Semanal', ya lleno con los
    datos del dia -- misma plantilla original, con sus formulas intactas."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()

    seguimiento = db.table("mermas_seguimiento").select("*").eq("local_id", local_id).execute().data or []
    if not seguimiento:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Este local no tiene insumos de seguimiento configurados")
    keys = [r["ingrediente_key"] for r in seguimiento]

    stock_inicial = _stock_inicial_por_insumo(db, local_id, fecha)
    for r in seguimiento:
        r["stock_inicial"] = stock_inicial.get(r["ingrediente_key"])

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada,mermas_desglose") \
        .eq("local_id", local_id).eq("fecha", fecha).in_("ingrediente_key", keys).execute().data or []
    stock_cocina = {c["ingrediente_key"]: c for c in cocina_rows}

    entregas_bodega = _entregas_por_insumo(db, local_id, fecha)

    recetas = db.table("produccion_proteinas_recetas").select("id,orden").eq("local_id", local_id).execute().data or []
    diarias_prot = db.table("produccion_proteinas_diaria").select("*") \
        .eq("fecha", fecha).in_("receta_id", [r["id"] for r in recetas]).execute().data or [] if recetas else []
    por_receta = {d["receta_id"]: d for d in diarias_prot}
    proteinas = [
        {"orden": r["orden"], **{k: (por_receta.get(r["id"]) or {}).get(k) for k in
                                  ("cantidad_consumida", "cantidad_producida", "mermas")}}
        for r in recetas
    ]

    pasteleria_seg = db.table("pasteleria_seguimiento").select("*").eq("local_id", local_id).execute().data or []
    pasteleria_diaria = db.table("pasteleria_diaria").select("*") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    por_prod_p = {d["producto_key"]: d for d in pasteleria_diaria}
    pasteleria = [
        {"producto_nombre": s["producto_nombre"], "cantidad_producida": (por_prod_p.get(s["producto_key"]) or {}).get("cantidad_producida")}
        for s in pasteleria_seg
    ]

    chocolates_seg = db.table("chocolates_seguimiento").select("*").eq("local_id", local_id).execute().data or []
    chocolates_diaria = db.table("chocolates_diaria").select("*") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    por_prod_c = {d["producto_key"]: d for d in chocolates_diaria}
    chocolates = [
        {
            "producto_nombre": s["producto_nombre"],
            "cantidad_entregada": (por_prod_c.get(s["producto_key"]) or {}).get("cantidad_entregada"),
            "cantidad_utilizada": (por_prod_c.get(s["producto_key"]) or {}).get("cantidad_utilizada"),
        }
        for s in chocolates_seg
    ]

    platos = db.table("platos").select("sku").eq("local_id", local_id).execute().data or []
    skus_locales = {p["sku"] for p in platos}
    ventas_rows = db.table("ventas_historial").select("plato_sku,cantidad") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    ventas = [v for v in ventas_rows if v["plato_sku"] in skus_locales]

    contenido = exportar_dia(
        fecha=fecha, seguimiento=seguimiento, stock_cocina=stock_cocina, entregas_bodega=entregas_bodega,
        proteinas=proteinas, pasteleria=pasteleria, chocolates=chocolates, ventas=ventas,
    )
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Inventario Cocina {fecha}.xlsx"'},
    )


def _diferencias_semana(db, local_id: str, dias: list[str], keys: list[str]) -> dict[str, dict[str, float]]:
    """Version 'toda la semana de una vez' de _diferencias_del_dia -- misma
    formula exacta dia por dia, pero trayendo cada tabla una sola vez para
    los 5 dias en vez de repetir las mismas consultas dia por dia (el resumen
    semanal hacia ~10 round-trips x dia = 50+ por semana; esto lo deja en
    un puñado de consultas, sin importar cuantos dias se pidan)."""
    if not dias:
        return {}
    dia_min, dia_max = min(dias), max(dias)
    dia_ant_min = _dia_anterior(dia_min)

    # Stock Cocina: se trae tambien el dia anterior al primero de la semana,
    # porque el Stock Inicial de un dia es el Stock Informado del dia previo.
    cocina_rows = db.table("stock_cocina").select("ingrediente_key,fecha,cantidad_informada,mermas_total") \
        .eq("local_id", local_id).gte("fecha", dia_ant_min).lte("fecha", dia_max).in_("ingrediente_key", keys).execute().data or []
    cocina_por_dia: dict[str, dict[str, dict]] = {}
    for r in cocina_rows:
        cocina_por_dia.setdefault(r["fecha"], {})[r["ingrediente_key"]] = r

    # Entregas de Bodega a Cocina: un solo rango que cubre toda la semana,
    # agrupado despues por dia (mismo formato de fecha que registrar_entrega_cocina).
    entregas_rows = db.table("bodega_movimientos").select("ingrediente_key,cantidad,fecha") \
        .eq("local_id", local_id).eq("origen", "entrega_cocina") \
        .gte("fecha", f"{dia_min}T00:00:00+00:00").lt("fecha", f"{dia_max}T23:59:59.999999+00:00") \
        .execute().data or []
    entregas_por_dia: dict[str, dict[str, float]] = {}
    for r in entregas_rows:
        d = entregas_por_dia.setdefault(r["fecha"][:10], {})
        d[r["ingrediente_key"]] = d.get(r["ingrediente_key"], 0) + r["cantidad"]

    # Catalogo de recetas de proteinas -- no depende del dia, se trae una sola vez.
    recetas = db.table("produccion_proteinas_recetas").select("id,producto_final_key") \
        .eq("local_id", local_id).execute().data or []
    receta_id_a_key = {r["id"]: r["producto_final_key"] for r in recetas if r["producto_final_key"]}

    produccion_por_dia: dict[str, dict[str, float]] = {}
    mermas_produccion_por_dia: dict[str, dict[str, float]] = {}
    if receta_id_a_key:
        diarias = db.table("produccion_proteinas_diaria").select("receta_id,fecha,cantidad_producida,mermas") \
            .in_("fecha", dias).in_("receta_id", list(receta_id_a_key.keys())).execute().data or []
        for r in diarias:
            key = receta_id_a_key.get(r["receta_id"])
            if not key:
                continue
            if r.get("cantidad_producida"):
                d = produccion_por_dia.setdefault(r["fecha"], {})
                d[key] = d.get(key, 0) + r["cantidad_producida"]
            if r.get("mermas"):
                d = mermas_produccion_por_dia.setdefault(r["fecha"], {})
                d[key] = d.get(key, 0) + r["mermas"]

    pasteleria_rows = db.table("pasteleria_diaria").select("producto_key,fecha,cantidad_producida") \
        .eq("local_id", local_id).in_("fecha", dias).execute().data or []
    for r in pasteleria_rows:
        if r.get("cantidad_producida"):
            d = produccion_por_dia.setdefault(r["fecha"], {})
            d[r["producto_key"]] = d.get(r["producto_key"], 0) + r["cantidad_producida"]

    chocolates_rows = db.table("chocolates_diaria").select("producto_key,fecha,cantidad_entregada") \
        .eq("local_id", local_id).in_("fecha", dias).execute().data or []
    for r in chocolates_rows:
        if r.get("cantidad_entregada"):
            d = produccion_por_dia.setdefault(r["fecha"], {})
            d[r["producto_key"]] = d.get(r["producto_key"], 0) + r["cantidad_entregada"]

    # Ventas del dia (consumo de insumo = cantidad vendida x receta embebida del bloque VENTAS).
    ventas_rows = db.table("ventas_historial").select("plato_sku,fecha,cantidad") \
        .eq("local_id", local_id).in_("fecha", dias).execute().data or []
    cantidad_por_dia_sku: dict[str, dict[str, float]] = {}
    for v in ventas_rows:
        d = cantidad_por_dia_sku.setdefault(v["fecha"], {})
        d[v["plato_sku"]] = d.get(v["plato_sku"], 0) + v["cantidad"]

    todos_skus = list({sku for por_sku in cantidad_por_dia_sku.values() for sku in por_sku})
    ventas_recetas_rows = (
        db.table("ventas_recetas").select("plato_sku,ingrediente_key,cantidad")
        .eq("local_id", local_id).in_("plato_sku", todos_skus).execute().data or []
    ) if todos_skus else []

    ventas_por_dia: dict[str, dict[str, float]] = {}
    for dia, cantidad_por_sku in cantidad_por_dia_sku.items():
        d = ventas_por_dia.setdefault(dia, {})
        for r in ventas_recetas_rows:
            key = r.get("ingrediente_key")
            vendido = cantidad_por_sku.get(r["plato_sku"], 0) if key else 0
            if key and vendido:
                d[key] = d.get(key, 0) + vendido * r["cantidad"]

    # Misma formula que _diferencias_del_dia, dia por dia, con todo ya en memoria.
    resultado: dict[str, dict[str, float]] = {}
    for dia in dias:
        informado = cocina_por_dia.get(dia, {})
        if not informado:
            continue
        stock_inicial = {k: v["cantidad_informada"] for k, v in cocina_por_dia.get(_dia_anterior(dia), {}).items()}
        entregas_bodega = entregas_por_dia.get(dia, {})
        produccion = produccion_por_dia.get(dia, {})
        mermas_produccion = mermas_produccion_por_dia.get(dia, {})
        ventas = ventas_por_dia.get(dia, {})

        dia_resultado: dict[str, float] = {}
        for key, fila in informado.items():
            if fila.get("cantidad_informada") is None:
                continue
            entregas = entregas_bodega.get(key, 0) + produccion.get(key, 0)
            mermas_total = (fila.get("mermas_total") or 0) + mermas_produccion.get(key, 0)
            stock_real = stock_inicial.get(key, 0) + entregas - ventas.get(key, 0) - mermas_total
            dia_resultado[key] = fila["cantidad_informada"] - stock_real
        resultado[dia] = dia_resultado
    return resultado


@router.get("/resumen-semana", response_model=list[ResumenDiferenciaItem])
def resumen_semana(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Resumen tipo hoja 'MERMAS Sx' del Excel real: por insumo, la
    Diferencia total de la semana (Lunes a Viernes, misma fórmula real
    =SUM('S1 Lunes:S1 Viernes'!K4)) y el $ perdido cuando la diferencia es
    un faltante (negativa)."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()

    seguimiento = db.table("mermas_seguimiento").select("*").eq("local_id", local_id).order("ingrediente_key").execute().data or []
    if not seguimiento:
        return []
    keys = [r["ingrediente_key"] for r in seguimiento]
    precios = productos_mas_baratos(db, keys)

    lunes = _lunes_de_la_semana(fecha)
    dias_semana = [(lunes + timedelta(days=i)).isoformat() for i in range(5)]  # Lunes..Viernes

    diferencias_por_dia = _diferencias_semana(db, local_id, dias_semana, keys)

    totales: dict[str, float] = {}
    for dia in dias_semana:
        for key, dif in diferencias_por_dia.get(dia, {}).items():
            totales[key] = totales.get(key, 0) + dif

    resultado = []
    for r in seguimiento:
        key = r["ingrediente_key"]
        if key not in totales:
            continue
        diferencia_total = round(totales[key], 3)
        precio = precios.get(key, {}).get("price", 0)
        total_dscto = diferencia_total * precio if diferencia_total < 0 else 0
        resultado.append(ResumenDiferenciaItem(
            ingrediente_key=key, nombre=r["nombre"], unidad=r["unidad"],
            diferencia_total=diferencia_total, precio=precio, total_dscto=round(total_dscto, 2),
        ))
    return resultado


@router.get("/reporte-ventas-pdf")
def reporte_ventas_pdf(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Descarga el PDF original 'Article Analysis' que TCPOS entregó esa
    noche -- respaldo guardado por el cron automático en Supabase Storage,
    bucket 'reportes-ventas'."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fecha inválida, debe ser YYYY-MM-DD")
    db = get_db()
    ruta = f"{local_id}/{fecha}-ArticleAnalysis.pdf"
    try:
        contenido = db.storage.from_("reportes-ventas").download(ruta)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No hay reporte de ventas respaldado para el {fecha}")
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Reporte Ventas {fecha}.pdf"'},
    )
