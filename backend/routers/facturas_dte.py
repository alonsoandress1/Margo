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

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_db
from ..deps import get_current_claims

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402

from ..schemas import (DteCrearFacturaOut, DteDetalleOut, DteLineaOut, DteMatchLineaIn, DteOut,
                       DteProductoOut)

router = APIRouter(prefix="/facturas-dte", tags=["facturas-dte"])


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


def _mejor_codigo(codigos: list[dict]) -> tuple[str | None, str | None]:
    """De los codigos de una linea (puede traer mas de uno), el primero que
    tenga code_value -- mismo criterio que el script de extraccion."""
    for c in codigos:
        if c.get("code_value"):
            return c["code_type"], c["code_value"]
    return None, None


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
    """Detalle de un DTE con sus lineas -- cada linea trae sugerido el
    product_id de nuestro mapeo aprendido (facturas_producto_mapa) cuando
    hay uno guardado para ese proveedor+codigo, sin escribir nada todavia
    en Odoo (eso pasa solo cuando se confirma via /lineas/match)."""
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
        codigo_tipo, codigo_valor = _mejor_codigo(codigos)
        product_id = l['product_id'][0] if l.get('product_id') else None
        product_name = l['product_id'][1] if l.get('product_id') else None
        sugerido = False
        if not product_id and codigo_tipo and (codigo_tipo, codigo_valor) in mapa:
            m = mapa[(codigo_tipo, codigo_valor)]
            product_id, product_name, sugerido = m["odoo_product_id"], m["odoo_product_name"], True
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


def _resolver_journal(cliente: OdooClient, company_id: int) -> int:
    js = cliente._call('account.journal', 'search_read',
        [[['type', '=', 'purchase'], ['company_id', '=', company_id], ['name', 'ilike', 'Facturas de proveedores']]],
        {'fields': ['id']})
    if len(js) != 1:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
            f"No encontré un único diario 'Facturas de proveedores' para la empresa {company_id} en Odoo (encontrados: {len(js)})")
    return js[0]['id']


def _resolver_impuesto(cliente: OdooClient, company_id: int, nombre: str) -> int:
    ts = cliente._call('account.tax', 'search_read',
        [[['type_tax_use', '=', 'purchase'], ['company_id', '=', company_id], ['name', '=', nombre]]],
        {'fields': ['id']})
    if len(ts) != 1:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
            f"No encontré el impuesto '{nombre}' para la empresa {company_id} en Odoo (encontrados: {len(ts)})")
    return ts[0]['id']


def _resolver_tipo_documento(cliente: OdooClient, code: str) -> int:
    ds = cliente._call('l10n_latam.document.type', 'search_read', [[['code', '=', code]]], {'fields': ['id']})
    if not ds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tipo de documento SII '{code}' no reconocido en Odoo")
    return ds[0]['id']


@router.post("/{dte_id}/crear-factura", response_model=DteCrearFacturaOut)
def crear_factura(dte_id: int, claims: dict = Depends(get_current_claims)):
    """Ultimo paso: todas las lineas ya deben tener product_id (confirmado a
    mano via /lineas/match).

    El boton 'Crear Factura Proveedor' de Odoo (metodo create_invoice) esta
    roto en esta instancia -- probado directo en la UI de Odoo, mismo error:
    KeyError: 'ir.property' en el modulo de terceros od_dte (usa un modelo
    que ya no existe en esta version de Odoo). Por eso creamos la factura
    (account.move) directo, replicando el patron de una factura real ya
    creada desde una OC: mismo diario/tipo de documento SII, product_id +
    cantidad + precio tal cual el DTE. La cuenta contable de cada linea se
    deja vacia a proposito -- Odoo no la completa sola sin pasar por el
    boton roto, y contabilidad la asigna al revisar el borrador. El
    impuesto por producto se guarda en facturas_producto_impuesto (default
    'IVA 19% Compra' si el producto no esta ahi) -- los impuestos son por
    EMPRESA en Odoo, se busca el id real segun la empresa de cada DTE."""
    _require_admin(claims)
    cliente = _odoo()

    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'date', 'invoice_id', 'company_id',
                     'l10n_latam_document_type_id_code', 'l10n_latam_document_number']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    if doc.get('invoice_id'):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este DTE ya tiene una factura creada")
    if doc.get('l10n_latam_document_type_id_code') != '33':
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"Tipo de documento SII '{doc.get('l10n_latam_document_type_id_code')}' todavía no soportado -- solo Factura Electrónica (33)")

    lineas = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'product_id', 'qty', 'item_price']})
    sin_producto = [l['id'] for l in lineas if not l.get('product_id')]
    if sin_producto:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            f"Faltan {len(sin_producto)} línea(s) sin producto asignado -- confirma todas antes de crear la factura")

    company_id = doc['company_id'][0]
    partners = cliente._call('res.partner', 'search_read', [[['vat', '=', doc['issuer_rut']]]], {'fields': ['id']})
    if len(partners) != 1:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
            f"No encontré (o encontré más de uno) el proveedor con RUT {doc['issuer_rut']} en Odoo")
    partner_id = partners[0]['id']

    empresa = cliente._call('res.company', 'read', [[company_id]], {'fields': ['currency_id']})[0]
    currency_id = empresa['currency_id'][0]

    journal_id = _resolver_journal(cliente, company_id)
    doctype_id = _resolver_tipo_documento(cliente, '33')

    product_ids = list({l['product_id'][0] for l in lineas})
    productos = cliente._call('product.product', 'read', [product_ids], {'fields': ['uom_id']})
    uom_por_producto = {p['id']: p['uom_id'][0] for p in productos}

    db = get_db()
    mapeos_tax = db.table("facturas_producto_impuesto").select("odoo_product_id,impuesto_nombre") \
        .in_("odoo_product_id", product_ids).execute().data or []
    nombre_impuesto_por_producto = {m["odoo_product_id"]: m["impuesto_nombre"] for m in mapeos_tax}

    impuesto_id_por_nombre: dict[str, int] = {}

    def _impuesto_id(nombre: str) -> int:
        if nombre not in impuesto_id_por_nombre:
            impuesto_id_por_nombre[nombre] = _resolver_impuesto(cliente, company_id, nombre)
        return impuesto_id_por_nombre[nombre]

    order_lines = []
    for l in lineas:
        pid = l['product_id'][0]
        nombre_imp = nombre_impuesto_por_producto.get(pid, 'IVA 19% Compra')
        order_lines.append((0, 0, {
            'product_id': pid,
            'quantity': l.get('qty') or 0,
            'price_unit': float(l.get('item_price') or 0),
            'product_uom_id': uom_por_producto.get(pid),
            'tax_ids': [(6, 0, [_impuesto_id(nombre_imp)])],
        }))

    vals = {
        'move_type': 'in_invoice',
        'company_id': company_id,
        'journal_id': journal_id,
        'partner_id': partner_id,
        'currency_id': currency_id,
        'invoice_date': doc['date'],
        'l10n_latam_document_type_id': doctype_id,
        'l10n_latam_document_number': str(doc['l10n_latam_document_number']).zfill(6),
        'invoice_line_ids': order_lines,
    }
    move_id = cliente._call('account.move', 'create', [vals])
    cliente._call('l10n_cl.supplier.xml', 'write', [[dte_id], {'invoice_id': move_id}])

    move = cliente._call('account.move', 'read', [[move_id]], {'fields': ['name']})[0]
    return DteCrearFacturaOut(invoice_id=move_id, invoice_name=move['name'])
