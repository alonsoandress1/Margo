from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import RecetaLineaIn, RecetaLineaOut

router = APIRouter(prefix="/recetas", tags=["recetas"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede editar recetas")


@router.get("", response_model=list[RecetaLineaOut])
def listar(local_id: str, claims: dict = Depends(get_current_claims)):
    verificar_acceso_local(claims, local_id)
    db = get_db()
    rows = db.table("recetas").select("*").eq("local_id", local_id) \
        .order("plato_nombre").execute().data or []
    return rows


@router.post("", response_model=RecetaLineaOut, status_code=status.HTTP_201_CREATED)
def agregar_linea(body: RecetaLineaIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()
    res = db.table("recetas").insert({
        "local_id": body.local_id, "plato_sku": body.plato_sku, "plato_nombre": body.plato_nombre,
        "ingrediente": body.ingrediente, "cantidad": body.cantidad, "unidad": body.unidad,
        "updated_by": claims["sub"],
    }).execute()
    return res.data[0]


@router.delete("/{linea_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_linea(linea_id: str, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    existente = db.table("recetas").select("local_id").eq("id", linea_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Línea de receta no encontrada")
    verificar_acceso_local(claims, existente.data[0]["local_id"])
    db.table("recetas").delete().eq("id", linea_id).execute()
