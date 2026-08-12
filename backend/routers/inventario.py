from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..bodega_service import stock_bodega_por_insumo
from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import InventarioItem, MovimientoIn, MovimientoOut

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
