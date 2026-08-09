from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims
from ..schemas import ConfiguracionEmailIn, ConfiguracionEmailOut

router = APIRouter(prefix="/configuracion", tags=["configuracion"])


@router.get("/email", response_model=ConfiguracionEmailOut)
def obtener(claims: dict = Depends(get_current_claims)):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede ver esta configuración")
    db = get_db()
    res = db.table("configuracion_email").select("*").limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay configuración de correo todavía")
    return res.data[0]


@router.patch("/email", response_model=ConfiguracionEmailOut)
def actualizar(body: ConfiguracionEmailIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede editar esta configuración")
    db = get_db()
    existente = db.table("configuracion_email").select("id").limit(1).execute()
    if existente.data:
        res = db.table("configuracion_email").update({
            "destinatario": body.destinatario, "cc": body.cc, "updated_by": claims["sub"],
        }).eq("id", existente.data[0]["id"]).execute()
    else:
        res = db.table("configuracion_email").insert({
            "destinatario": body.destinatario, "cc": body.cc, "updated_by": claims["sub"],
        }).execute()
    return res.data[0]
