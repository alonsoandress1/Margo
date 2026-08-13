"""Ingreso de facturas de proveedor a partir de los DTE que Odoo recibe
automaticamente del SII -- flujo NUEVO, separado del historico facturas.py
(ese lee facturas YA POSTEADAS en Odoo para sumar a Bodega; este lee los
DTE crudos que TODAVIA no se convirtieron a factura borrador en Odoo).

Estructura real de Odoo (confirmada leyendo el Odoo real, no documentacion
generica -- este modelo es de una app de terceros para Chile, no viene en
la doc estandar de Odoo):
  l10n_cl.supplier.xml            -- cabecera del DTE. invoice_id=False
                                      mientras no se creo la factura borrador.
    -> line_ids -> l10n_cl.supplier.xml.line   (item_name, qty, product_id,
                                                 code_ids)
         -> code_ids -> l10n_cl.supplier.xml.item.code  (code_type,
                                                          code_value -- el
                                                          codigo interno del
                                                          PROVEEDOR)
  Boton "Crear Factura Proveedor" = metodo create_invoice() en la cabecera.

No creamos productos nuevos en Odoo, nunca -- solo buscamos productos ya
existentes y escribimos su product_id en la linea del DTE. La conexion
codigo-de-proveedor -> product_id se aprende una vez (confirmada por un
admin) y se reusa siempre despues -- tabla facturas_producto_mapa."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from postgrest.exceptions import APIError

from ..db import get_db
from ..deps import get_current_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402

from ..schemas import (ColaFacturaOut, CompararOut, CompararLineaOut, DteDetalleOut, DteLineaOut,
                       DteMatchLineaIn, DteOut, DteProductoOut, FactorConversionIn, FactorConversionOut,
                       ImpuestoOut, ProductoImpuestosIn, ProveedorOcultarIn, ProveedorOcultoOut)

router = APIRouter(prefix="/facturas-dte", tags=["facturas-dte"])

TOLERANCIA_MONTOS = 9  # pesos -- diferencia maxima aceptada entre el DTE y la factura creada en Odoo


# Doña Sofía es proveedor de Doña Delfina (no un local aparte) y, a diferencia
# de cualquier otro proveedor, casi siempre ya tiene una Orden de Compra real
# creada en Odoo ANTES de que llegue su DTE -- por un proceso de compras
# existente, ajeno a este sistema (confirmado revisando Odoo real: facturas
# ya creadas con invoice_origin apuntando a una OC, sin que el DTE
# correspondiente jamas quedara marcado como procesado). Para este proveedor
# NO se crea una OC nueva -- se busca la que ya existe y se reusa.
RUT_DONA_SOFIA = "77500046-5"
VENTANA_DIAS_OC_SOFIA = 5  # la OC real puede tener hasta esta cantidad de dias de anticipacion sobre el DTE
UMBRAL_MATCH_CANTIDAD_SOFIA = 0.9  # al menos 90% de la cantidad del DTE debe calzar con la OC candidata

# Unicos dos productos de Doña Sofía con peso variable real (confirmado por
# el usuario) -- para estos SI se actualiza la cantidad de la OC a la
# declarada en el DTE (ademas del precio), porque lo pedido y lo despachado
# legitimamente no calzan exacto (se pesa al despachar). Para cualquier otro
# producto, la cantidad de la OC nunca se toca -- si no calza, es un
# desajuste real que debe revisarse a mano, no adivinarse.
PRODUCTOS_PESO_VARIABLE_SOFIA = {
    12041,  # Carpaccio de Res Kg (CAR0400)
    16826,  # Filete para Churrascos (REC529)
}


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede gestionar el ingreso de facturas")


def _odoo() -> OdooClient:
    """Cuenta de servicio dedicada -- guardada en Render, nunca en el chat
    ni en el navegador. Ver _configurar_cuenta_servicio_facturas.py."""
    try:
        cliente = OdooClient(os.environ["ODOO_URL"], os.environ["ODOO_DB"],
                              os.environ["ODOO_FACTURAS_USER"], os.environ["ODOO_FACTURAS_PASSWORD"])
    except KeyError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
    ok, msg = cliente.connect()
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo conectar a Odoo: {msg}")
    return cliente


def _mejor_codigo(codigos: list[dict], item_name: str | None = None) -> tuple[str | None, str | None]:
    """De los codigos de una linea (puede traer mas de uno), el primero que
    tenga code_value. Algunos proveedores no mandan NINGUN codigo interno en
    el DTE (ej. Distribuidora Frio Express -- code_ids viene vacio en todas
    sus lineas) -- en ese caso se usa el texto exacto del item como codigo
    de respaldo (mismo patron que el script de extraccion, _extraer_productos_dte_proveedor.py).
    Sin esto, un producto de estos proveedores nunca queda "aprendido": el
    admin confirma el match una y otra vez, pero facturas_producto_mapa
    nunca llega a guardar nada porque confirmar_match exige codigo_tipo +
    codigo_valor no vacios."""
    for c in codigos:
        if c.get("code_value"):
            return c["code_type"], c["code_value"]
    texto = (item_name or "").strip()
    return ("TEXTO", texto) if texto else (None, None)


@router.get("", response_model=list[DteOut])
def listar_pendientes(desde: str, hasta: str, claims: dict = Depends(get_current_claims)):
    """DTE recibidos del SII en el rango de fechas que TODAVIA no tienen
    una factura borrador creada en Odoo (invoice_id vacio). No incluye
    proveedores marcados como ocultos (facturas_proveedor_oculto)."""
    _require_admin(claims)
    db = get_db()
    ocultos = {f["proveedor_rut"] for f in (db.table("facturas_proveedor_oculto").select("proveedor_rut").execute().data or [])}
    cliente = _odoo()
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read',
        [[['date', '>=', desde], ['date', '<=', hasta], ['invoice_id', '=', False]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date', 'amount_total'],
         'order': 'issuer_name, date'})
    return [
        DteOut(id=d['id'], proveedor_rut=d.get('issuer_rut') or '', proveedor_nombre=d.get('issuer_name') or '',
               folio=d.get('l10n_latam_document_number') or '', fecha=d.get('date'),
               monto_total=_monto(d.get('amount_total')), tiene_factura=False)
        for d in docs
        if (d.get('issuer_rut') or '') not in ocultos
    ]


@router.get("/proveedores/ocultos", response_model=list[ProveedorOcultoOut])
def listar_proveedores_ocultos(claims: dict = Depends(get_current_claims)):
    """Proveedores actualmente ocultos de la lista de pendientes."""
    _require_admin(claims)
    db = get_db()
    filas = db.table("facturas_proveedor_oculto").select("proveedor_rut, proveedor_nombre") \
        .order("proveedor_nombre").execute().data or []
    return [ProveedorOcultoOut(proveedor_rut=f["proveedor_rut"], proveedor_nombre=f["proveedor_nombre"]) for f in filas]


@router.post("/proveedores/ocultar", status_code=status.HTTP_204_NO_CONTENT)
def ocultar_proveedor(body: ProveedorOcultarIn, claims: dict = Depends(get_current_claims)):
    """Oculta todas las facturas pendientes de este proveedor -- no toca
    nada en Odoo, solo deja de listarlas. Reversible."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_proveedor_oculto").upsert({
        "proveedor_rut": body.proveedor_rut, "proveedor_nombre": body.proveedor_nombre,
        "ocultado_por": claims["sub"],
    }).execute()


@router.delete("/proveedores/ocultos/{proveedor_rut}", status_code=status.HTTP_204_NO_CONTENT)
def mostrar_proveedor(proveedor_rut: str, claims: dict = Depends(get_current_claims)):
    """Vuelve a mostrar un proveedor previamente ocultado."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_proveedor_oculto").delete().eq("proveedor_rut", proveedor_rut).execute()


@router.get("/productos/buscar", response_model=list[DteProductoOut])
def buscar_producto(q: str, claims: dict = Depends(get_current_claims)):
    """Busca productos YA EXISTENTES en Odoo por nombre o codigo interno --
    solo lectura, nunca crea nada. Para cuando una linea no tiene sugerencia
    y hay que buscar el producto correcto a mano."""
    _require_admin(claims)
    cliente = _odoo()
    productos = cliente._call('product.product', 'search_read',
        [['|', ['name', 'ilike', q], ['default_code', 'ilike', q]]],
        {'fields': ['id', 'name', 'default_code', 'uom_id'], 'limit': 30})
    return [
        DteProductoOut(id=p['id'], name=p['name'], default_code=p.get('default_code') or None,
                        uom=p['uom_id'][1] if p.get('uom_id') else None)
        for p in productos
    ]


@router.get("/impuestos/buscar", response_model=list[ImpuestoOut])
def buscar_impuesto(q: str = '', claims: dict = Depends(get_current_claims)):
    """Busca impuestos de compra YA EXISTENTES en Odoo por nombre (ej. "IVA
    19% Compra", "Impuesto a la Carne 5%") -- solo lectura. Se buscan en la
    empresa por defecto de la cuenta de servicio; al crear la factura se
    resuelve el impuesto real de CADA empresa por el mismo nombre (los
    impuestos son por empresa en Odoo, ver _ejecutar_creacion)."""
    _require_admin(claims)
    cliente = _odoo()
    dominio = [['type_tax_use', '=', 'purchase'], ['active', '=', True]]
    if q:
        dominio.append(['name', 'ilike', q])
    impuestos = cliente._call('account.tax', 'search_read', [dominio],
        {'fields': ['id', 'name', 'amount'], 'limit': 30, 'order': 'name'})
    return [ImpuestoOut(id=i['id'], name=i['name'], amount=i.get('amount') or 0) for i in impuestos]


@router.get("/productos/{producto_id}/impuestos", response_model=list[str])
def listar_impuestos_producto(producto_id: int, claims: dict = Depends(get_current_claims)):
    """Impuestos que aplican hoy a este producto (hasta 3): si hay un override
    guardado, ese; si no, el impuesto de compra que el producto YA TIENE por
    defecto en Odoo (supplier_taxes_id) -- para que el selector salga
    alineado con lo que se factura hoy y no se pierda (ej. el IVA 19%) al
    marcar solo un impuesto especial nuevo."""
    _require_admin(claims)
    db = get_db()
    filas = db.table("facturas_producto_impuesto").select("impuesto_nombre").eq("odoo_product_id", producto_id).execute().data or []
    if filas:
        return [f["impuesto_nombre"] for f in filas]
    cliente = _odoo()
    prod = cliente._call('product.product', 'read', [[producto_id]], {'fields': ['supplier_taxes_id']})
    tax_ids = prod[0]['supplier_taxes_id'] if prod else []
    if not tax_ids:
        return []
    taxes = cliente._call('account.tax', 'read', [tax_ids], {'fields': ['name']})
    return [t['name'] for t in taxes]


@router.put("/productos/{producto_id}/impuestos", status_code=status.HTTP_204_NO_CONTENT)
def fijar_impuestos_producto(producto_id: int, body: ProductoImpuestosIn, claims: dict = Depends(get_current_claims)):
    """Reemplaza los impuestos guardados de este producto por la lista
    dada (maximo 3) -- lista vacia = volver a usar el impuesto por defecto
    del producto en Odoo."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_producto_impuesto").delete().eq("odoo_product_id", producto_id).execute()
    if body.impuesto_nombres:
        db.table("facturas_producto_impuesto").insert([
            {"odoo_product_id": producto_id, "odoo_product_name": body.odoo_product_name,
             "impuesto_nombre": nombre, "actualizado_por": claims["sub"]}
            for nombre in body.impuesto_nombres
        ]).execute()


@router.get("/mapeo/factor", response_model=FactorConversionOut)
def obtener_factor_conversion(proveedor_rut: str, codigo_tipo: str, codigo_valor: str,
                               claims: dict = Depends(get_current_claims)):
    """Factor de conversion guardado para este mapeo (proveedor + codigo de
    producto) -- 1 = sin conversion (el caso normal, el qty del DTE ya es la
    cantidad real)."""
    _require_admin(claims)
    db = get_db()
    fila = db.table("facturas_producto_mapa").select("factor_conversion") \
        .eq("proveedor_rut", proveedor_rut).eq("codigo_tipo", codigo_tipo).eq("codigo_valor", codigo_valor).execute().data
    return FactorConversionOut(factor_conversion=(fila[0]["factor_conversion"] if fila else 1) or 1)


@router.put("/mapeo/factor", status_code=status.HTTP_204_NO_CONTENT)
def fijar_factor_conversion(body: FactorConversionIn, claims: dict = Depends(get_current_claims)):
    """Guarda el factor de conversion para este mapeo -- ej. si el proveedor
    declara "1" pero en realidad vienen 10 unidades reales por cada una
    declarada (un bulto), factor_conversion=10. Se aplica multiplicando la
    cantidad y dividiendo el precio unitario por el mismo factor (el total
    de la linea no cambia). Requiere que el producto ya se haya confirmado
    al menos una vez para este proveedor+codigo (la fila ya debe existir)."""
    _require_admin(claims)
    db = get_db()
    res = db.table("facturas_producto_mapa").update({"factor_conversion": body.factor_conversion}) \
        .eq("proveedor_rut", body.proveedor_rut).eq("codigo_tipo", body.codigo_tipo).eq("codigo_valor", body.codigo_valor).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
            "No hay un producto confirmado todavía para este código -- confírmalo primero")


@router.get("/{dte_id}/comparar", response_model=CompararOut)
def comparar(dte_id: int, claims: dict = Depends(get_current_claims)):
    """Compara linea por linea lo que declaro el DTE del proveedor contra lo
    que realmente quedo creado en la factura de Odoo -- lee la factura REAL
    (no una simulacion), asi que solo funciona para DTE que ya tienen
    factura creada."""
    _require_admin(claims)
    cliente = _odoo()
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'invoice_id', 'amount_untaxed', 'iva', 'amount_total']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    if not doc.get('invoice_id'):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            "Esta factura todavía no se ha creado en Odoo -- créala primero para poder comparar")
    move_id = doc['invoice_id'][0]

    lineas_dte = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['item_name', 'qty', 'item_price', 'product_id']})

    move = cliente._call('account.move', 'read', [[move_id]],
        {'fields': ['name', 'amount_untaxed', 'amount_tax', 'amount_total']})[0]
    move_lineas = cliente._call('account.move.line', 'search_read',
        [[['move_id', '=', move_id], ['display_type', '=', 'product']]],
        {'fields': ['product_id', 'quantity', 'price_unit', 'tax_ids']})

    tax_ids = list({t for ml in move_lineas for t in ml.get('tax_ids', [])})
    tax_nombres: dict[int, str] = {}
    if tax_ids:
        taxes = cliente._call('account.tax', 'read', [tax_ids], {'fields': ['name']})
        tax_nombres = {t['id']: t['name'] for t in taxes}

    # Empareja por product_id -- el flujo de creacion arma como maximo una
    # linea de OC/factura por producto (ver _ejecutar_creacion), asi que
    # alcanza para emparejar de vuelta con las lineas del DTE.
    odoo_por_producto: dict[int, dict] = {}
    for ml in move_lineas:
        if ml.get('product_id'):
            odoo_por_producto[ml['product_id'][0]] = ml

    lineas_out = []
    for l in lineas_dte:
        pid = l['product_id'][0] if l.get('product_id') else None
        ml = odoo_por_producto.get(pid) if pid else None
        lineas_out.append(CompararLineaOut(
            item_name=l.get('item_name') or '',
            qty_dte=l.get('qty') or 0,
            precio_dte=float(l.get('item_price') or 0),
            subtotal_dte=round((l.get('qty') or 0) * float(l.get('item_price') or 0), 2),
            producto_nombre=(l['product_id'][1] if l.get('product_id') else None),
            qty_odoo=ml['quantity'] if ml else None,
            precio_odoo=ml['price_unit'] if ml else None,
            subtotal_odoo=round(ml['quantity'] * ml['price_unit'], 2) if ml else None,
            impuestos_odoo=[tax_nombres.get(t, '?') for t in (ml.get('tax_ids') or [])] if ml else [],
        ))

    return CompararOut(
        invoice_name=move['name'],
        neto_dte=_monto(doc.get('amount_untaxed')), iva_dte=_monto(doc.get('iva')), total_dte=_monto(doc.get('amount_total')),
        neto_odoo=move.get('amount_untaxed') or 0, iva_odoo=move.get('amount_tax') or 0, total_odoo=move.get('amount_total') or 0,
        lineas=lineas_out,
    )


@router.get("/{dte_id}", response_model=DteDetalleOut)
def detalle(dte_id: int, claims: dict = Depends(get_current_claims)):
    """Detalle de un DTE con sus lineas. Cuando el codigo de una linea ya
    tiene un mapeo aprendido (facturas_producto_mapa), se AUTOCONFIRMA
    solo -- se escribe el product_id directo en Odoo, sin pedir el clic
    manual de "Confirmar" (ya se sabe que es el producto correcto, se
    aprendio la primera vez que alguien lo confirmo a mano). Si la
    escritura falla por lo que sea, no se cae toda la pantalla -- la
    linea vuelve a quedar como sugerencia pendiente del clic manual
    (fallback, mismo comportamiento de antes)."""
    _require_admin(claims)
    cliente = _odoo()
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date', 'invoice_id']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]

    lineas_raw = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'item_name', 'qty', 'product_id', 'code_ids']})

    code_ids = [c for l in lineas_raw for c in l.get('code_ids', [])]
    codigos_por_id = {}
    if code_ids:
        codigos = cliente._call('l10n_cl.supplier.xml.item.code', 'search_read',
            [[['id', 'in', code_ids]]], {'fields': ['code_type', 'code_value']})
        codigos_por_id = {c['id']: c for c in codigos}

    db = get_db()
    mapeos = db.table("facturas_producto_mapa").select("*").eq("proveedor_rut", doc.get("issuer_rut") or "").execute().data or []
    mapa = {(m["codigo_tipo"], m["codigo_valor"]): m for m in mapeos}

    lineas: list[DteLineaOut] = []
    for l in lineas_raw:
        codigos = [codigos_por_id[c] for c in l.get('code_ids', []) if c in codigos_por_id]
        codigo_tipo, codigo_valor = _mejor_codigo(codigos, l.get('item_name'))
        product_id = l['product_id'][0] if l.get('product_id') else None
        product_name = l['product_id'][1] if l.get('product_id') else None
        sugerido = False
        if not product_id and codigo_tipo and (codigo_tipo, codigo_valor) in mapa:
            m = mapa[(codigo_tipo, codigo_valor)]
            product_id, product_name = m["odoo_product_id"], m["odoo_product_name"]
            try:
                cliente._call('l10n_cl.supplier.xml.line', 'write', [[l['id']], {'product_id': product_id}])
            except Exception:
                sugerido = True  # no se pudo autoconfirmar -- que quede el clic manual como respaldo
        lineas.append(DteLineaOut(
            id=l['id'], item_name=l.get('item_name') or '', qty=l.get('qty') or 0,
            codigo_tipo=codigo_tipo, codigo_valor=codigo_valor,
            product_id=product_id, product_name=product_name, sugerido=sugerido,
        ))

    return DteDetalleOut(
        id=doc['id'], proveedor_rut=doc.get('issuer_rut') or '', proveedor_nombre=doc.get('issuer_name') or '',
        folio=doc.get('l10n_latam_document_number') or '', fecha=doc.get('date'),
        tiene_factura=bool(doc.get('invoice_id')), lineas=lineas,
    )


@router.post("/lineas/match", status_code=status.HTTP_204_NO_CONTENT)
def confirmar_match(body: DteMatchLineaIn, claims: dict = Depends(get_current_claims)):
    """Un admin confirma que una linea del DTE corresponde a un producto ya
    existente en Odoo: escribe el product_id en la linea (unico cambio que
    se hace en Odoo aca) y guarda el mapeo para que la proxima factura del
    mismo proveedor con el mismo codigo se sugiera sola."""
    _require_admin(claims)
    cliente = _odoo()
    cliente._call('l10n_cl.supplier.xml.line', 'write', [[body.line_id], {'product_id': body.odoo_product_id}])

    if body.codigo_tipo and body.codigo_valor:
        db = get_db()
        db.table("facturas_producto_mapa").upsert({
            "proveedor_rut": body.proveedor_rut, "proveedor_nombre": body.proveedor_nombre,
            "codigo_tipo": body.codigo_tipo, "codigo_valor": body.codigo_valor,
            "odoo_product_id": body.odoo_product_id, "odoo_product_name": body.odoo_product_name,
            "confirmado_por": claims["sub"],
        }, on_conflict="proveedor_rut,codigo_tipo,codigo_valor").execute()


def _monto(valor) -> float:
    """Los montos del DTE vienen como texto ("293363") y los de Odoo
    (purchase.order/account.move, mismos nombres de campo en ambos) como
    numero -- normaliza ambos a float para poder compararlos."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _verificar_montos(doc: dict, odoo_datos: dict) -> list[str]:
    """Compara Neto/IVA/Total del DTE contra los mismos montos ya calculados
    en Odoo (la OC en borrador, antes de confirmar nada) -- deben coincidir
    o tener maximo TOLERANCIA_MONTOS pesos de diferencia (redondeos).
    Devuelve la lista de desajustes encontrados (vacia si todo calza)."""
    comparaciones = (
        ("Neto", doc.get('amount_untaxed'), odoo_datos.get('amount_untaxed')),
        ("IVA", doc.get('iva'), odoo_datos.get('amount_tax')),
        ("Total", doc.get('amount_total'), odoo_datos.get('amount_total')),
    )
    desajustes = []
    for campo, valor_dte, valor_odoo in comparaciones:
        valor_dte, valor_odoo = _monto(valor_dte), _monto(valor_odoo)
        diferencia = abs(valor_dte - valor_odoo)
        if diferencia > TOLERANCIA_MONTOS:
            desajustes.append(f"{campo}: DTE ${valor_dte:,.0f} vs Odoo ${valor_odoo:,.0f} (diferencia ${diferencia:,.0f})")
    return desajustes


def _buscar_oc_sofia(cliente: OdooClient, partner_id: int, company_id: int, fecha_dte: str,
                      qty_dte_por_producto: dict[int, float]) -> tuple[int | None, str | None, str | None]:
    """Busca la Orden de Compra de Doña Sofía que ya existe en Odoo y
    corresponde a este DTE -- NO se crea una OC nueva para este proveedor
    (ver comentario junto a RUT_DONA_SOFIA). Matchea por CANTIDADES (no por
    precio, que es justamente el dato que puede estar desactualizado en la
    OC): al menos UMBRAL_MATCH_CANTIDAD_SOFIA de la cantidad total del DTE
    debe encontrarse en las lineas de la OC candidata, para el mismo
    producto. Si hay 0 candidatas o 2+ empatadas por encima del umbral, no
    se elige ninguna -- mejor fallar que adivinar mal.

    Devuelve (po_id, po_name, motivo_de_error). po_id es None si no se pudo
    determinar una OC unica -- en ese caso motivo_de_error explica por que."""
    desde = (date.fromisoformat(fecha_dte) - timedelta(days=VENTANA_DIAS_OC_SOFIA)).isoformat()
    candidatas = cliente._call('purchase.order', 'search_read',
        [[['partner_id', '=', partner_id], ['company_id', '=', company_id],
          ['state', '=', 'purchase'], ['invoice_status', '=', 'no'],
          ['date_order', '>=', f'{desde} 00:00:00'], ['date_order', '<=', f'{fecha_dte} 23:59:59']]],
        {'fields': ['id', 'name']})
    if not candidatas:
        return None, None, (
            f"no encontré ninguna Orden de Compra de Doña Sofía sin facturar en los últimos "
            f"{VENTANA_DIAS_OC_SOFIA} días")

    total_qty_dte = sum(qty_dte_por_producto.values())
    calzan = []
    for c in candidatas:
        lineas_oc = cliente._call('purchase.order.line', 'search_read',
            [[['order_id', '=', c['id']]]], {'fields': ['product_id', 'product_qty']})
        qty_oc_por_producto: dict[int, float] = {}
        for l in lineas_oc:
            if l.get('product_id'):
                pid = l['product_id'][0]
                qty_oc_por_producto[pid] = qty_oc_por_producto.get(pid, 0) + (l.get('product_qty') or 0)
        qty_calzada = sum(min(qty_dte, qty_oc_por_producto.get(pid, 0)) for pid, qty_dte in qty_dte_por_producto.items())
        score = (qty_calzada / total_qty_dte) if total_qty_dte else 0
        if score >= UMBRAL_MATCH_CANTIDAD_SOFIA:
            calzan.append((c, score))

    if not calzan:
        return None, None, (
            f"ninguna de las {len(candidatas)} Orden(es) de Compra sin facturar de Doña Sofía en los "
            f"últimos {VENTANA_DIAS_OC_SOFIA} días calza al menos {int(UMBRAL_MATCH_CANTIDAD_SOFIA * 100)}% en cantidades")
    if len(calzan) > 1:
        nombres = ', '.join(c['name'] for c, _ in calzan)
        return None, None, (
            f"{len(calzan)} Órdenes de Compra de Doña Sofía calzan al menos "
            f"{int(UMBRAL_MATCH_CANTIDAD_SOFIA * 100)}% en cantidades ({nombres}) -- no se puede elegir automáticamente")

    oc_elegida, _ = calzan[0]
    return oc_elegida['id'], oc_elegida['name'], None


def _ejecutar_creacion(cliente: OdooClient, dte_id: int, doc: dict, lineas: list[dict]) -> tuple[int, str]:
    """El trabajo pesado de verdad -- 6 llamadas seguidas a Odoo, por eso se
    corre en segundo plano (ver crear_factura) en vez de bloquear al usuario.

    El boton 'Crear Factura Proveedor' de Odoo (metodo create_invoice) esta
    roto en esta instancia -- probado directo en la UI de Odoo, mismo error:
    KeyError: 'ir.property' en el modulo de terceros od_dte (usa un modelo
    que ya no existe en esta version de Odoo).

    En vez de armar la factura (account.move) a mano, replicamos el flujo
    real que usa el negocio para TODOS los proveedores (confirmado revisando
    el historico completo en Odoo: ~1000 facturas, todas con una OC detras):
    1) crear la Orden de Compra (mismo mecanismo que la automatizacion de
       compras -- OC en Draft con product_id/cantidad/precio del DTE),
    1.5) verificar que Neto/IVA/Total de la OC en borrador calcen con lo
       declarado en el DTE (maximo TOLERANCIA_MONTOS pesos de diferencia) --
       si no calzan, se borra la OC (todavia en borrador, se puede limpio) y
       no se sigue: no se crea ninguna factura con montos que no coinciden,
    2) confirmarla (button_confirm -- genera la recepcion de mercaderia),
    3) marcar la mercaderia como recibida (button_validate, con la fecha del
       DTE), 4) generar la factura DESDE la OC (action_create_invoice --
    metodo nativo y estandar de Odoo, no el boton roto). Asi Odoo completa
    solo el diario, la cuenta contable y el impuesto de cada linea (igual
    que en las facturas reales existentes) -- solo hay que fijar despues la
    fecha y el folio del DTE, que Odoo no puede saber por si solo.

    EXCEPCION -- Doña Sofía (RUT_DONA_SOFIA): no se crea una OC nueva, se
    busca y reusa la que ya existe (ver _buscar_oc_sofia) y solo se le
    actualiza el precio de cada linea al del DTE real."""
    company_id = doc['company_id'][0]
    partners = cliente._call('res.partner', 'search_read', [[['vat', '=', doc['issuer_rut']]]],
        {'fields': ['id', 'supplier_rank']})
    if not partners:
        raise RuntimeError(f"No encontré el proveedor con RUT {doc['issuer_rut']} en Odoo")
    if len(partners) == 1:
        partner_id = partners[0]['id']
    else:
        # Es comun que el mismo RUT quede repetido en varios res.partner --
        # confirmado con datos reales en CCU (la empresa real + 2 contactos
        # personales con el mismo vat copiado, supplier_rank=0) y en
        # Comercializadora Global Products (duplicado de una razon social
        # vieja). El registro correcto es el que realmente se ha usado como
        # proveedor -- supplier_rank mucho mas alto que el resto. Si no hay
        # un ganador claro, mejor fallar que adivinar mal.
        ranking = sorted(partners, key=lambda p: p.get('supplier_rank') or 0, reverse=True)
        if (ranking[0].get('supplier_rank') or 0) == (ranking[1].get('supplier_rank') or 0):
            raise RuntimeError(
                f"Encontré {len(partners)} proveedores con RUT {doc['issuer_rut']} en Odoo, "
                f"sin uno claramente mas usado como proveedor -- hay que resolverlo a mano en Odoo"
            )
        partner_id = ranking[0]['id']

    # Verificar que no exista YA una factura real para este mismo documento
    # (mismo proveedor + mismo folio), aunque el DTE nunca haya quedado
    # vinculado a ella -- esto puede pasar si alguien crea la factura por
    # otro camino (a mano en Odoo, u otro proceso de compras) sin pasar por
    # esta pantalla. Encontrado con un caso real: una factura de Alimentos y
    # Frutos S.A. ya existia (creada por otro proceso, nunca vinculada al
    # DTE) y este sistema creo una segunda factura duplicada para el mismo
    # folio antes de tener esta validacion. Aplica a CUALQUIER proveedor,
    # no solo a Doña Sofía.
    folio = str(doc.get('l10n_latam_document_number') or '').strip()
    if folio:
        ya_facturada = cliente._call('account.move', 'search_read',
            [[['partner_id', '=', partner_id], ['move_type', '=', 'in_invoice'],
              ['l10n_latam_document_number', '=', folio], ['state', '!=', 'cancel']]],
            {'fields': ['id', 'name', 'amount_total']})
        if ya_facturada:
            nombres = ', '.join(m['name'] for m in ya_facturada)
            raise RuntimeError(
                f"Ya existe una factura en Odoo para este folio ({nombres}) aunque el DTE no estaba vinculado "
                f"a ella -- no se creó nada nuevo. Si es la factura correcta, hay que vincularla a mano; "
                f"si no, revisar con contabilidad"
            )

    # Condicion de pago -- la que el proveedor ya tiene configurada por
    # defecto en Odoo. Al crear la OC por API (no por el formulario) Odoo NO
    # la autocompleta sola (ese autocompletado es un onchange, que solo se
    # dispara desde la UI) -- confirmado en un caso real (Bidfood, "30 Days"
    # configurado en el proveedor, la OC/factura creada por este sistema
    # quedaba sin ninguna condicion). Se fija a mano para que quede igual
    # que si alguien la hubiera creado a mano en Odoo.
    partner_datos = cliente._call('res.partner', 'read', [[partner_id]],
        {'fields': ['property_supplier_payment_term_id']})[0]
    payment_term_id = (partner_datos['property_supplier_payment_term_id'][0]
                        if partner_datos.get('property_supplier_payment_term_id') else False)

    product_ids = list({l['product_id'][0] for l in lineas})
    productos = cliente._call('product.product', 'read', [product_ids], {'fields': ['uom_id', 'display_name']})
    info_por_producto = {p['id']: p for p in productos}

    # Impuestos guardados por producto (tabla facturas_producto_impuesto,
    # hasta 3 por producto) -- si un producto no tiene fila aca, Odoo usa el
    # impuesto que ya tenga configurado por defecto (el caso normal). Los
    # impuestos son por EMPRESA en Odoo, asi que se guarda el NOMBRE y se
    # resuelve al id real de la empresa de este DTE recien aca.
    db = get_db()
    filas_impuestos = db.table("facturas_producto_impuesto").select("odoo_product_id,impuesto_nombre") \
        .in_("odoo_product_id", product_ids).execute().data or []
    nombres_por_producto: dict[int, list[str]] = {}
    for f in filas_impuestos:
        nombres_por_producto.setdefault(f["odoo_product_id"], []).append(f["impuesto_nombre"])

    tax_id_por_nombre: dict[str, int] = {}
    if nombres_por_producto:
        nombres_unicos = list({n for ns in nombres_por_producto.values() for n in ns})
        impuestos_odoo = cliente._call('account.tax', 'search_read',
            [[['name', 'in', nombres_unicos], ['company_id', '=', company_id], ['type_tax_use', '=', 'purchase']]],
            {'fields': ['id', 'name']})
        tax_id_por_nombre = {i['name']: i['id'] for i in impuestos_odoo}
        faltantes = [n for n in nombres_unicos if n not in tax_id_por_nombre]
        if faltantes:
            raise RuntimeError(
                f"No encontré el impuesto '{', '.join(faltantes)}' en la empresa de este DTE -- "
                f"revisar el nombre o configurarlo en Odoo para esa empresa"
            )

    # Factor de conversion por mapeo (proveedor + codigo) -- algunos
    # proveedores declaran una cantidad que en realidad es un bulto con mas
    # unidades reales (ej. el DTE dice "1 azucar" pero son 10 kg reales). Se
    # resuelve el codigo real de cada linea (mismo criterio que detalle()) y
    # se busca el factor guardado en facturas_producto_mapa -- default 1 si
    # no hay nada guardado (el caso normal, el qty del DTE ya es el real).
    code_ids = [c for l in lineas for c in l.get('code_ids', [])]
    codigos_por_id = {}
    if code_ids:
        codigos = cliente._call('l10n_cl.supplier.xml.item.code', 'search_read',
            [[['id', 'in', code_ids]]], {'fields': ['code_type', 'code_value']})
        codigos_por_id = {c['id']: c for c in codigos}

    mapeos_proveedor = db.table("facturas_producto_mapa").select("codigo_tipo,codigo_valor,factor_conversion") \
        .eq("proveedor_rut", doc['issuer_rut']).execute().data or []
    factor_por_codigo = {(m['codigo_tipo'], m['codigo_valor']): (m.get('factor_conversion') or 1) for m in mapeos_proveedor}

    def _factor_de_linea(l: dict) -> float:
        codigos_linea = [codigos_por_id[c] for c in l.get('code_ids', []) if c in codigos_por_id]
        codigo_tipo, codigo_valor = _mejor_codigo(codigos_linea, l.get('item_name'))
        return factor_por_codigo.get((codigo_tipo, codigo_valor), 1) or 1

    # Algunos proveedores (ej. Comercializadora Global Products) aplican un
    # descuento que solo se ve en el Neto declarado en la cabecera del DTE
    # -- el item_price de cada linea sigue siendo el precio SIN descuento,
    # asi que sumar item_price*qty da un Neto mas alto que el real y la
    # factura nunca calza. Se corrige escalando todas las lineas por un
    # mismo factor para que la suma de line coincida con el Neto declarado
    # -- si no hay descuento el factor es 1 y no cambia nada.
    neto_dte = _monto(doc.get('amount_untaxed'))
    neto_sin_descuento = sum((l.get('qty') or 0) * float(l.get('item_price') or 0) for l in lineas)
    factor_descuento = (neto_dte / neto_sin_descuento) if neto_dte and neto_sin_descuento else 1.0

    fecha_dte = f"{doc['date']} 12:00:00"
    order_lines = []
    for l in lineas:
        pid = l['product_id'][0]
        prod = info_por_producto[pid]
        factor_conversion = _factor_de_linea(l)
        precio_real = (float(l.get('item_price') or 0) / factor_conversion) if factor_conversion else float(l.get('item_price') or 0)
        linea_oc = {
            'product_id': pid,
            'name': prod['display_name'],
            'product_qty': (l.get('qty') or 0) * factor_conversion,
            'price_unit': round(precio_real * factor_descuento, 2),
            'product_uom': prod['uom_id'][0] if prod.get('uom_id') else False,
        }
        nombres_impuestos = nombres_por_producto.get(pid)
        if nombres_impuestos:
            linea_oc['taxes_id'] = [(6, 0, [tax_id_por_nombre[n] for n in nombres_impuestos])]
        order_lines.append((0, 0, linea_oc))

    es_sofia = doc['issuer_rut'] == RUT_DONA_SOFIA
    oc_reusada = False

    if es_sofia:
        qty_dte_por_producto: dict[int, float] = {}
        for _, _, linea_oc in order_lines:
            pid = linea_oc['product_id']
            qty_dte_por_producto[pid] = qty_dte_por_producto.get(pid, 0) + linea_oc['product_qty']

        oc_id, oc_name, motivo = _buscar_oc_sofia(cliente, partner_id, company_id, doc['date'], qty_dte_por_producto)
        if oc_id is None:
            raise RuntimeError(f"Doña Sofía: {motivo} -- no se creó nada, revisar a mano")

        oc_actual = cliente._call('purchase.order', 'read', [[oc_id]], {'fields': ['invoice_status']})[0]
        if oc_actual['invoice_status'] != 'no':
            # La OC que calza por cantidades ya tiene factura -- creada por
            # el proceso de compras existente de Doña Sofía, con el precio
            # que tenía la OC en ese momento (no el del DTE real). Pedido
            # explícito: no se toca una factura ya posteada, solo se avisa.
            raise RuntimeError(
                f"Doña Sofía: la Orden de Compra {oc_name} que calza con este DTE ya tiene una factura "
                f"creada (por el proceso de compras existente, no por este sistema) -- no se modifica nada, "
                f"revisar a mano si el precio de esa factura calza con este DTE"
            )

        lineas_oc_actuales = cliente._call('purchase.order.line', 'search_read',
            [[['order_id', '=', oc_id]]], {'fields': ['product_id', 'price_unit', 'product_qty']})
        linea_id_por_producto = {l['product_id'][0]: l['id'] for l in lineas_oc_actuales if l.get('product_id')}
        valores_originales = {l['id']: {'price_unit': l['price_unit'], 'product_qty': l['product_qty']} for l in lineas_oc_actuales}

        # Se actualiza el PRECIO de toda linea -- pedido explícito del
        # usuario ("los precios que mandan son los de la factura, no los de
        # la OC"). La CANTIDAD de la OC solo se toca para los dos productos
        # con peso variable real (PRODUCTOS_PESO_VARIABLE_SOFIA) -- para
        # cualquier otro producto, si la cantidad no calza es un desajuste
        # real que debe revisarse a mano, no ajustarse solo.
        for _, _, linea_oc in order_lines:
            pid = linea_oc['product_id']
            linea_id = linea_id_por_producto.get(pid)
            if not linea_id:
                continue
            valores = {'price_unit': linea_oc['price_unit']}
            if pid in PRODUCTOS_PESO_VARIABLE_SOFIA:
                valores['product_qty'] = linea_oc['product_qty']
            cliente._call('purchase.order.line', 'write', [[linea_id], valores])

        po_id = oc_id
        oc_reusada = True
    else:
        po_id = cliente._call('purchase.order', 'create', [{
            'partner_id': partner_id,
            'company_id': company_id,
            'date_order': fecha_dte,
            'order_line': order_lines,
            'payment_term_id': payment_term_id,
        }])

    # Verificacion de montos ANTES de confirmar/recibir/facturar -- en
    # borrador (o, para Doña Sofía, ya con los precios del DTE recien
    # escritos), la OC ya calcula Neto/IVA/Total con el mismo motor de
    # impuestos que usara la factura final.
    po_montos = cliente._call('purchase.order', 'read', [[po_id]],
        {'fields': ['amount_untaxed', 'amount_tax', 'amount_total']})[0]
    desajustes = _verificar_montos(doc, po_montos)
    if desajustes:
        if oc_reusada:
            # No se puede cancelar/borrar una OC de Doña Sofía -- ya estaba
            # confirmada de antes (no la creamos nosotros). Se revierten los
            # precios (y cantidades, si se llegaron a tocar) que se acaban
            # de escribir, dejando la OC exactamente como se encontró --
            # "no tocar nada si no calza".
            for linea_id, valores in valores_originales.items():
                try:
                    cliente._call('purchase.order.line', 'write', [[linea_id], valores])
                except Exception:
                    pass
            raise RuntimeError(
                f"No coinciden los valores con la Orden de Compra {oc_name} de Doña Sofía -- se revirtió "
                f"todo lo que se acababa de escribir, no se tocó nada más: " + "; ".join(desajustes)
            )
        # Un borrador no se puede eliminar directo en esta instancia -- Odoo
        # exige cancelarlo primero (button_cancel) y recien ahi el unlink
        # funciona. button_cancel ademas devuelve None, que este XML-RPC no
        # puede serializar en la respuesta -- tira excepcion IGUAL cuando la
        # cancelacion si se aplico (confirmado leyendo el estado real de la
        # OC despues) -- por eso va en su propio try, separado del unlink.
        try:
            cliente._call('purchase.order', 'button_cancel', [[po_id]])
        except Exception:
            pass
        limpio = True
        try:
            cliente._call('purchase.order', 'unlink', [[po_id]])
        except Exception:
            limpio = False
        detalle_oc = ("no quedó ninguna Orden de Compra ni factura en Odoo" if limpio
            else f"la Orden de Compra borrador quedó cancelada en Odoo (revisar/eliminar a mano, id {po_id})")
        raise RuntimeError(
            f"No coinciden los valores -- ingresar de manera manual. {detalle_oc}: " + "; ".join(desajustes)
        )

    if not oc_reusada:
        cliente._call('purchase.order', 'button_confirm', [[po_id]])

    po = cliente._call('purchase.order', 'read', [[po_id]], {'fields': ['picking_ids']})[0]
    for picking_id in po['picking_ids']:
        picking = cliente._call('stock.picking', 'read', [[picking_id]], {'fields': ['move_line_ids', 'state']})[0]
        if picking['state'] == 'done':
            continue
        move_line_ids = picking['move_line_ids']
        if move_line_ids:
            # un solo read para todas las lineas de este picking (antes era
            # un read por linea) -- el write si tiene que ir uno por uno
            # porque cada linea recibe su propia cantidad recibida.
            move_lines = cliente._call('stock.move.line', 'read', [move_line_ids], {'fields': ['quantity']})
            for ml in move_lines:
                cliente._call('stock.move.line', 'write', [[ml['id']], {'qty_done': ml['quantity']}])
        cliente._call('stock.picking', 'button_validate', [[picking_id]])
        cliente._call('stock.picking', 'write', [[picking_id], {'date_done': fecha_dte}])

    cliente._call('purchase.order', 'action_create_invoice', [[po_id]])
    po_facturada = cliente._call('purchase.order', 'read', [[po_id]], {'fields': ['invoice_ids']})[0]
    if not po_facturada['invoice_ids']:
        raise RuntimeError("Odoo no devolvió la factura creada desde la OC")
    move_id = po_facturada['invoice_ids'][-1]

    cliente._call('account.move', 'write', [[move_id], {
        'invoice_date': doc['date'],
        'l10n_latam_document_number': str(doc['l10n_latam_document_number']).zfill(6),
    }])
    cliente._call('l10n_cl.supplier.xml', 'write', [[dte_id], {'invoice_id': move_id}])

    # Ojo: pedir TODOS los campos de account.move falla con un error de
    # permisos (un campo relacionado toca pos.payment, sin acceso para la
    # cuenta de servicio) -- por eso siempre hay que pedir campos explicitos.
    move = cliente._call('account.move', 'read', [[move_id]], {'fields': ['name']})[0]
    return move_id, move['name']


def _procesar_item_cola(cola_id: str, dte_id: int):
    """Corre en un hilo aparte (FastAPI BackgroundTasks) -- no bloquea al
    resto del servidor mientras Odoo procesa la OC/recepcion/factura."""
    db = get_db()
    db.table("facturas_dte_cola").update({"estado": "procesando"}).eq("id", cola_id).execute()
    try:
        cliente = _odoo_sin_http()
        docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
            {'fields': ['id', 'issuer_rut', 'date', 'invoice_id', 'company_id', 'l10n_latam_document_number',
                        'amount_untaxed', 'iva', 'amount_total']})
        if not docs:
            raise RuntimeError("El DTE ya no existe")
        doc = docs[0]
        if doc.get('invoice_id'):
            raise RuntimeError("Este DTE ya tiene una factura creada")
        lineas = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
            {'fields': ['id', 'product_id', 'qty', 'item_price', 'item_name', 'code_ids']})
        sin_producto = [l['id'] for l in lineas if not l.get('product_id')]
        if sin_producto:
            raise RuntimeError(f"Faltan {len(sin_producto)} línea(s) sin producto asignado")

        invoice_id, invoice_name = _ejecutar_creacion(cliente, dte_id, doc, lineas)
        db.table("facturas_dte_cola").update({
            "estado": "completado", "invoice_id": invoice_id, "invoice_name": invoice_name,
        }).eq("id", cola_id).execute()
    except Exception as e:
        db.table("facturas_dte_cola").update({"estado": "error", "error_mensaje": str(e)[:500]}).eq("id", cola_id).execute()


def _odoo_sin_http() -> OdooClient:
    """Igual que _odoo() pero sin HTTPException -- para usar desde el hilo
    en segundo plano, donde no hay una request activa a la que responder."""
    cliente = OdooClient(os.environ["ODOO_URL"], os.environ["ODOO_DB"],
                          os.environ["ODOO_FACTURAS_USER"], os.environ["ODOO_FACTURAS_PASSWORD"])
    ok, msg = cliente.connect()
    if not ok:
        raise RuntimeError(f"No se pudo conectar a Odoo: {msg}")
    return cliente


@router.post("/{dte_id}/crear-factura", response_model=ColaFacturaOut, status_code=status.HTTP_202_ACCEPTED)
def crear_factura(dte_id: int, background_tasks: BackgroundTasks, claims: dict = Depends(get_current_claims)):
    """Valida rapido (lecturas nomas) y encola la creacion real -- crear la
    factura implica 6 llamadas seguidas a Odoo (OC, confirmar, recibir,
    facturar, fijar fecha, fijar folio) y puede demorar varios segundos.
    Encolar en vez de bloquear permite seguir revisando/confirmando otros
    DTE mientras este se procesa en segundo plano (ver _procesar_item_cola)."""
    _require_admin(claims)
    cliente = _odoo()

    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_name', 'invoice_id', 'l10n_latam_document_type_id_code', 'l10n_latam_document_number']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    if doc.get('invoice_id'):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este DTE ya tiene una factura creada")
    if doc.get('l10n_latam_document_type_id_code') != '33':
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"Tipo de documento SII '{doc.get('l10n_latam_document_type_id_code')}' todavía no soportado -- solo Factura Electrónica (33)")

    lineas = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'product_id']})
    sin_producto = [l['id'] for l in lineas if not l.get('product_id')]
    if sin_producto:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"Faltan {len(sin_producto)} línea(s) sin producto asignado -- confirma todas antes de crear la factura")

    # Un indice unico (dte_id) para estado en pendiente/procesando evita que
    # dos clics casi simultaneos para el mismo DTE terminen creando dos
    # facturas duplicadas en Odoo -- el chequeo de invoice_id no alcanza a
    # detectarlo porque crear la factura demora varios segundos.
    db = get_db()
    try:
        fila = db.table("facturas_dte_cola").insert({
            "dte_id": dte_id, "folio": doc.get('l10n_latam_document_number') or '',
            "proveedor_nombre": doc.get('issuer_name') or '', "estado": "pendiente", "creado_por": claims["sub"],
        }).execute().data[0]
    except APIError as e:
        if e.code == "23505":
            raise HTTPException(status.HTTP_409_CONFLICT, "Esta factura ya está en la cola -- espera a que termine") from e
        raise

    background_tasks.add_task(_procesar_item_cola, fila["id"], dte_id)
    return ColaFacturaOut(**fila)


@router.get("/cola/estado", response_model=list[ColaFacturaOut])
def listar_cola(claims: dict = Depends(get_current_claims)):
    """Ultimos items de la cola de creacion -- para el panel que muestra el
    progreso mientras se sigue trabajando en otros DTE."""
    _require_admin(claims)
    db = get_db()
    filas = db.table("facturas_dte_cola").select("*").order("creado_en", desc=True).limit(30).execute().data or []
    return [ColaFacturaOut(**f) for f in filas]


@router.delete("/cola/{cola_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_de_cola(cola_id: str, claims: dict = Depends(get_current_claims)):
    """Saca un item del panel de la cola -- solo lo borra de nuestro
    registro, no toca Odoo (si ya se creo la factura, sigue existiendo
    ahi; si estaba en curso, el trabajo en segundo plano igual termina,
    solo deja de mostrarse aca)."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_cola").delete().eq("id", cola_id).execute()


@router.delete("/cola", status_code=status.HTTP_204_NO_CONTENT)
def limpiar_cola(claims: dict = Depends(get_current_claims)):
    """Igual que eliminar_de_cola pero para todo el panel de una vez --
    mismo alcance (solo nuestro registro, nunca toca Odoo ni cancela
    trabajos en curso)."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_cola").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
