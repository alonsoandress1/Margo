from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims
from ..schemas import LoginRequest, LoginResponse, UsuarioOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    db = get_db()
    res = db.table("usuarios").select("*").eq("email", body.email).eq("activo", True).execute()
    rows = res.data or []
    if not rows or not verify_password(body.password, rows[0]["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos")

    usuario = rows[0]
    locales: list[str] = []
    if usuario["rol"] == "solicitante":
        rel = db.table("usuario_locales").select("local_id").eq("usuario_id", usuario["id"]).execute()
        locales = [r["local_id"] for r in (rel.data or [])]

    token = create_access_token(usuario["id"], usuario["rol"])
    return LoginResponse(
        access_token=token,
        usuario=UsuarioOut(
            id=usuario["id"], email=usuario["email"], nombre=usuario["nombre"],
            rol=usuario["rol"], locales=locales,
        ),
    )


@router.get("/me", response_model=dict)
def me(claims: dict = Depends(get_current_claims)):
    return claims
