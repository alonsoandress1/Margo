from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims
from ..schemas import CambiarPasswordIn, LoginRequest, LoginResponse, UsuarioOut
from ..security import create_access_token, hash_password, verify_password

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


@router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_password(body: CambiarPasswordIn, claims: dict = Depends(get_current_claims)):
    db = get_db()
    usuario = db.table("usuarios").select("password_hash").eq("id", claims["sub"]).execute().data
    if not usuario or not verify_password(body.password_actual, usuario[0]["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tu contraseña actual no es correcta")
    if len(body.password_nueva) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La nueva contraseña debe tener al menos 6 caracteres")

    db.table("usuarios").update({"password_hash": hash_password(body.password_nueva)}).eq("id", claims["sub"]).execute()
