from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
