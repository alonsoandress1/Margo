from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import RecetaLineaIn, RecetaLineaOut

router = APIRouter(prefix="/recetas", tags=["recetas"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede editar recetas")


def _linea_de(row: dict, plato: dict) -> RecetaLineaOut:
    return RecetaLineaOut(
        id=row["id"], plato_id=row["plato_id"], plato_sku=plato["sku"], plato_nombre=plato["nombre"],
        ingrediente_key=row.get("ingrediente_key"), ingrediente=row["ingrediente"],
        cantidad=row["cantidad"], unidad=row["unidad"],
    )


@router.get("", response_model=list[RecetaLineaOut])
def listar(local_id: str, claims: dict = Depends(get_current_claims)):
    verificar_acceso_local(claims, local_id)
    db = get_db()
    platos = db.table("platos").select("*").eq("local_id", local_id).execute().data or []
    if not platos:
        return []
    platos_por_id = {p["id"]: p for p in platos}
    rows = db.table("recetas").select("*").in_("plato_id", list(platos_por_id.keys())).execute().data or []
    return [_linea_de(r, platos_por_id[r["plato_id"]]) for r in rows]


@router.post("", response_model=RecetaLineaOut, status_code=status.HTTP_201_CREATED)
def agregar_linea(body: RecetaLineaIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()

    plato = db.table("platos").select("*").eq("id", body.plato_id).execute()
    if not plato.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plato no encontrado")
    verificar_acceso_local(claims, plato.data[0]["local_id"])

    res = db.table("recetas").insert({
        "plato_id": body.plato_id, "ingrediente_key": body.ingrediente_key,
        "ingrediente": body.ingrediente, "cantidad": body.cantidad, "unidad": body.unidad,
        "updated_by": claims["sub"],
    }).execute()
    return _linea_de(res.data[0], plato.data[0])


@router.delete("/{linea_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_linea(linea_id: str, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    existente = db.table("recetas").select("plato_id").eq("id", linea_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Línea de receta no encontrada")
    plato = db.table("platos").select("local_id").eq("id", existente.data[0]["plato_id"]).execute()
    if plato.data:
        verificar_acceso_local(claims, plato.data[0]["local_id"])
    db.table("recetas").delete().eq("id", linea_id).execute()
