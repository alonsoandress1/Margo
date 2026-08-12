from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims
from ..schemas import UsuarioAdminOut, UsuarioCreateIn, UsuarioUpdateIn
from ..security import hash_password

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

ROLES_VALIDOS = ("solicitante", "administrador", "observador")


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar usuarios")


def _con_locales(db, usuarios: list[dict]) -> list[dict]:
    if not usuarios:
        return usuarios
    ids = [u["id"] for u in usuarios]
    rel = db.table("usuario_locales").select("usuario_id,local_id").in_("usuario_id", ids).execute().data or []
    por_usuario: dict[str, list[str]] = {}
    for r in rel:
        por_usuario.setdefault(r["usuario_id"], []).append(r["local_id"])
    for u in usuarios:
        u["locales"] = por_usuario.get(u["id"], [])
    return usuarios


@router.get("", response_model=list[UsuarioAdminOut])
def listar(claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    rows = db.table("usuarios").select("id,email,nombre,rol,activo").order("nombre").execute().data or []
    return _con_locales(db, rows)


@router.post("", response_model=UsuarioAdminOut, status_code=status.HTTP_201_CREATED)
def crear(body: UsuarioCreateIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    if body.rol not in ROLES_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rol inválido, debe ser uno de: {ROLES_VALIDOS}")
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña debe tener al menos 6 caracteres")
    db = get_db()

    existente = db.table("usuarios").select("id").eq("email", body.email).execute()
    if existente.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya existe un usuario con ese email")

    res = db.table("usuarios").insert({
        "email": body.email, "nombre": body.nombre, "rol": body.rol,
        "password_hash": hash_password(body.password), "activo": True,
    }).execute()
    usuario = res.data[0]

    if body.rol == "solicitante" and body.locales:
        db.table("usuario_locales").insert([
            {"usuario_id": usuario["id"], "local_id": lid} for lid in body.locales
        ]).execute()

    usuario["locales"] = body.locales if body.rol == "solicitante" else []
    return usuario


@router.patch("/{usuario_id}", response_model=UsuarioAdminOut)
def actualizar(usuario_id: str, body: UsuarioUpdateIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()

    existente = db.table("usuarios").select("*").eq("id", usuario_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    update = {}
    if body.nombre is not None:
        update["nombre"] = body.nombre
    if body.rol is not None:
        if body.rol not in ROLES_VALIDOS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rol inválido, debe ser uno de: {ROLES_VALIDOS}")
        update["rol"] = body.rol
    if body.activo is not None:
        update["activo"] = body.activo
    if body.password:
        if len(body.password) < 6:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña debe tener al menos 6 caracteres")
        update["password_hash"] = hash_password(body.password)

    if update:
        db.table("usuarios").update(update).eq("id", usuario_id).execute()

    if body.locales is not None:
        db.table("usuario_locales").delete().eq("usuario_id", usuario_id).execute()
        if body.locales:
            db.table("usuario_locales").insert([
                {"usuario_id": usuario_id, "local_id": lid} for lid in body.locales
            ]).execute()

    usuario = db.table("usuarios").select("id,email,nombre,rol,activo").eq("id", usuario_id).execute().data[0]
    return _con_locales(db, [usuario])[0]
