import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from ..catalogo import productos_mas_baratos
from ..db import get_db
from ..deps import get_current_claims, locales_permitidos, verificar_acceso_local
from ..email_sender import enviar_aviso_pedido
from ..schemas import (AccionCompra, FavoritoIn, GenerarOCIn, GenerarOCOut, PedidoEstadoIn,
                       PedidoIn, PedidoOut, SugerenciaItem)

# odoo_connector.py vive en la raiz del repo (lo comparte tambien la app de
# escritorio y los scripts de terminal) -- se agrega esa ruta para poder
# importarlo sin duplicar el archivo dentro del paquete backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooWebSession  # noqa: E402

router = APIRouter(prefix="/pedidos", tags=["pedidos"])

ESTADOS_VALIDOS = ("aprobado", "rechazado", "editado")


def _redondear_a_empaque(cantidad: float, tamano_empaque: float | None) -> float:
    """Redondea hacia arriba al multiplo del tamano de empaque -- no se
    puede pedir una cantidad que el proveedor no despacha tal cual
    (ej. Filete Salteado viene en paquetes de 1.6 kg)."""
    if not tamano_empaque or tamano_empaque <= 0 or cantidad <= 0:
        return cantidad
    paquetes = math.ceil(round(cantidad / tamano_empaque, 6))
    return round(paquetes * tamano_empaque, 3)


def _con_po_tracking(db, pedidos: list[dict]) -> list[dict]:
    if not pedidos:
        return pedidos
    ids = [p["id"] for p in pedidos]
    tracking = db.table("po_tracking").select("pedido_id,tipo,po_id,po_name,proveedor").in_("pedido_id", ids).execute().data or []
    por_pedido: dict[str, list] = {}
    for t in tracking:
        por_pedido.setdefault(t["pedido_id"], []).append(t)
    for p in pedidos:
        p["acciones"] = [
            {"proveedor": t["proveedor"], "tipo": t["tipo"], "po_id": t.get("po_id"), "po_name": t.get("po_name")}
            for t in por_pedido.get(p["id"], [])
        ]
    return pedidos


@router.get("/sugerencia", response_model=list[SugerenciaItem])
def sugerencia_compra(local_id: str, claims: dict = Depends(get_current_claims)):
    """Sugerencia basada en Par Stock - stock actual (bodega + cocina).
    Elige automaticamente el proveedor mas barato entre los registrados
    para cada insumo. Todavia no incluye demanda proyectada por
    pronostico de ventas (fase 2: requiere migrar el historial de ventas
    a Supabase)."""
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

    mapping = productos_mas_baratos(db, keys)

    resultado = []
    for r in par_rows:
        key = r["ingrediente_key"]
        nombre = key.split("||")[0]
        en_bodega = stock_bodega.get(key, 0)
        en_cocina = stock_cocina.get(key, 0)
        disponible = en_bodega + en_cocina
        sugerido = max(0.0, r["par_cantidad"] - disponible)
        m = mapping.get(key, {})
        sugerido = _redondear_a_empaque(sugerido, m.get("tamano_empaque"))
        resultado.append(SugerenciaItem(
            ingrediente_key=key, nombre=nombre, unidad=r["unidad"], categoria=r["categoria"],
            par=r["par_cantidad"], stock_bodega=en_bodega, stock_cocina=en_cocina,
            sugerido=sugerido, precio=m.get("price", 0), proveedor=m.get("supplier_name"),
            tamano_empaque=m.get("tamano_empaque"),
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
    return _con_po_tracking(db, res.data)[0]


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
    return _con_po_tracking(db, res.data)[0]


@router.patch("/{pedido_id}/favorito", response_model=PedidoOut)
def marcar_favorito(pedido_id: str, body: FavoritoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede marcar favoritos")

    db = get_db()
    existente = db.table("pedidos").select("local_id").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    res = db.table("pedidos").update({"favorito": body.favorito}).eq("id", pedido_id).execute()
    return _con_po_tracking(db, res.data)[0]


@router.delete("/{pedido_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_pedido(pedido_id: str, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede eliminar pedidos")

    db = get_db()
    existente = db.table("pedidos").select("local_id").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    con_acciones = db.table("po_tracking").select("id").eq("pedido_id", pedido_id).execute()
    if con_acciones.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No se puede eliminar: ya se generó una OC o aviso de compra para este pedido",
        )

    db.table("pedidos").delete().eq("id", pedido_id).execute()


@router.post("/{pedido_id}/generar-oc", response_model=GenerarOCOut)
def generar_oc(pedido_id: str, body: GenerarOCIn, claims: dict = Depends(get_current_claims)):
    """Genera la accion de compra de un pedido ya aprobado, insumo por
    insumo se elige el proveedor mas barato entre los registrados:
    - Si ese proveedor tiene integracion a Odoo (usa_odoo=true, hoy solo
      Doña Sofía), se crea la Orden de Compra real. Las credenciales de
      Odoo viajan solo en este request, se usan una vez y se descartan.
    - Si no, se envia un correo con el nombre del proveedor y las
      cantidades solicitadas, al destinatario configurado en Configuración."""
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

    ya_existe = db.table("po_tracking").select("id").eq("pedido_id", pedido_id).execute()
    if ya_existe.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya se generó una acción de compra para este pedido")

    local = db.table("locales").select("nombre").eq("id", pedido["local_id"]).execute().data[0]

    keys = [i["ingrediente_key"] for i in pedido["items"] if i.get("ingrediente_key")]
    mapping = productos_mas_baratos(db, keys)

    grupos: dict[str, list[tuple[dict, dict]]] = {}
    omitidos = []
    for item in pedido["items"]:
        key = item.get("ingrediente_key")
        m = mapping.get(key) if key else None
        if not m or not m.get("proveedor_id"):
            omitidos.append(item.get("ingrediente", "?"))
            continue
        grupos.setdefault(m["proveedor_id"], []).append((m, item))

    if not grupos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ningun insumo del pedido tiene un proveedor registrado -- nada que generar")

    proveedor_ids = list(grupos.keys())
    proveedores = {p["id"]: p for p in db.table("proveedores").select("*").in_("id", proveedor_ids).execute().data or []}

    acciones: list[AccionCompra] = []
    odoo_session: OdooWebSession | None = None

    for proveedor_id, entradas in grupos.items():
        proveedor = proveedores.get(proveedor_id)
        nombre_proveedor = proveedor["nombre"] if proveedor else "Proveedor desconocido"

        if proveedor and proveedor.get("usa_odoo"):
            if not body.email or not body.password:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Faltan credenciales de Odoo para generar la OC de {nombre_proveedor}")
            if odoo_session is None:
                odoo_session = OdooWebSession(os.environ["ODOO_URL"])
                ok, msg = odoo_session.connect(body.email, body.password)
                if not ok:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"No se pudo conectar a Odoo: {msg}")

            po_lines = []
            for m, item in entradas:
                cantidad = float(item.get("cantidad", 0))
                unidad = (item.get("unidad") or "").lower()
                cantidad_kg = cantidad / 1000 if unidad == "g" else cantidad
                cantidad_kg = _redondear_a_empaque(cantidad_kg, m.get("tamano_empaque"))
                po_lines.append({
                    "product_id": m["odoo_id"], "name": m["odoo_name"],
                    "product_qty": round(cantidad_kg, 2), "price_unit": m.get("price", 0) or 0,
                })

            po_id, po_name = odoo_session.create_purchase_order(
                proveedor["odoo_supplier_id"], po_lines, notes=f"Generado automaticamente -- pedido {pedido_id}")

            db.table("po_tracking").insert({
                "tipo": "odoo", "po_id": po_id, "po_name": po_name, "local_id": pedido["local_id"],
                "pedido_id": pedido_id, "proveedor": nombre_proveedor, "creado_por": claims["sub"],
            }).execute()
            acciones.append(AccionCompra(proveedor=nombre_proveedor, tipo="odoo", po_id=po_id, po_name=po_name))
        else:
            config = db.table("configuracion_email").select("destinatario").limit(1).execute()
            if not config.data:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "No hay un destinatario de correo configurado (ve a Proveedores)")
            items_email = [{"ingrediente": item.get("ingrediente", "?"), "cantidad": item.get("cantidad", 0), "unidad": item.get("unidad", "")}
                            for _, item in entradas]
            try:
                enviar_aviso_pedido(config.data[0]["destinatario"], nombre_proveedor, local["nombre"], items_email)
            except KeyError as e:
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e} para poder enviar correos")
            except Exception as e:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo enviar el correo a {nombre_proveedor}: {e}")

            db.table("po_tracking").insert({
                "tipo": "email", "local_id": pedido["local_id"], "pedido_id": pedido_id,
                "proveedor": nombre_proveedor, "creado_por": claims["sub"],
            }).execute()
            acciones.append(AccionCompra(proveedor=nombre_proveedor, tipo="email"))

    return GenerarOCOut(acciones=acciones, omitidos=omitidos)
