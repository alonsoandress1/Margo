import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


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
