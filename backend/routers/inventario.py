from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..bodega_service import stock_bodega_por_insumo
from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import (InventarioItem, MovimientoIn, MovimientoOut, StockPendienteOut,
                       StockPendienteReprocesarOut)

router = APIRouter(prefix="/inventario", tags=["inventario"])

TIPOS_VALIDOS = ("ingreso", "egreso", "ajuste")


@router.get("", response_model=list[InventarioItem])
def listar_inventario(local_id: str, claims: dict = Depends(get_current_claims)):
    """Stock de bodega actual por insumo -- 100% calculado desde el ledger
    de movimientos (nunca contado a mano)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).execute().data or []
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
    que el mapeo que faltaba exista."""
    db = get_db()
    filas = db.table("bodega_stock_pendiente").select("*").order("creado_en", desc=True).execute().data or []
    return [StockPendienteOut(**f) for f in filas]


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

    ahora = datetime.now(timezone.utc).isoformat()
    resueltos = 0
    for p in pendientes:
        local_id = p.get("local_id") or local_por_company.get(p.get("odoo_company_id"))
        ingrediente_key = ingrediente_por_producto.get(p["odoo_product_id"])
        if not local_id or not ingrediente_key:
            continue
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "ingreso",
            "cantidad": p["cantidad"], "origen": "factura_odoo", "ref": p.get("invoice_name"),
            "nota": f"Factura Odoo {p.get('invoice_name')} ({p.get('proveedor_nombre')}) -- resuelto despues",
            "fecha": ahora,
        }).execute()
        db.table("bodega_stock_pendiente").delete().eq("id", p["id"]).execute()
        resueltos += 1

    return StockPendienteReprocesarOut(resueltos=resueltos, pendientes=len(pendientes) - resueltos)
