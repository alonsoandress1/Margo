from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_db
from .security import decode_access_token

_bearer = HTTPBearer()


def get_current_claims(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    claims = decode_access_token(creds.credentials)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido o expirado")

    # El JWT por si solo no sabe si el usuario fue desactivado o le cambiaron
    # el rol despues de emitirlo -- sin esto, un token seguia siendo valido
    # con los permisos viejos hasta por 8 horas (JWT_EXPIRE_MINUTES).
    db = get_db()
    usuario = db.table("usuarios").select("rol,activo").eq("id", claims["sub"]).execute().data
    if not usuario or not usuario[0]["activo"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tu cuenta fue desactivada")
    claims["rol"] = usuario[0]["rol"]
    return claims


def require_roles(*roles: str):
    def _check(claims: dict = Depends(get_current_claims)) -> dict:
        if claims.get("rol") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esto")
        return claims
    return _check


def locales_permitidos(claims: dict) -> list[str] | None:
    """None significa 'todos los locales' (administrador/observador).
    Lista vacia o con ids significa acceso restringido (solicitante)."""
    if claims["rol"] in ("administrador", "observador"):
        return None
    db = get_db()
    rel = db.table("usuario_locales").select("local_id").eq("usuario_id", claims["sub"]).execute()
    return [r["local_id"] for r in (rel.data or [])]


def verificar_acceso_local(claims: dict, local_id: str):
    permitidos = locales_permitidos(claims)
    if permitidos is not None and local_id not in permitidos:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a ese local")


def get_odoo_credentials(
    x_odoo_user: str | None = Header(default=None),
    x_odoo_password: str | None = Header(default=None),
) -> tuple[str, str]:
    """Credenciales de Odoo de la persona que esta usando el sistema --
    nunca una cuenta de servicio compartida (pedido explicito del usuario:
    "ninguna cuenta lo es"). El navegador las manda en estos headers una vez
    que el admin las escribio (una vez por sesion de pestaña, nunca se
    guardan en la base de datos -- ver frontend/app.js). 428 (no 401) para
    que el frontend pueda distinguir "falta iniciar sesion en Odoo" de
    "la sesion de la app expiro" sin tocar el manejo de 401 ya existente."""
    if not x_odoo_user or not x_odoo_password:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "Faltan tus credenciales de Odoo")
    return x_odoo_user, x_odoo_password
