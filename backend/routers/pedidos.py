import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, locales_permitidos, verificar_acceso_local
from ..schemas import GenerarOCIn, GenerarOCOut, PedidoEstadoIn, PedidoIn, PedidoOut, SugerenciaItem

# odoo_connector.py vive en la raiz del repo (lo comparte tambien la app de
# escritorio y los scripts de terminal) -- se agrega esa ruta para poder
# importarlo sin duplicar el archivo dentro del paquete backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooWebSession  # noqa: E402

router = APIRouter(prefix="/pedidos", tags=["pedidos"])

ESTADOS_VALIDOS = ("aprobado", "rechazado", "editado")


def _con_po_tracking(db, pedidos: list[dict]) -> list[dict]:
    if not pedidos:
        return pedidos
    ids = [p["id"] for p in pedidos]
    tracking = db.table("po_tracking").select("pedido_id,po_id,po_name").in_("pedido_id", ids).execute().data or []
    por_pedido = {t["pedido_id"]: t for t in tracking}
    for p in pedidos:
        t = por_pedido.get(p["id"])
        p["po_id"] = t["po_id"] if t else None
        p["po_name"] = t["po_name"] if t else None
    return pedidos


@router.get("/sugerencia", response_model=list[SugerenciaItem])
def sugerencia_compra(local_id: str, claims: dict = Depends(get_current_claims)):
    """Sugerencia basada en Par Stock - stock actual (bodega + cocina).
    Todavia no incluye demanda proyectada por pronostico de ventas (fase 2:
    requiere migrar el historial de ventas a Supabase)."""
    verificar_acceso_local(claims, local_id)
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).execute().data or []
    if not par_rows:
        return []
    keys = [r["ingrediente_key"] for r in par_rows]

    mov_rows = db.table("bodega_movimientos").select("ingrediente_key,tipo,cantidad") \
        .eq("local_id", local_id).in_("ingrediente_key", keys).execute().data or []
    stock_bodega: dict[str, float] = {}
    for m in mov_rows:
        signo = -1 if m["tipo"] == "egreso" else 1
        stock_bodega[m["ingrediente_key"]] = stock_bodega.get(m["ingrediente_key"], 0) + signo * m["cantidad"]

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,fecha,cantidad_informada") \
        .eq("local_id", local_id).in_("ingrediente_key", keys) \
        .order("fecha", desc=True).execute().data or []
    stock_cocina: dict[str, float] = {}
    for c in cocina_rows:
        stock_cocina.setdefault(c["ingrediente_key"], c["cantidad_informada"])  # primera = mas reciente (ya ordenado)

    mapping_rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data or []
    mapping = {m["ingrediente_key"]: m for m in mapping_rows}

    resultado = []
    for r in par_rows:
        key = r["ingrediente_key"]
        nombre = key.split("||")[0]
        en_bodega = stock_bodega.get(key, 0)
        en_cocina = stock_cocina.get(key, 0)
        disponible = en_bodega + en_cocina
        sugerido = max(0.0, r["par_cantidad"] - disponible)
        m = mapping.get(key, {})
        resultado.append(SugerenciaItem(
            ingrediente_key=key, nombre=nombre, unidad=r["unidad"], categoria=r["categoria"],
            par=r["par_cantidad"], stock_bodega=en_bodega, stock_cocina=en_cocina,
            sugerido=sugerido, precio=m.get("price", 0), proveedor=m.get("supplier_name"),
        ))
    return resultado


@router.get("", response_model=list[PedidoOut])
def listar_pedidos(local_id: str | None = None, claims: dict = Depends(get_current_claims)):
    db = get_db()
    permitidos = locales_permitidos(claims)

    if local_id:
        verificar_acceso_local(claims, local_id)
        q = db.table("pedidos").select("*").eq("local_id", local_id)
    else:
        if permitidos is not None:
            if not permitidos:
                return []
            q = db.table("pedidos").select("*").in_("local_id", permitidos)
        else:
            q = db.table("pedidos").select("*")

    res = q.order("created_at", desc=True).execute()
    return _con_po_tracking(db, res.data or [])


@router.post("", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def crear_pedido(body: PedidoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede crear pedidos")
    verificar_acceso_local(claims, body.local_id)

    db = get_db()
    res = db.table("pedidos").insert({
        "local_id": body.local_id,
        "items": body.items,
        "estado": "pendiente",
        "creado_por": claims["sub"],
    }).execute()
    return res.data[0]


@router.patch("/{pedido_id}/estado", response_model=PedidoOut)
def actualizar_estado(pedido_id: str, body: PedidoEstadoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede modificar pedidos")
    if body.estado not in ESTADOS_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Estado invalido, debe ser uno de: {ESTADOS_VALIDOS}")

    db = get_db()
    existente = db.table("pedidos").select("local_id").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    update = {
        "estado": body.estado,
        "revisado_por": claims["sub"],
        "revisado_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.items is not None:
        update["items"] = body.items

    res = db.table("pedidos").update(update).eq("id", pedido_id).execute()
    return res.data[0]


@router.post("/{pedido_id}/generar-oc", response_model=GenerarOCOut)
def generar_oc(pedido_id: str, body: GenerarOCIn, claims: dict = Depends(get_current_claims)):
    """Crea la Orden de Compra real en Odoo para un pedido ya aprobado.
    Las credenciales de Odoo viajan solo en este request, se usan una vez
    y se descartan -- nunca se guardan, ni siquiera encriptadas."""
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede generar OC")

    db = get_db()
    pedido_res = db.table("pedidos").select("*").eq("id", pedido_id).execute()
    if not pedido_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    pedido = pedido_res.data[0]
    verificar_acceso_local(claims, pedido["local_id"])

    if pedido["estado"] != "aprobado":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Solo se puede generar la OC de un pedido aprobado")

    ya_existe = db.table("po_tracking").select("po_name").eq("pedido_id", pedido_id).execute()
    if ya_existe.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Ya existe una OC para este pedido: {ya_existe.data[0]['po_name']}")

    keys = [i["ingrediente_key"] for i in pedido["items"] if i.get("ingrediente_key")]
    mapping_rows = db.table("odoo_mapping").select("*").in_("ingrediente_key", keys).execute().data if keys else []
    mapping = {m["ingrediente_key"]: m for m in mapping_rows}

    po_lines = []
    omitidos = []
    for item in pedido["items"]:
        key = item.get("ingrediente_key")
        m = mapping.get(key) if key else None
        if not m:
            omitidos.append(item.get("ingrediente", "?"))
            continue
        cantidad = float(item.get("cantidad", 0))
        unidad = (item.get("unidad") or "").lower()
        cantidad_kg = cantidad / 1000 if unidad == "g" else cantidad
        po_lines.append({
            "product_id": m["odoo_id"],
            "name": m["odoo_name"],
            "product_qty": round(cantidad_kg, 2),
            "price_unit": m.get("price", 0) or 0,
        })

    if not po_lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ningun insumo del pedido tiene mapeo a Odoo -- nada que generar")

    partner_id = next(iter(mapping.values()))["supplier_id"]
    proveedor = next(iter(mapping.values()))["supplier_name"]

    session = OdooWebSession(os.environ["ODOO_URL"])
    ok, msg = session.connect(body.email, body.password)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"No se pudo conectar a Odoo: {msg}")

    po_id, po_name = session.create_purchase_order(
        partner_id, po_lines, notes=f"Generado automaticamente -- pedido {pedido_id}")

    db.table("po_tracking").insert({
        "po_id": po_id, "po_name": po_name, "local_id": pedido["local_id"], "pedido_id": pedido_id,
        "proveedor": proveedor, "creado_por": claims["sub"],
    }).execute()

    return GenerarOCOut(po_id=po_id, po_name=po_name, omitidos=omitidos)
