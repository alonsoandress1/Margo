from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from ..bodega_service import stock_bodega_por_insumo
from ..catalogo import _producto_de
from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import (InventarioItem, MovimientoHistorialOut, MovimientoIn, MovimientoOut, ProductoOut,
                       StockPendienteOut, StockPendienteReprocesarOut, VincularPendienteIn)

router = APIRouter(prefix="/inventario", tags=["inventario"])

TIPOS_VALIDOS = ("ingreso", "egreso", "ajuste")


@router.get("", response_model=list[InventarioItem])
def listar_inventario(local_id: str, claims: dict = Depends(get_current_claims)):
    """Stock de bodega actual por insumo -- 100% calculado desde el ledger
    de movimientos (nunca contado a mano)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).order("ingrediente_key").execute().data or []
    if not par_rows:
        return []
    keys = [r["ingrediente_key"] for r in par_rows]
    stock = stock_bodega_por_insumo(db, local_id, keys)

    return [
        InventarioItem(
            ingrediente_key=r["ingrediente_key"], nombre=r["ingrediente_key"].split("||")[0],
            unidad=r["unidad"], categoria=r["categoria"], par=r["par_cantidad"],
            stock_bodega=stock.get(r["ingrediente_key"], 0),
        )
        for r in par_rows
    ]


@router.get("/historial-movimientos", response_model=list[MovimientoHistorialOut])
def historial_movimientos(local_id: str, ingrediente_key: str, desde: str, hasta: str,
                           claims: dict = Depends(get_current_claims)):
    """Movimientos reales de bodega_movimientos para un insumo en un rango de
    fechas (desde/hasta, formato AAAA-MM-DD) -- solo lectura, para poder
    verificar a mano el consumo real detras del pronostico de la sugerencia
    de compra (ver bodega_service.py::consumo_promedio_por_dia_semana)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()
    rows = db.table("bodega_movimientos").select("fecha,tipo,cantidad,origen,ref,nota") \
        .eq("local_id", local_id).eq("ingrediente_key", ingrediente_key) \
        .gte("fecha", f"{desde}T00:00:00+00:00").lte("fecha", f"{hasta}T23:59:59.999999+00:00") \
        .order("fecha").execute().data or []
    return rows


@router.post("/movimiento", response_model=MovimientoOut, status_code=status.HTTP_201_CREATED)
def registrar_movimiento(body: MovimientoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede registrar movimientos")
    if body.tipo not in TIPOS_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tipo invalido, debe ser uno de: {TIPOS_VALIDOS}")
    verificar_acceso_local(claims, body.local_id)

    db = get_db()
    res = db.table("bodega_movimientos").insert({
        "local_id": body.local_id,
        "ingrediente_key": body.ingrediente_key,
        "tipo": body.tipo,
        "cantidad": body.cantidad,
        "nota": body.nota,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "created_by": claims["sub"],
    }).execute()
    return res.data[0]


@router.get("/stock-pendiente", response_model=list[StockPendienteOut])
def listar_stock_pendiente(claims: dict = Depends(get_current_claims)):
    """Lineas de facturas creadas desde Facturas Odoo que no se pudieron
    sumar solas al stock de Bodega -- producto todavia sin insumo asociado
    (odoo_mapping) o local sin mapeo a su empresa de Odoo (locales.
    odoo_company_id). Se resuelven con reprocesar_stock_pendiente() una vez
    que el mapeo que faltaba exista.

    Sin gate de rol a proposito -- Inventario ya es visible para
    administrador/solicitante/observador por igual (ver SECCIONES en el
    frontend), asi que basta con estar autenticado.

    Ademas anexa sugerencia_ingrediente_key cuando el mismo producto de
    Odoo (odoo_product_id) ya esta vinculado en el catalogo bajo otro
    proveedor -- para que "Vincular" pueda preseleccionar ese insumo en vez
    de arriesgar crear uno nuevo duplicado con otro nombre."""
    db = get_db()
    filas = db.table("bodega_stock_pendiente").select("*").order("creado_en", desc=True).execute().data or []
    if not filas:
        return []

    product_ids = list({f["odoo_product_id"] for f in filas})
    mapeos = db.table("odoo_mapping").select("odoo_id,ingrediente_key").in_("odoo_id", product_ids).execute().data or []
    ingrediente_key_por_producto: dict[int, str] = {}
    for m in mapeos:
        ingrediente_key_por_producto.setdefault(m["odoo_id"], m["ingrediente_key"])

    return [
        StockPendienteOut(**f, sugerencia_ingrediente_key=ingrediente_key_por_producto.get(f["odoo_product_id"]))
        for f in filas
    ]


def _creditar_pendiente(db, p: dict, local_id: str, ingrediente_key: str) -> bool:
    """Borra la fila pendiente y suma el movimiento -- solo si el borrado de
    verdad se llevo puesto la fila. Se borra ANTES de sumar el movimiento y
    solo se suma si el borrado de verdad se llevo puesto una fila -- si dos
    resoluciones del mismo pendiente caen casi juntas (dos clics, dos
    pestañas), la segunda no encuentra nada que borrar y no llega a sumar
    el ingreso dos veces. Devuelve True si quedo resuelto."""
    borrada = db.table("bodega_stock_pendiente").delete().eq("id", p["id"]).execute()
    if not borrada.data:
        return False
    try:
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "ingreso",
            "cantidad": p["cantidad"], "origen": "factura_odoo", "ref": p.get("invoice_name"),
            "nota": f"Factura Odoo {p.get('invoice_name')} ({p.get('proveedor_nombre')}) -- resuelto despues",
            "fecha": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        # Se ya borro la fila pendiente pero no se alcanzo a sumar el
        # ingreso (ej. error de red) -- se reinserta para no perderla, en
        # vez de quedar sin registro de que faltaba sumarse.
        db.table("bodega_stock_pendiente").insert({
            "dte_id": p["dte_id"], "invoice_id": p.get("invoice_id"), "invoice_name": p.get("invoice_name"),
            "odoo_company_id": p.get("odoo_company_id"), "local_id": p.get("local_id"),
            "odoo_product_id": p["odoo_product_id"], "producto_nombre": p["producto_nombre"],
            "cantidad": p["cantidad"], "proveedor_nombre": p.get("proveedor_nombre"), "motivo": p["motivo"],
            "proveedor_rut": p.get("proveedor_rut"), "odoo_partner_id": p.get("odoo_partner_id"),
            "precio": p.get("precio"), "uom_odoo_id": p.get("uom_odoo_id"), "uom_odoo_nombre": p.get("uom_odoo_nombre"),
        }).execute()
        return False
    return True


@router.post("/stock-pendiente/reprocesar", response_model=StockPendienteReprocesarOut)
def reprocesar_stock_pendiente(claims: dict = Depends(get_current_claims)):
    """Reintenta sumar al stock cada linea pendiente -- para cuando se
    agrega despues el mapeo (insumo o local) que faltaba en su momento."""
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede actualizar el stock")
    db = get_db()
    pendientes = db.table("bodega_stock_pendiente").select("*").execute().data or []
    if not pendientes:
        return StockPendienteReprocesarOut(resueltos=0, pendientes=0)

    product_ids = list({p["odoo_product_id"] for p in pendientes})
    mapeos = db.table("odoo_mapping").select("odoo_id,ingrediente_key").in_("odoo_id", product_ids).execute().data or []
    ingrediente_por_producto = {m["odoo_id"]: m["ingrediente_key"] for m in mapeos}

    company_ids = list({p["odoo_company_id"] for p in pendientes if p.get("odoo_company_id")})
    locales_rows = (db.table("locales").select("id,odoo_company_id").in_("odoo_company_id", company_ids)
                    .execute().data or []) if company_ids else []
    local_por_company = {r["odoo_company_id"]: r["id"] for r in locales_rows}

    resueltos = 0
    for p in pendientes:
        local_id = p.get("local_id") or local_por_company.get(p.get("odoo_company_id"))
        ingrediente_key = ingrediente_por_producto.get(p["odoo_product_id"])
        if not local_id or not ingrediente_key:
            continue
        if _creditar_pendiente(db, p, local_id, ingrediente_key):
            resueltos += 1

    return StockPendienteReprocesarOut(resueltos=resueltos, pendientes=len(pendientes) - resueltos)


def _resolver_proveedor(db, p: dict) -> dict:
    """Busca el proveedor por su ID real en Odoo (odoo_supplier_id); si
    todavia no esta en nuestra tabla de Proveedores, lo crea usando los
    datos que la factura ya trajo -- nunca se inventa nada, solo se
    registra lo que Odoo ya confirmo al crear la factura real. No crea
    nada EN Odoo, solo en nuestra base. Devuelve la fila completa (no solo
    el id) para poder llenar supplier_id/supplier_name en odoo_mapping,
    igual que crear_producto en proveedores.py."""
    if not p.get("odoo_partner_id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Esta fila pendiente es de antes de este cambio y no tiene el proveedor de Odoo resuelto -- "
            "hay que vincular este producto a mano en Proveedores",
        )
    existente = db.table("proveedores").select("*").eq("odoo_supplier_id", p["odoo_partner_id"]).execute()
    if existente.data:
        return existente.data[0]
    try:
        nuevo = db.table("proveedores").insert({
            "nombre": p.get("proveedor_nombre") or "Proveedor sin nombre",
            "odoo_supplier_id": p["odoo_partner_id"], "usa_odoo": True,
        }).execute()
    except APIError as e:
        if e.code != "23505":
            raise
        # Dos "Vincular" concurrentes del mismo proveedor nuevo -- el otro
        # gano la carrera (indice unico en odoo_supplier_id, ver
        # _migracion_proveedores_odoo_supplier_id_unico.sql), se usa esa fila.
        return db.table("proveedores").select("*").eq("odoo_supplier_id", p["odoo_partner_id"]).execute().data[0]
    return nuevo.data[0]


@router.post("/stock-pendiente/{pendiente_id}/vincular", response_model=ProductoOut)
def vincular_pendiente(pendiente_id: str, body: VincularPendienteIn, claims: dict = Depends(get_current_claims)):
    """Registra en el catalogo (odoo_mapping) el producto de esta linea
    pendiente usando los datos que la factura YA trajo de Odoo (odoo_id,
    nombre, precio, unidad real) -- sin retipear nada. Se puede vincular a
    un insumo ya existente (consolida el mismo insumo entre proveedores,
    habilitando comparar precio a futuro) o crear uno nuevo. El proveedor
    se crea solo si todavia no estaba en Proveedores (ver
    _resolver_proveedor) -- nunca se crea nada en Odoo."""
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede vincular productos")
    if not body.ingrediente_key_existente and not (body.nombre_nuevo and body.unidad_nueva):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            "Hay que elegir un insumo existente o dar nombre y unidad para uno nuevo")

    db = get_db()
    fila = db.table("bodega_stock_pendiente").select("*").eq("id", pendiente_id).execute()
    if not fila.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fila pendiente no encontrada")
    p = fila.data[0]
    if p["motivo"] != "sin_insumo":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta fila no está pendiente por falta de insumo")

    proveedor = _resolver_proveedor(db, p)
    proveedor_id = proveedor["id"]
    ingrediente_key = body.ingrediente_key_existente or f"{body.nombre_nuevo}||{body.unidad_nueva}"

    db.table("odoo_mapping").upsert({
        "ingrediente_key": ingrediente_key, "proveedor_id": proveedor_id,
        "odoo_id": p["odoo_product_id"], "odoo_name": p["producto_nombre"],
        "supplier_id": proveedor["odoo_supplier_id"], "supplier_name": proveedor["nombre"],
        "price": body.precio if body.precio is not None else (p.get("precio") or 0),
        "tamano_empaque": body.tamano_empaque, "unidad_odoo": body.unidad_odoo,
    }, on_conflict="ingrediente_key,proveedor_id").execute()

    row = db.table("odoo_mapping").select("*").eq("ingrediente_key", ingrediente_key) \
        .eq("proveedor_id", proveedor_id).execute().data[0]

    if p.get("local_id"):
        _creditar_pendiente(db, p, p["local_id"], ingrediente_key)

    return _producto_de(row)
