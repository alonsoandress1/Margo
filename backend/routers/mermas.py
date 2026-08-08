from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import MermaItem, StockCocinaIn

router = APIRouter(prefix="/mermas", tags=["mermas"])


@router.get("", response_model=list[MermaItem])
def listar_mermas(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Stock de cocina informado para un local en una fecha (hoy por
    defecto) -- reemplaza el Excel de Mermas, capturado a mano igual que
    lo hacia cocina antes, pero directo en la plataforma."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or date.today().isoformat()
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).execute().data or []
    if not par_rows:
        return []
    keys = [r["ingrediente_key"] for r in par_rows]

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada") \
        .eq("local_id", local_id).eq("fecha", fecha).in_("ingrediente_key", keys).execute().data or []
    informado = {c["ingrediente_key"]: c["cantidad_informada"] for c in cocina_rows}

    return [
        MermaItem(
            ingrediente_key=r["ingrediente_key"], nombre=r["ingrediente_key"].split("||")[0],
            unidad=r["unidad"], categoria=r["categoria"],
            cantidad_informada=informado.get(r["ingrediente_key"]), fecha=fecha,
        )
        for r in par_rows
    ]


@router.post("", status_code=201)
def registrar_merma(body: StockCocinaIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede registrar mermas")
    verificar_acceso_local(claims, body.local_id)
    fecha = body.fecha or date.today().isoformat()

    db = get_db()
    res = db.table("stock_cocina").upsert({
        "local_id": body.local_id,
        "ingrediente_key": body.ingrediente_key,
        "fecha": fecha,
        "cantidad_informada": body.cantidad_informada,
        "created_by": claims["sub"],
    }, on_conflict="local_id,ingrediente_key,fecha").execute()
    return res.data[0]
