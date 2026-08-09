from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import PlatoIn, PlatoOut

router = APIRouter(prefix="/platos", tags=["platos"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar platos")


@router.get("", response_model=list[PlatoOut])
def listar(local_id: str, claims: dict = Depends(get_current_claims)):
    verificar_acceso_local(claims, local_id)
    db = get_db()
    return db.table("platos").select("*").eq("local_id", local_id).order("nombre").execute().data or []


@router.post("", response_model=PlatoOut, status_code=status.HTTP_201_CREATED)
def crear(body: PlatoIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    existente = db.table("platos").select("id").eq("local_id", body.local_id).eq("sku", body.sku).execute()
    if existente.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya existe un plato con ese SKU para este local")

    res = db.table("platos").insert({
        "local_id": body.local_id, "sku": body.sku, "nombre": body.nombre,
    }).execute()
    return res.data[0]
