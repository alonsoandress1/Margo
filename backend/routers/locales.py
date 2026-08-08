from fastapi import APIRouter, Depends

from ..db import get_db
from ..deps import get_current_claims, locales_permitidos
from ..schemas import LocalOut

router = APIRouter(prefix="/locales", tags=["locales"])


@router.get("", response_model=list[LocalOut])
def listar_locales(claims: dict = Depends(get_current_claims)):
    db = get_db()
    permitidos = locales_permitidos(claims)

    q = db.table("locales").select("*").eq("activo", True)
    if permitidos is not None:
        if not permitidos:
            return []
        q = q.in_("id", permitidos)
    res = q.execute()
    return res.data or []
