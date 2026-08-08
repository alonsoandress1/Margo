import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def create_access_token(usuario_id: str, rol: str) -> str:
    expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {"sub": usuario_id, "rol": rol, "exp": expire}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[ALGORITHM])
    except JWTError:
        return None
