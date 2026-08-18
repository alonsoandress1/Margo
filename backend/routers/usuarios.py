from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

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
    actual = existente.data[0]

    # Si este usuario es HOY administrador activo y el cambio lo dejaria de
    # ser (desactivarlo o bajarle el rol), hay que asegurarse de que quede
    # al menos otro administrador activo -- si no, el sistema queda sin
    # nadie que pueda gestionar usuarios (solo se arreglaria entrando
    # directo a Supabase). Mismo espiritu que la proteccion de
    # auto-eliminacion en eliminar() mas abajo.
    deja_de_ser_admin_activo = (
        actual["rol"] == "administrador" and actual["activo"]
        and ((body.rol is not None and body.rol != "administrador") or body.activo is False)
    )
    if deja_de_ser_admin_activo:
        otros_admins = db.table("usuarios").select("id").eq("rol", "administrador") \
            .eq("activo", True).neq("id", usuario_id).execute()
        if not otros_admins.data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                "No puedes dejar el sistema sin ningún administrador activo -- agrega o reactiva otro admin primero")

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


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(usuario_id: str, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    if usuario_id == claims["sub"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes eliminar tu propia cuenta")
    db = get_db()

    existente = db.table("usuarios").select("id").eq("id", usuario_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    db.table("usuario_locales").delete().eq("usuario_id", usuario_id).execute()
    try:
        db.table("usuarios").delete().eq("id", usuario_id).execute()
    except APIError as e:
        # 23503 = foreign_key_violation -- el usuario tiene historial real
        # (pedidos creados, facturas procesadas, etc.) referenciado sin cascada
        # a proposito, para no perder auditoria. En ese caso no se puede
        # borrar de verdad -- la salida correcta es Desactivar.
        if e.code == "23503":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "No se puede eliminar: este usuario tiene historial asociado (pedidos, facturas, etc.). Usa \"Desactivar\" en su lugar.",
            ) from e
        raise
