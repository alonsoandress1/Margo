from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims, locales_permitidos, verificar_acceso_local
from ..schemas import PedidoEstadoIn, PedidoIn, PedidoOut, SugerenciaItem

router = APIRouter(prefix="/pedidos", tags=["pedidos"])

ESTADOS_VALIDOS = ("aprobado", "rechazado", "editado")


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
    return res.data or []


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
