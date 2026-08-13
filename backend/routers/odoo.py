import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_claims, get_odoo_credentials

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooWebSession  # noqa: E402

router = APIRouter(prefix="/odoo", tags=["odoo"])


@router.get("/empresas")
def listar_empresas(claims: dict = Depends(get_current_claims),
                     odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Empresas de Odoo a las que tiene acceso la persona recien conectada
    -- el frontend lo llama justo despues de pedir las credenciales de Odoo
    (una vez por sesion de pestaña) para saber si tiene que pedirle tambien
    que elija con cual empresa va a trabajar (si tiene acceso a 2 o mas) o
    si puede seguir de largo (si solo tiene una, como la mayoria)."""
    usuario, password = odoo_creds
    try:
        session = OdooWebSession(os.environ["ODOO_URL"])
        ok, msg = session.connect(usuario, password)
    except KeyError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
    if not ok:
        if "login rechazado" in msg.lower():
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, f"Odoo: {msg}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo conectar a Odoo: {msg}")
    return session.listar_empresas()
