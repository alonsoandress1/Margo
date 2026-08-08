from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_db
from .security import decode_access_token

_bearer = HTTPBearer()


def get_current_claims(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    claims = decode_access_token(creds.credentials)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido o expirado")
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
