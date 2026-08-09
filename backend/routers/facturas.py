import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import (FacturaAceptarIn, FacturaLineaPreview, FacturaPreview,
                       FacturasBuscarIn, FacturaTrackingOut)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooWebSession  # noqa: E402

router = APIRouter(prefix="/facturas", tags=["facturas"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar facturas de proveedor")


@router.post("/buscar", response_model=list[FacturaPreview])
def buscar(body: FacturasBuscarIn, claims: dict = Depends(get_current_claims)):
    """Trae facturas nuevas (no procesadas todavia) de Odoo para los
    proveedores con integracion Odoo -- solo lectura, no escribe nada.
    Las credenciales viajan solo en este request y se descartan al terminar."""
    _require_admin(claims)
    db = get_db()

    proveedores_odoo = db.table("proveedores").select("*").eq("usa_odoo", True).eq("activo", True).execute().data or []
    if not proveedores_odoo:
        return []

    ya_procesadas = [r["odoo_invoice_id"] for r in db.table("factura_tracking").select("odoo_invoice_id").execute().data or []]

    session = OdooWebSession(os.environ["ODOO_URL"])
    ok, msg = session.connect(body.email, body.password)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"No se pudo conectar a Odoo: {msg}")

    proveedor_ids = [p["id"] for p in proveedores_odoo]
    productos = db.table("odoo_mapping").select("odoo_id,ingrediente_key").in_("proveedor_id", proveedor_ids).execute().data or []
    ingrediente_por_odoo_id = {p["odoo_id"]: p["ingrediente_key"] for p in productos}

    resultado: list[FacturaPreview] = []
    for prov in proveedores_odoo:
        try:
            facturas = session.buscar_facturas_proveedor(prov["odoo_supplier_id"], ya_procesadas)
        except Exception as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudieron leer las facturas de {prov['nombre']}: {e}")

        for f in facturas:
            lineas = [
                FacturaLineaPreview(
                    ingrediente_key=ingrediente_por_odoo_id.get(l["product_id"]), nombre=l["product_name"],
                    cantidad=l["cantidad"], reconocido=l["product_id"] in ingrediente_por_odoo_id,
                )
                for l in f["lineas"]
            ]
            resultado.append(FacturaPreview(
                odoo_invoice_id=f["id"], odoo_invoice_name=f["name"], proveedor=prov["nombre"],
                fecha=f.get("fecha"), total=f.get("total", 0), lineas=lineas,
            ))
    return resultado


@router.post("/aceptar", response_model=FacturaTrackingOut, status_code=status.HTTP_201_CREATED)
def aceptar(body: FacturaAceptarIn, claims: dict = Depends(get_current_claims)):
    """Registra el ingreso a Bodega de los insumos reconocidos de una
    factura ya revisada por un admin. No vuelve a tocar Odoo -- usa las
    lineas que ya se trajeron en /buscar."""
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    ya = db.table("factura_tracking").select("id").eq("odoo_invoice_id", body.odoo_invoice_id).execute()
    if ya.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta factura ya fue procesada")

    reconocidas = [l for l in body.lineas if l.reconocido and l.ingrediente_key]
    if not reconocidas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ningun insumo de esta factura esta registrado en el catalogo -- nada que ingresar")

    ahora = datetime.now(timezone.utc).isoformat()
    for l in reconocidas:
        db.table("bodega_movimientos").insert({
            "local_id": body.local_id, "ingrediente_key": l.ingrediente_key, "tipo": "ingreso",
            "cantidad": l.cantidad, "origen": "factura", "ref": body.odoo_invoice_name,
            "nota": f"Factura Odoo {body.odoo_invoice_name} ({body.proveedor})",
            "fecha": ahora, "created_by": claims["sub"],
        }).execute()

    res = db.table("factura_tracking").insert({
        "odoo_invoice_id": body.odoo_invoice_id, "odoo_invoice_name": body.odoo_invoice_name,
        "proveedor": body.proveedor, "local_id": body.local_id,
        "items": [l.model_dump() for l in body.lineas],
        "procesada_por": claims["sub"],
    }).execute()
    return res.data[0]


@router.get("", response_model=list[FacturaTrackingOut])
def historial(claims: dict = Depends(get_current_claims)):
    db = get_db()
    return db.table("factura_tracking").select("*").order("procesada_en", desc=True).limit(100).execute().data or []
