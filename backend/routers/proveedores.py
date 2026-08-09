from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims
from ..schemas import ProductoIn, ProductoOut, ProductoUpdateIn, ProveedorIn, ProveedorOut

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar proveedores")


def _producto_de(row: dict) -> ProductoOut:
    return ProductoOut(
        id=row["id"], ingrediente_key=row["ingrediente_key"], nombre=row["ingrediente_key"].split("||")[0],
        unidad=row["ingrediente_key"].split("||")[1] if "||" in row["ingrediente_key"] else "",
        proveedor_id=row["proveedor_id"], odoo_id=row["odoo_id"], odoo_name=row["odoo_name"],
        ref=row.get("ref"), precio=row.get("price", 0), tamano_empaque=row.get("tamano_empaque"),
    )


@router.get("", response_model=list[ProveedorOut])
def listar_proveedores(claims: dict = Depends(get_current_claims)):
    db = get_db()
    return db.table("proveedores").select("*").eq("activo", True).execute().data or []


@router.post("", response_model=ProveedorOut, status_code=status.HTTP_201_CREATED)
def crear_proveedor(body: ProveedorIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    res = db.table("proveedores").insert({
        "nombre": body.nombre, "odoo_supplier_id": body.odoo_supplier_id, "usa_odoo": body.usa_odoo,
    }).execute()
    return res.data[0]


@router.get("/{proveedor_id}/productos", response_model=list[ProductoOut])
def listar_productos(proveedor_id: str, claims: dict = Depends(get_current_claims)):
    db = get_db()
    rows = db.table("odoo_mapping").select("*").eq("proveedor_id", proveedor_id).execute().data or []
    return [_producto_de(r) for r in rows]


@router.post("/{proveedor_id}/productos", response_model=ProductoOut, status_code=status.HTTP_201_CREATED)
def crear_producto(proveedor_id: str, body: ProductoIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()

    prov = db.table("proveedores").select("*").eq("id", proveedor_id).execute()
    if not prov.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proveedor no encontrado")

    key = f"{body.nombre}||{body.unidad}"
    tamano = None if body.a_granel else body.tamano_empaque

    # un mismo insumo (ingrediente_key) puede tener hasta 3 filas, una por
    # proveedor -- el conflicto se resuelve por (ingrediente_key, proveedor_id),
    # no por ingrediente_key solo, para permitir varias opciones de compra
    db.table("odoo_mapping").upsert({
        "ingrediente_key": key, "proveedor_id": proveedor_id,
        "ref": body.ref, "odoo_id": body.odoo_id, "odoo_name": body.odoo_name,
        "supplier_id": prov.data[0]["odoo_supplier_id"], "supplier_name": prov.data[0]["nombre"],
        "price": body.precio, "tamano_empaque": tamano,
    }, on_conflict="ingrediente_key,proveedor_id").execute()

    row = db.table("odoo_mapping").select("*").eq("ingrediente_key", key).eq("proveedor_id", proveedor_id).execute().data[0]
    return _producto_de(row)


@router.patch("/{proveedor_id}/productos", response_model=ProductoOut)
def actualizar_producto(proveedor_id: str, body: ProductoUpdateIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()

    existente = db.table("odoo_mapping").select("*").eq("ingrediente_key", body.ingrediente_key).eq("proveedor_id", proveedor_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado para ese proveedor")

    update = {"tamano_empaque": None if body.a_granel else body.tamano_empaque}
    if body.precio is not None:
        update["price"] = body.precio
    db.table("odoo_mapping").update(update).eq("id", existente.data[0]["id"]).execute()

    row = db.table("odoo_mapping").select("*").eq("id", existente.data[0]["id"]).execute().data[0]
    return _producto_de(row)
