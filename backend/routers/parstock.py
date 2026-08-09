from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import ParStockAddIn, ParStockItem, ParStockUpdateIn, ProductoOut

router = APIRouter(tags=["par-stock"])


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


@router.get("/productos", response_model=list[ProductoOut])
def listar_todos_productos(claims: dict = Depends(get_current_claims)):
    """Catalogo completo (todos los proveedores) -- para elegir al agregar a Par Stock."""
    db = get_db()
    rows = db.table("odoo_mapping").select("*").execute().data or []
    return [
        ProductoOut(
            ingrediente_key=r["ingrediente_key"], nombre=r["ingrediente_key"].split("||")[0],
            unidad=r["ingrediente_key"].split("||")[1] if "||" in r["ingrediente_key"] else "",
            proveedor_id=r.get("proveedor_id") or "", odoo_id=r["odoo_id"], odoo_name=r["odoo_name"],
            ref=r.get("ref"), precio=r.get("price", 0), tamano_empaque=r.get("tamano_empaque"),
        )
        for r in rows
    ]


@router.get("/par-stock", response_model=list[ParStockItem])
def listar(local_id: str, claims: dict = Depends(get_current_claims)):
    verificar_acceso_local(claims, local_id)
    db = get_db()
    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).execute().data or []
    keys = [r["ingrediente_key"] for r in par_rows]
    mapping_rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data if keys else []
    mapping = {m["ingrediente_key"]: m for m in mapping_rows}
    return [_item_de(r, mapping) for r in par_rows]


@router.post("/par-stock", response_model=ParStockItem, status_code=status.HTTP_201_CREATED)
def agregar(body: ParStockAddIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    producto = db.table("odoo_mapping").select("*").eq("ingrediente_key", body.ingrediente_key).execute()
    if not producto.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ese insumo no existe en el catalogo de Proveedores -- agrégalo ahí primero")
    unidad = body.ingrediente_key.split("||")[1] if "||" in body.ingrediente_key else ""

    db.table("par_stock").upsert({
        "local_id": body.local_id, "ingrediente_key": body.ingrediente_key, "unidad": unidad,
        "categoria": body.categoria, "par_cantidad": body.par_cantidad,
    }, on_conflict="local_id,ingrediente_key").execute()

    par_row = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute().data[0]
    return _item_de(par_row, {body.ingrediente_key: producto.data[0]})


@router.patch("/par-stock", response_model=ParStockItem)
def actualizar(body: ParStockUpdateIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    existente = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Insumo no encontrado para ese local")

    db.table("par_stock").update({"par_cantidad": body.par_cantidad}) \
        .eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute()

    par_row = db.table("par_stock").select("*").eq("local_id", body.local_id).eq("ingrediente_key", body.ingrediente_key).execute().data[0]
    mapping_row = db.table("odoo_mapping").select("*").eq("ingrediente_key", body.ingrediente_key).execute().data
    mapping = {body.ingrediente_key: mapping_row[0]} if mapping_row else {}
    return _item_de(par_row, mapping)
