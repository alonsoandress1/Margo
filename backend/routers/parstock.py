from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import ParStockIn, ParStockItem, ParStockUpdateIn

router = APIRouter(prefix="/par-stock", tags=["par-stock"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar Par Stock")


def _item_de(par_row: dict, mapping: dict) -> ParStockItem:
    m = mapping.get(par_row["ingrediente_key"], {})
    return ParStockItem(
        ingrediente_key=par_row["ingrediente_key"], nombre=par_row["ingrediente_key"].split("||")[0],
        unidad=par_row["unidad"], categoria=par_row["categoria"], par_cantidad=par_row["par_cantidad"],
        odoo_name=m.get("odoo_name"), ref=m.get("ref"), supplier_name=m.get("supplier_name"),
        precio=m.get("price", 0), tamano_empaque=m.get("tamano_empaque"),
    )


@router.get("", response_model=list[ParStockItem])
def listar(local_id: str, claims: dict = Depends(get_current_claims)):
    verificar_acceso_local(claims, local_id)
    db = get_db()
    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).execute().data or []
    keys = [r["ingrediente_key"] for r in par_rows]
    mapping_rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data if keys else []
    mapping = {m["ingrediente_key"]: m for m in mapping_rows}
    return [_item_de(r, mapping) for r in par_rows]


@router.post("", response_model=ParStockItem, status_code=status.HTTP_201_CREATED)
def crear(body: ParStockIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    key = f"{body.nombre}||{body.unidad}"
    tamano = None if body.a_granel else body.tamano_empaque

    db.table("odoo_mapping").upsert({
        "ingrediente_key": key, "ref": body.ref, "odoo_id": body.odoo_id, "odoo_name": body.odoo_name,
        "supplier_id": body.supplier_id, "supplier_name": body.supplier_name,
        "price": body.precio, "tamano_empaque": tamano,
    }, on_conflict="ingrediente_key").execute()

    db.table("par_stock").upsert({
        "local_id": body.local_id, "ingrediente_key": key, "unidad": body.unidad,
        "categoria": body.categoria, "par_cantidad": body.par_cantidad,
    }, on_conflict="local_id,ingrediente_key").execute()

    mapping_row = db.table("odoo_mapping").select("*").eq("ingrediente_key", key).execute().data[0]
    par_row = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", key).execute().data[0]
    return _item_de(par_row, {key: mapping_row})


@router.patch("", response_model=ParStockItem)
def actualizar(body: ParStockUpdateIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    existente = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Insumo no encontrado para ese local")

    if body.par_cantidad is not None:
        db.table("par_stock").update({"par_cantidad": body.par_cantidad}) \
            .eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute()

    mapping_update = {"tamano_empaque": None if body.a_granel else body.tamano_empaque}
    if body.precio is not None:
        mapping_update["price"] = body.precio
    db.table("odoo_mapping").update(mapping_update).eq("ingrediente_key", body.ingrediente_key).execute()

    par_row = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute().data[0]
    mapping_row = db.table("odoo_mapping").select("*").eq("ingrediente_key", body.ingrediente_key).execute().data
    mapping = {body.ingrediente_key: mapping_row[0]} if mapping_row else {}
    return _item_de(par_row, mapping)
