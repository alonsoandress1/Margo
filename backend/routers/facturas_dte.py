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
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from postgrest.exceptions import APIError

from ..db import get_db
from ..deps import get_current_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402

from ..schemas import (ColaFacturaOut, DteDetalleOut, DteLineaOut, DteMatchLineaIn, DteOut,
                       DteProductoOut)

router = APIRouter(prefix="/facturas-dte", tags=["facturas-dte"])

TOLERANCIA_MONTOS = 9  # pesos -- diferencia maxima aceptada entre el DTE y la factura creada en Odoo


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
    una factura borrador creada en Odoo (invoice_id vacio)."""
    _require_admin(claims)
    cliente = _odoo()
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read',
        [[['date', '>=', desde], ['date', '<=', hasta], ['invoice_id', '=', False]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date'],
         'order': 'issuer_name, date'})
    return [
        DteOut(id=d['id'], proveedor_rut=d.get('issuer_rut') or '', proveedor_nombre=d.get('issuer_name') or '',
               folio=d.get('l10n_latam_document_number') or '', fecha=d.get('date'), tiene_factura=False)
        for d in docs
    ]


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
    fecha y el folio del DTE, que Odoo no puede saber por si solo."""
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

    product_ids = list({l['product_id'][0] for l in lineas})
    productos = cliente._call('product.product', 'read', [product_ids], {'fields': ['uom_id', 'display_name']})
    info_por_producto = {p['id']: p for p in productos}

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
        order_lines.append((0, 0, {
            'product_id': pid,
            'name': prod['display_name'],
            'product_qty': l.get('qty') or 0,
            'price_unit': round(float(l.get('item_price') or 0) * factor_descuento, 2),
            'product_uom': prod['uom_id'][0] if prod.get('uom_id') else False,
        }))

    po_id = cliente._call('purchase.order', 'create', [{
        'partner_id': partner_id,
        'company_id': company_id,
        'date_order': fecha_dte,
        'order_line': order_lines,
    }])

    # Verificacion de montos ANTES de confirmar/recibir/facturar -- en
    # borrador, la OC ya calcula Neto/IVA/Total con el mismo motor de
    # impuestos que usara la factura final, y todavia se puede borrar
    # limpio (unlink) si no calza, sin dejar nada a medio crear en Odoo.
    po_montos = cliente._call('purchase.order', 'read', [[po_id]],
        {'fields': ['amount_untaxed', 'amount_tax', 'amount_total']})[0]
    desajustes = _verificar_montos(doc, po_montos)
    if desajustes:
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
            {'fields': ['id', 'product_id', 'qty', 'item_price']})
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
