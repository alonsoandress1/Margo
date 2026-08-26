import os
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError

from ..catalogo import _producto_de
from ..db import get_db
from ..deps import get_current_claims, get_odoo_credentials

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402

from ..schemas import (AhorroMensualOut, AlertaPrecioOut, ItemAhorroOut, ProductoIn, ProductoOut,
                       ProductoUpdateIn, ProveedorConfigIn, ProveedorIn, ProveedorOdooOut, ProveedorOut)

router = APIRouter(prefix="/proveedores", tags=["proveedores"])


def _odoo(odoo_creds: tuple[str, str]) -> OdooClient:
    """Conecta con las credenciales de Odoo de la persona que esta usando el
    sistema en este momento -- nunca una cuenta compartida (pedido explicito
    del usuario). El navegador las manda en cada request (headers
    X-Odoo-User/X-Odoo-Password, ver get_odoo_credentials en deps.py);
    nunca se guardan en la base de datos. Mismo patron que facturas_dte.py."""
    usuario, password = odoo_creds
    try:
        cliente = OdooClient(os.environ["ODOO_URL"], os.environ["ODOO_DB"], usuario, password)
    except KeyError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
    ok, msg = cliente.connect()
    if not ok:
        if "credenciales incorrectas" in msg.lower():
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, f"Odoo: {msg}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo conectar a Odoo: {msg}")
    return cliente


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar proveedores")


def _require_lectura(claims: dict):
    """Observador puede ver todo (pedido explicito del usuario), nunca
    cambiar nada -- se usa solo en los endpoints puramente de lectura."""
    if claims["rol"] not in ("administrador", "observador"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso")


@router.get("", response_model=list[ProveedorOut])
def listar_proveedores(claims: dict = Depends(get_current_claims)):
    db = get_db()
    return db.table("proveedores").select("*").eq("activo", True).execute().data or []


@router.post("", response_model=ProveedorOut, status_code=status.HTTP_201_CREATED)
def crear_proveedor(body: ProveedorIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    try:
        res = db.table("proveedores").insert({
            "nombre": body.nombre, "odoo_supplier_id": body.odoo_supplier_id, "usa_odoo": body.usa_odoo,
        }).execute()
    except APIError as e:
        if e.code != "23505":
            raise
        # Ya existia un proveedor con ese odoo_supplier_id -- probablemente
        # se habia eliminado antes (soft-delete, ver eliminar_proveedor) y
        # se esta volviendo a agregar, a mano o desde "Buscar en Odoo".
        # Reactivar en vez de fallar, para que eliminar sea reversible sin
        # arriesgar filas duplicadas para el mismo proveedor real.
        res = db.table("proveedores").update({
            "nombre": body.nombre, "usa_odoo": body.usa_odoo, "activo": True,
        }).eq("odoo_supplier_id", body.odoo_supplier_id).execute()
    return res.data[0]


@router.delete("/{proveedor_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_proveedor(proveedor_id: str, claims: dict = Depends(get_current_claims)):
    """Elimina (desactiva) un proveedor -- no se borra de verdad porque sus
    productos (odoo_mapping) e historial de precios/compras siguen
    referenciandolo; solo deja de aparecer en las listas para elegir.
    Reversible: volver a agregarlo (a mano o desde "Buscar en Odoo" con el
    mismo proveedor real) lo reactiva en vez de duplicarlo (ver
    crear_proveedor)."""
    _require_admin(claims)
    db = get_db()
    existente = db.table("proveedores").select("id").eq("id", proveedor_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proveedor no encontrado")
    db.table("proveedores").update({"activo": False}).eq("id", proveedor_id).execute()


@router.patch("/{proveedor_id}/config", response_model=ProveedorOut)
def actualizar_config_proveedor(proveedor_id: str, body: ProveedorConfigIn, claims: dict = Depends(get_current_claims)):
    """Agenda del proveedor -- dias_entrega (cuanto tarda en llegar el
    pedido, se suma como consumo proyectado a la sugerencia de compra) y
    dias_pedido (que dias de la semana corresponde pedirle, dispara la
    tarjeta de recordatorio en Vista Resumen). Los dos campos se mandan
    siempre juntos -- no hay edicion parcial de uno solo."""
    _require_admin(claims)
    if body.dias_entrega < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dias_entrega no puede ser negativo")
    if any(d < 0 or d > 6 for d in body.dias_pedido):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dias_pedido debe ser 0 (Lunes) a 6 (Domingo)")
    db = get_db()
    existente = db.table("proveedores").select("id").eq("id", proveedor_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proveedor no encontrado")
    res = db.table("proveedores").update({
        "dias_entrega": body.dias_entrega, "dias_pedido": body.dias_pedido,
    }).eq("id", proveedor_id).execute()
    return res.data[0]


@router.get("/alerta-pedido-hoy", response_model=list[ProveedorOut])
def alerta_pedido_hoy(claims: dict = Depends(get_current_claims)):
    """Proveedores activos a los que corresponde pedirles hoy (dias_pedido
    incluye el dia de hoy) -- puramente informativo para la tarjeta de
    recordatorio en Vista Resumen, nunca genera nada solo. No verifica si
    el pedido de hoy ya se generó -- simplificacion consciente, se puede
    agregar despues cruzando contra po_tracking si en la practica molesta."""
    _require_lectura(claims)
    db = get_db()
    hoy = date.today().weekday()  # 0=Lunes..6=Domingo
    proveedores = db.table("proveedores").select("*").eq("activo", True).execute().data or []
    return [p for p in proveedores if hoy in (p.get("dias_pedido") or [])]


@router.get("/{proveedor_id}/verificar-unidades")
def verificar_unidades(proveedor_id: str, claims: dict = Depends(get_current_claims),
                        odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Compara la unidad base guardada de cada producto de este proveedor
    contra la unidad de COMPRA real que ese producto tiene configurada en
    Odoo (product.product.uom_po_id) -- para encontrar insumos cargados
    con la unidad equivocada (ej. "Filete para Churrascos" guardado como
    "un" cuando en Odoo se compra por "kg") sin adivinar por el nombre.
    Mismo mecanismo de resolucion kg/un que ya usa facturas_dte.py al
    sugerir la unidad de una linea de factura (ids estandar de Odoo
    product_uom_kgm/product_uom_unit). Solo lectura, no cambia nada --
    la correccion se sigue haciendo a mano en la tabla de productos."""
    _require_lectura(claims)
    db = get_db()

    # Red de seguridad -- envuelve TODO lo que sigue (conexion a Odoo
    # incluida) para que un error inesperado cualquiera nunca vuelva un 500
    # en blanco -- siempre un mensaje con el texto real del error, para
    # poder diagnosticar sin tener que adivinar.
    try:
        cliente = _odoo(odoo_creds)
        productos = db.table("odoo_mapping").select("ingrediente_key,odoo_id,unidad") \
            .eq("proveedor_id", proveedor_id).execute().data or []
        if not productos:
            return []
        odoo_ids = list({p["odoo_id"] for p in productos})

        ids_uom = cliente._call('ir.model.data', 'search_read',
            [[['module', '=', 'uom'], ['name', 'in', ['product_uom_kgm', 'product_uom_unit']]]],
            {'fields': ['name', 'res_id']})
        uom_por_nombre = {u['name']: u['res_id'] for u in ids_uom}
        unidad_por_uom_id: dict[int, str] = {}
        if uom_por_nombre.get('product_uom_kgm'):
            unidad_por_uom_id[uom_por_nombre['product_uom_kgm']] = 'kg'
        if uom_por_nombre.get('product_uom_unit'):
            unidad_por_uom_id[uom_por_nombre['product_uom_unit']] = 'un'

        # Productos cuyo odoo_id ya no existe en Odoo (eliminado despues de
        # agregarlo aca) tiran MissingError en 'read' -- se leen de a uno
        # en ese caso para no perder la verificacion completa por un id malo.
        try:
            productos_odoo = cliente._call('product.product', 'read', [odoo_ids], {'fields': ['uom_po_id']})
        except Exception:
            productos_odoo = []
            for odoo_id in odoo_ids:
                try:
                    productos_odoo.extend(cliente._call('product.product', 'read', [[odoo_id]], {'fields': ['uom_po_id']}))
                except Exception:
                    continue
        unidad_real_por_odoo_id = {
            p['id']: unidad_por_uom_id.get(p['uom_po_id'][0]) if p.get('uom_po_id') else None
            for p in productos_odoo
        }

        discrepancias = []
        for p in productos:
            unidad_real = unidad_real_por_odoo_id.get(p["odoo_id"])
            if unidad_real and unidad_real != p["unidad"]:
                discrepancias.append({
                    "ingrediente_key": p["ingrediente_key"],
                    "nombre": p["ingrediente_key"].split("||")[0],
                    "unidad_actual": p["unidad"],
                    "unidad_real_odoo": unidad_real,
                })
        return sorted(discrepancias, key=lambda d: d["nombre"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo verificar contra Odoo: {type(e).__name__}: {e}")


@router.get("/odoo/candidatos", response_model=list[ProveedorOdooOut])
def buscar_proveedores_odoo(claims: dict = Depends(get_current_claims),
                             odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Proveedores reales que ya tienen al menos una factura (DTE) en Odoo,
    para agregarlos sin escribir nombre/ID a mano -- solo lectura de Odoo,
    nunca se crea ni modifica nada alla. El RUT real se cruza contra
    res.partner (mismo criterio de matcheo por "vat" que ya usa
    facturas_dte.py::marcar_ingresada_manual) para resolver el id interno
    real, y se excluyen los que ya estan registrados como proveedor activo
    en nuestra tabla."""
    _require_admin(claims)
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[]], {'fields': ['issuer_rut', 'issuer_name']})
    nombre_por_rut: dict[str, str] = {}
    for d in docs:
        rut = d.get('issuer_rut')
        if rut:
            nombre_por_rut[rut] = d.get('issuer_name') or nombre_por_rut.get(rut, '')
    if not nombre_por_rut:
        return []

    partners = cliente._call('res.partner', 'search_read',
        [[['vat', 'in', list(nombre_por_rut.keys())]]], {'fields': ['id', 'vat']})
    partner_por_rut = {p['vat']: p['id'] for p in partners if p.get('vat')}

    db = get_db()
    ya_registrados = {p["odoo_supplier_id"] for p in
                       db.table("proveedores").select("odoo_supplier_id").eq("activo", True).execute().data or []}

    resultado = [
        ProveedorOdooOut(rut=rut, nombre=nombre, odoo_supplier_id=partner_por_rut[rut])
        for rut, nombre in nombre_por_rut.items()
        if rut in partner_por_rut and partner_por_rut[rut] not in ya_registrados
    ]
    return sorted(resultado, key=lambda p: p.nombre)


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
        "price": body.precio, "tamano_empaque": tamano, "unidad_odoo": body.unidad_odoo,
        "precio_negociado": body.precio_negociado,
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
    producto_id = existente.data[0]["id"]

    if body.unidad is not None:
        key_actual = existente.data[0]["ingrediente_key"]
        nombre, _, unidad_actual = key_actual.partition("||")
        if body.unidad != unidad_actual:
            nueva_key = f"{nombre}||{body.unidad}"
            # Renombra en una sola transaccion (odoo_mapping de TODOS los
            # proveedores que venden este insumo, Par Stock, bodega_movimientos,
            # stock_cocina, ventas_recetas) -- si algo choca en el camino, se
            # aborta completo y no queda nada a medio migrar.
            try:
                db.rpc("renombrar_unidad_insumo", {
                    "p_old_key": key_actual, "p_new_key": nueva_key, "p_nueva_unidad": body.unidad,
                }).execute()
            except Exception as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo cambiar la unidad: {e}")

    update = {
        "tamano_empaque": None if body.a_granel else body.tamano_empaque, "unidad_odoo": body.unidad_odoo,
        "precio_negociado": body.precio_negociado,
    }
    if body.precio is not None:
        update["price"] = body.precio
    db.table("odoo_mapping").update(update).eq("id", producto_id).execute()

    row = db.table("odoo_mapping").select("*").eq("id", producto_id).execute().data[0]
    return _producto_de(row)


@router.delete("/{proveedor_id}/productos/{producto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_producto(proveedor_id: str, producto_id: str, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()

    existente = db.table("odoo_mapping").select("ingrediente_key").eq("id", producto_id).eq("proveedor_id", proveedor_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Producto no encontrado para ese proveedor")

    en_par_stock = db.table("par_stock").select("local_id").eq("ingrediente_key", existente.data[0]["ingrediente_key"]).execute()
    if en_par_stock.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No se puede eliminar: está agregado en Par Stock de uno o más locales -- quítalo de ahí primero",
        )

    db.table("odoo_mapping").delete().eq("id", producto_id).execute()


@router.get("/alertas-precio", response_model=list[AlertaPrecioOut])
def listar_alertas_precio(claims: dict = Depends(get_current_claims)):
    """Dos tipos de alerta, generadas solas al crear una factura en
    Facturas Odoo (ver facturas_dte.py::_alimentar_stock_bodega):
    'sobreprecio' (el precio de esta factura superó el precio_negociado de
    ESE proveedor) y 'oportunidad' (cualquier proveedor facturó más barato
    que el mejor precio_negociado vigente entre todos, para evaluar
    cambiar de proveedor prioritario). No se borran al resolverlas (solo
    se marcan), para que el reporte de Ahorro por Acuerdos Comerciales las
    siga contando igual."""
    _require_lectura(claims)
    db = get_db()
    alertas = db.table("alertas_precio_factura").select("*").eq("resuelta", False) \
        .order("fecha", desc=True).execute().data or []
    if not alertas:
        return []
    proveedor_ids = list({a["proveedor_id"] for a in alertas if a.get("proveedor_id")})
    proveedores = (db.table("proveedores").select("id,nombre").in_("id", proveedor_ids).execute().data or []) \
        if proveedor_ids else []
    nombre_por_proveedor = {p["id"]: p["nombre"] for p in proveedores}
    return [
        AlertaPrecioOut(
            id=a["id"], dte_id=a.get("dte_id"), invoice_name=a.get("invoice_name"),
            ingrediente_key=a["ingrediente_key"], nombre=a["ingrediente_key"].split("||")[0],
            proveedor_id=a.get("proveedor_id"), proveedor_nombre=nombre_por_proveedor.get(a.get("proveedor_id")),
            precio_real=a["precio_real"], precio_negociado=a["precio_negociado"],
            tipo=a.get("tipo", "sobreprecio"), fecha=a["fecha"], resuelta=a["resuelta"],
        )
        for a in alertas
    ]


@router.post("/alertas-precio/{alerta_id}/resolver", status_code=status.HTTP_204_NO_CONTENT)
def resolver_alerta_precio(alerta_id: str, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    db = get_db()
    db.table("alertas_precio_factura").update({"resuelta": True}).eq("id", alerta_id).execute()


@router.get("/ahorro-mensual", response_model=AhorroMensualOut)
def ahorro_mensual(anio: int, mes: int, claims: dict = Depends(get_current_claims)):
    """Cuanta plata se dejo de ahorrar este mes por no haber comprado
    siempre al mejor precio pactado disponible para cada insumo -- cubre
    tanto pagarle de mas a un proveedor con acuerdo (rompio el precio)
    como comprarle a un proveedor sin acuerdo (o mas caro) pudiendo haber
    ido a uno pactado mas barato para el mismo insumo. Se calcula sobre
    historial_precios_compra, que solo tiene datos desde que existe esta
    funcionalidad -- no hay como reconstruir el pasado."""
    _require_lectura(claims)
    db = get_db()

    negociados = db.table("odoo_mapping").select("ingrediente_key,precio_negociado") \
        .not_.is_("precio_negociado", "null").execute().data or []
    mejor_precio_por_key: dict[str, float] = {}
    for n in negociados:
        k, p = n["ingrediente_key"], n["precio_negociado"]
        if k not in mejor_precio_por_key or p < mejor_precio_por_key[k]:
            mejor_precio_por_key[k] = p
    if not mejor_precio_por_key:
        return AhorroMensualOut(anio=anio, mes=mes, total_perdido=0, items=[])

    # Limites explicitos en UTC -- historial_precios_compra.fecha se guarda
    # siempre con offset UTC (datetime.now(timezone.utc).isoformat()), asi
    # que comparar contra fechas sin offset podia excluir/incluir mal una
    # compra muy cerca de medianoche en el borde del mes segun el huso
    # horario de sesion de Postgres.
    ultimo_dia = monthrange(anio, mes)[1]
    desde = f"{date(anio, mes, 1).isoformat()}T00:00:00+00:00"
    hasta = f"{date(anio, mes, ultimo_dia).isoformat()}T23:59:59.999999+00:00"
    compras = db.table("historial_precios_compra").select("*") \
        .in_("ingrediente_key", list(mejor_precio_por_key.keys())) \
        .gte("fecha", desde).lte("fecha", hasta).execute().data or []
    if not compras:
        return AhorroMensualOut(anio=anio, mes=mes, total_perdido=0, items=[])

    proveedor_ids = list({c["proveedor_id"] for c in compras if c.get("proveedor_id")})
    proveedores = (db.table("proveedores").select("id,nombre").in_("id", proveedor_ids).execute().data or []) \
        if proveedor_ids else []
    nombre_por_proveedor = {p["id"]: p["nombre"] for p in proveedores}

    items: list[ItemAhorroOut] = []
    total = 0.0
    for c in compras:
        mejor_precio = mejor_precio_por_key[c["ingrediente_key"]]
        if c["precio"] <= mejor_precio:
            continue
        perdida = (c["precio"] - mejor_precio) * c["cantidad"]
        total += perdida
        items.append(ItemAhorroOut(
            ingrediente_key=c["ingrediente_key"], nombre=c["ingrediente_key"].split("||")[0],
            proveedor_nombre=nombre_por_proveedor.get(c.get("proveedor_id"), "Proveedor desconocido"),
            precio_pagado=c["precio"], mejor_precio_pactado=mejor_precio, cantidad=c["cantidad"],
            perdida=round(perdida, 2), fecha=c["fecha"], invoice_name=c.get("invoice_name"),
        ))
    items.sort(key=lambda it: it.perdida, reverse=True)

    return AhorroMensualOut(anio=anio, mes=mes, total_perdido=round(total, 2), items=items)
