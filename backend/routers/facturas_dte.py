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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from postgrest.exceptions import APIError

from ..db import get_db
from ..deps import get_current_claims, get_odoo_credentials

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402

from ..schemas import (CantidadRecibidaIn, CargarStockManualIn, ColaFacturaOut, CompararOut, CompararLineaOut,
                       DescuentoLineaIn, DteDetalleOut, DteLineaOut, DteLineaSimpleOut, DteMarcadoManualOut,
                       DteMatchLineaIn, DteNotaCreditoDetalleOut, DteOut, DteProductoOut,
                       FactorConversionIn, HistoricoFacturaOut, HistoricoLineaOut,
                       ImpuestoOut, LineaManualIn, MarcarManualOut, MarcarManualLineaOut, ProductoImpuestosIn,
                       ProveedorOcultarIn, ProveedorOcultoOut, SimularImpuestoOut, SimularOut)

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


def _require_lectura(claims: dict):
    """Observador puede ver todo (pedido explicito del usuario), nunca
    cambiar nada -- se usa solo en los endpoints puramente de lectura."""
    if claims["rol"] not in ("administrador", "observador"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a Facturas Odoo")


def _odoo(odoo_creds: tuple[str, str]) -> OdooClient:
    """Conecta con las credenciales de Odoo de la persona que esta usando el
    sistema en este momento -- nunca una cuenta compartida (pedido explicito
    del usuario). El navegador las manda en cada request (headers
    X-Odoo-User/X-Odoo-Password, ver get_odoo_credentials en deps.py);
    nunca se guardan en la base de datos."""
    usuario, password = odoo_creds
    try:
        cliente = OdooClient(os.environ["ODOO_URL"], os.environ["ODOO_DB"], usuario, password)
    except KeyError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
    ok, msg = cliente.connect()
    if not ok:
        # Credenciales de Odoo invalidas -> 428 (el frontend vuelve a pedirlas),
        # no 502 (que es para un problema real de conectividad/servidor).
        if "credenciales incorrectas" in msg.lower():
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, f"Odoo: {msg}")
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
def listar_pendientes(desde: str, hasta: str, claims: dict = Depends(get_current_claims),
                       odoo_creds: tuple[str, str] = Depends(get_odoo_credentials),
                       x_odoo_company_id: str | None = Header(default=None)):
    """DTE recibidos del SII en el rango de fechas que TODAVIA no tienen
    una factura borrador creada en Odoo (invoice_id vacio). Factura
    Electrónica (tipo SII 33) y Nota de Crédito Electrónica (tipo 61,
    marcada con es_nota_credito=True) -- las NC son SOLO VISUALIZACION por
    ahora (el frontend no expone "Revisar" ni "Ingresada Manualmente" para
    ellas, ver renderDteResultados). Otros tipos (Guías de Despacho,
    Facturas Exentas, etc.) siguen sin poder procesarse en esta pantalla y
    quedan excluidos (confirmado revisando datos reales: 94 de 704
    pendientes eran de otro tipo, de las cuales 68 eran NC). No
    incluye proveedores marcados como ocultos (facturas_proveedor_oculto)
    ni DTE marcados como ingresados a mano (facturas_dte_ingresado_manual --
    alguien ya creo la factura real en Odoo por fuera de esta pantalla,
    sin que el DTE quedara vinculado a ella).

    x_odoo_company_id es la empresa que la persona eligio en el frontend
    (GET /odoo/empresas, solo se le pregunta si tiene acceso a 2 o mas) --
    sin esto, un usuario con acceso a varias empresas en Odoo veria DTE de
    TODAS mezclados en una sola lista, sin forma de saber a que local
    pertenece cada uno."""
    _require_lectura(claims)
    db = get_db()
    ocultos = {f["proveedor_rut"] for f in (db.table("facturas_proveedor_oculto").select("proveedor_rut").execute().data or [])}
    marcados_manual = {f["dte_id"] for f in (db.table("facturas_dte_ingresado_manual").select("dte_id").execute().data or [])}
    cliente = _odoo(odoo_creds)
    domain = [['date', '>=', desde], ['date', '<=', hasta], ['invoice_id', '=', False]]
    if x_odoo_company_id:
        try:
            domain.append(['company_id', '=', int(x_odoo_company_id)])
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Odoo-Company-Id invalido")
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read',
        [domain],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date', 'amount_total',
                    'l10n_latam_document_type_id_code'],
         'order': 'issuer_name, date'})
    return [
        DteOut(id=d['id'], proveedor_rut=d.get('issuer_rut') or '', proveedor_nombre=d.get('issuer_name') or '',
               folio=d.get('l10n_latam_document_number') or '', fecha=d.get('date'),
               monto_total=_monto(d.get('amount_total')), tiene_factura=False,
               es_nota_credito=d.get('l10n_latam_document_type_id_code') == '61')
        for d in docs
        if d.get('l10n_latam_document_type_id_code') in ('33', '61')
        and (d.get('issuer_rut') or '') not in ocultos and d['id'] not in marcados_manual
    ]


@router.post("/{dte_id}/marcar-manual", response_model=MarcarManualOut)
def marcar_ingresada_manual(dte_id: int, claims: dict = Depends(get_current_claims),
                             odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Marca este DTE como ya ingresado a mano en Odoo (por fuera de esta
    pantalla) -- deja de aparecer como pendiente. Ademas busca la factura
    real en Odoo (mismo proveedor + mismo folio, igual criterio que el
    chequeo de duplicados de _ejecutar_creacion) para:
    1) vincularla al DTE (invoice_id) -- para que quede prolijo, no se
       arriesgue un duplicado despues, y quede disponible para "Comparar",
    2) si esa factura no tiene Orden de Compra detras (invoice_origin
       vacio -- el caso tipico de una factura entrada a mano directo en
       Odoo, sin pasar por OC), agregarla a planilla_compras_factura_manual
       para que igual aparezca en la Planilla de Compras -- que de otra
       forma la excluye por parecer un gasto administrativo (arriendo,
       seguro), ver planilla_compras.py,
    3) devolver sus lineas reales (producto + cantidad facturada) para que
       el frontend pueda mostrar el modal de "Cantidad recibida" y cargar
       Bodega automatico (ver cargar_stock_manual, mas abajo) -- este
       camino nunca pasa por _ejecutar_creacion, asi que sin esto Bodega
       quedaria sin cargar (antes se compensaba a mano con "Registrar
       movimiento" en Inventario, pedido explicito del usuario integrarlo
       aca tambien).
    Si no se encuentra una factura real que calce sola (0 o 2+
    candidatas), se marca igual como resuelta pero sin vincular ni agregar
    a la planilla -- revisar a mano despues (factura_vinculada=False, sin
    lineas -- el frontend no muestra el modal de cargar stock)."""
    _require_admin(claims)
    cliente = _odoo(odoo_creds)
    db = get_db()

    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'l10n_latam_document_number', 'company_id']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]

    factura_id_vinculada = None
    invoice_name = None
    lineas_out: list[MarcarManualLineaOut] = []
    folio = _normalizar_folio(doc.get('l10n_latam_document_number'))
    if folio and doc.get('issuer_rut') and doc.get('company_id'):
        partners = cliente._call('res.partner', 'search_read', [[['vat', '=', doc['issuer_rut']]]], {'fields': ['id']})
        partner_ids = [p['id'] for p in partners]
        if partner_ids:
            facturas = cliente._call('account.move', 'search_read',
                [[['partner_id', 'in', partner_ids], ['company_id', '=', doc['company_id'][0]],
                  ['move_type', '=', 'in_invoice'], ['state', '!=', 'cancel']]],
                {'fields': ['id', 'name', 'l10n_latam_document_number', 'invoice_origin', 'invoice_date']})
            candidatas = [f for f in facturas if _normalizar_folio(f.get('l10n_latam_document_number')) == folio]
            if len(candidatas) == 1:
                factura = candidatas[0]
                factura_id_vinculada = factura['id']
                invoice_name = factura.get('name')
                cliente._call('l10n_cl.supplier.xml', 'write', [[dte_id], {'invoice_id': factura['id']}])
                if not factura.get('invoice_origin'):
                    db.table("planilla_compras_factura_manual").upsert({
                        "factura_id": factura['id'], "agregado_por": claims["sub"],
                        "invoice_date": factura.get('invoice_date') or None,
                    }).execute()

                move_lineas = cliente._call('account.move.line', 'search_read',
                    [[['move_id', '=', factura['id']], ['display_type', '=', 'product']]],
                    {'fields': ['product_id', 'quantity', 'price_unit']})
                lineas_out = [
                    MarcarManualLineaOut(product_id=ml['product_id'][0], product_name=ml['product_id'][1],
                                          cantidad=ml['quantity'], price_unit=ml.get('price_unit') or 0)
                    for ml in move_lineas if ml.get('product_id')
                ]

    db.table("facturas_dte_ingresado_manual").upsert({
        "dte_id": dte_id, "marcado_por": claims["sub"], "factura_id_vinculada": factura_id_vinculada,
    }, on_conflict="dte_id").execute()

    return MarcarManualOut(factura_vinculada=factura_id_vinculada is not None, invoice_name=invoice_name, lineas=lineas_out)


@router.post("/{dte_id}/marcar-manual/cargar-stock", status_code=status.HTTP_204_NO_CONTENT)
def cargar_stock_manual(dte_id: int, body: CargarStockManualIn, claims: dict = Depends(get_current_claims),
                         odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Carga Bodega desde la factura real que "Ingresada Manualmente" ya
    vinculo (ver marcar_ingresada_manual) -- mismo mecanismo que la
    creacion automatica de factura (_alimentar_stock_bodega), pero para el
    camino en que la OC/recepcion/factura se armaron 100% a mano en Odoo.

    Nunca confia en lo que mando el cliente salvo cantidad_recibida por
    producto -- vuelve a leer la factura real, sus lineas y sus productos
    frescos desde Odoo (mismo patron que _procesar_item_cola). cantidad_recibida
    reemplaza a la cantidad facturada SOLO para lo que se acredita a
    Bodega -- la factura real en Odoo nunca se toca."""
    _require_admin(claims)
    db = get_db()

    fila = db.table("facturas_dte_ingresado_manual").select("*").eq("dte_id", dte_id).execute().data
    if not fila:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta factura todavía no se marcó como ingresada a mano")
    fila = fila[0]
    if fila.get("stock_cargado"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El stock de esta factura ya se cargó a Bodega")
    if not fila.get("factura_id_vinculada"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
            "Esta factura no tiene una factura real vinculada en Odoo -- no se puede cargar stock automático, "
            "usa Registrar movimiento en Inventario")

    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'company_id']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    move_id = fila["factura_id_vinculada"]

    move = cliente._call('account.move', 'read', [[move_id]], {'fields': ['name']})[0]
    move_lineas = cliente._call('account.move.line', 'search_read',
        [[['move_id', '=', move_id], ['display_type', '=', 'product']]],
        {'fields': ['product_id', 'quantity', 'price_unit']})
    move_lineas = [ml for ml in move_lineas if ml.get('product_id')]
    if not move_lineas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La factura vinculada no tiene líneas con producto -- nada que cargar")

    product_ids = list({ml['product_id'][0] for ml in move_lineas})
    productos = cliente._call('product.product', 'read', [product_ids], {'fields': ['uom_id']})
    uom_por_producto = {p['id']: p['uom_id'] for p in productos if p.get('uom_id')}
    uom_nombre_por_producto = {pid: uom[1] for pid, uom in uom_por_producto.items()}

    partner_id = None
    if doc.get('issuer_rut'):
        partners = cliente._call('res.partner', 'search_read', [[['vat', '=', doc['issuer_rut']]]], {'fields': ['id']})
        if partners:
            partner_id = partners[0]['id']

    cantidad_recibida_por_producto = {l.product_id: l.cantidad_recibida for l in body.lineas}
    lineas = []
    for ml in move_lineas:
        pid = ml['product_id'][0]
        cantidad_facturada = ml['quantity']
        lineas.append({
            'product_id': pid, 'name': ml['product_id'][1], 'price_unit': ml.get('price_unit'),
            'product_uom': uom_por_producto.get(pid, [None])[0],
            'cantidad_facturada': cantidad_facturada,
            'cantidad_bodega': cantidad_recibida_por_producto.get(pid, cantidad_facturada),
        })

    _creditar_stock_bodega(db, cliente, doc['company_id'][0], dte_id, move_id, move['name'],
                            doc.get('issuer_name') or '', doc.get('issuer_rut') or '', partner_id,
                            uom_nombre_por_producto, lineas, origen="factura_manual")

    db.table("facturas_dte_ingresado_manual").update({"stock_cargado": True}).eq("dte_id", dte_id).execute()


@router.delete("/{dte_id}/marcar-manual", status_code=status.HTTP_204_NO_CONTENT)
def desmarcar_ingresada_manual(dte_id: int, claims: dict = Depends(get_current_claims)):
    """Revierte la marca de 'ingresada a mano' -- vuelve a aparecer como
    pendiente si Odoo sigue sin tener invoice_id vinculado (si se encontro
    y vinculo una factura real al marcarla, ese vinculo en Odoo NO se
    deshace -- es un hecho real, no solo la marca de esta pantalla). Si
    esa factura se habia agregado a planilla_compras_factura_manual, se
    saca de ahi tambien."""
    _require_admin(claims)
    db = get_db()
    fila = db.table("facturas_dte_ingresado_manual").select("factura_id_vinculada").eq("dte_id", dte_id).execute().data
    if fila and fila[0].get("factura_id_vinculada"):
        db.table("planilla_compras_factura_manual").delete().eq("factura_id", fila[0]["factura_id_vinculada"]).execute()
    db.table("facturas_dte_ingresado_manual").delete().eq("dte_id", dte_id).execute()


@router.get("/marcados-manual", response_model=list[DteMarcadoManualOut])
def listar_marcados_manual(claims: dict = Depends(get_current_claims),
                            odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """DTE marcados como 'ingresada manualmente' hoy -- para poder
    revisarlos y desmarcarlos si hace falta (ver desmarcar_ingresada_manual
    arriba). Sin esta lista no habia forma de saber cuales estaban
    marcados ni de deshacer una marca por error sin entrar directo a
    Supabase."""
    _require_lectura(claims)
    db = get_db()
    marcados = db.table("facturas_dte_ingresado_manual").select("*").order("marcado_en", desc=True).execute().data or []
    if not marcados:
        return []
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', 'in', [m["dte_id"] for m in marcados]]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date']})
    docs_por_id = {d['id']: d for d in docs}
    resultado = []
    for m in marcados:
        d = docs_por_id.get(m["dte_id"])
        if not d:
            continue  # el DTE ya no existe en Odoo (borrado) -- se omite, no hay nada que mostrar
        resultado.append(DteMarcadoManualOut(
            dte_id=m["dte_id"], proveedor_rut=d.get('issuer_rut') or '', proveedor_nombre=d.get('issuer_name') or '',
            folio=d.get('l10n_latam_document_number') or '', fecha=d.get('date'),
            marcado_en=m["marcado_en"], factura_vinculada=m.get("factura_id_vinculada") is not None,
            stock_cargado=m.get("stock_cargado") or False,
        ))
    return resultado


@router.get("/proveedores/ocultos", response_model=list[ProveedorOcultoOut])
def listar_proveedores_ocultos(claims: dict = Depends(get_current_claims)):
    """Proveedores actualmente ocultos de la lista de pendientes."""
    _require_lectura(claims)
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
def buscar_producto(q: str, claims: dict = Depends(get_current_claims),
                     odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Busca productos YA EXISTENTES en Odoo por nombre o codigo interno --
    solo lectura, nunca crea nada. Para cuando una linea no tiene sugerencia
    y hay que buscar el producto correcto a mano."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    productos = cliente._call('product.product', 'search_read',
        [[['purchase_ok', '=', True], '|', ['name', 'ilike', q], ['default_code', 'ilike', q]]],
        {'fields': ['id', 'name', 'default_code', 'uom_id'], 'limit': 30})
    return [
        DteProductoOut(id=p['id'], name=p['name'], default_code=p.get('default_code') or None,
                        uom=p['uom_id'][1] if p.get('uom_id') else None)
        for p in productos
    ]


@router.get("/impuestos/buscar", response_model=list[ImpuestoOut])
def buscar_impuesto(q: str = '', claims: dict = Depends(get_current_claims),
                     odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Busca impuestos de compra YA EXISTENTES en Odoo por nombre (ej. "IVA
    19% Compra", "Impuesto a la Carne 5%") -- solo lectura. Se buscan en la
    empresa por defecto del usuario conectado; al crear la factura se
    resuelve el impuesto real de CADA empresa por el mismo nombre (los
    impuestos son por empresa en Odoo, ver _ejecutar_creacion)."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    dominio = [['type_tax_use', '=', 'purchase'], ['active', '=', True]]
    if q:
        dominio.append(['name', 'ilike', q])
    impuestos = cliente._call('account.tax', 'search_read', [dominio],
        {'fields': ['id', 'name', 'amount'], 'limit': 30, 'order': 'name'})
    return [ImpuestoOut(id=i['id'], name=i['name'], amount=i.get('amount') or 0) for i in impuestos]


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


@router.put("/lineas/{linea_id}/descuento", status_code=status.HTTP_204_NO_CONTENT)
def fijar_descuento_linea(linea_id: int, body: DescuentoLineaIn, claims: dict = Depends(get_current_claims)):
    """Guarda el % de descuento de ESTA linea puntual -- el descuento real
    varia linea por linea (no es un % parejo para toda la factura, ver
    _ejecutar_creacion), asi que se confirma producto por producto, no una
    vez por factura. El valor por defecto es 0 (sin descuento) -- el DTE
    nunca trae el descuento poblado por linea, el admin lo ve en la factura
    real y lo escribe a mano."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_linea_descuento").upsert({
        "dte_linea_id": linea_id, "descuento_pct": body.descuento_pct, "actualizado_por": claims["sub"],
        "proveedor_rut": body.proveedor_rut, "odoo_product_id": body.odoo_product_id,
        # actualizado_en tiene default now() en la fila NUEVA, pero un upsert
        # sobre una fila existente no lo toca solo -- se fija a mano para
        # que detalle() pueda ordenar el historial por "el mas reciente" de
        # verdad, no por la fecha del primer guardado de esa linea.
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="dte_linea_id").execute()


@router.put("/lineas/{linea_id}/cantidad-recibida", status_code=status.HTTP_204_NO_CONTENT)
def fijar_cantidad_recibida(linea_id: int, body: CantidadRecibidaIn, claims: dict = Depends(get_current_claims)):
    """Guarda cuanto REALMENTE llego de esta linea, cuando difiere de lo
    facturado (factura mal despachada -- vienen menos unidades, o la mitad
    de un item). No cambia la factura/OC real en Odoo (eso siempre debe
    reflejar lo que el proveedor facturo, para contabilidad/SII) -- solo
    corrige cuanto se suma a nuestro Stock de Bodega interno cuando la
    factura se crea (ver _ejecutar_creacion / _alimentar_stock_bodega). Sin
    guardar nada acá, se usa la cantidad facturada tal cual, como siempre."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_linea_recibido").upsert({
        "dte_linea_id": linea_id, "cantidad_recibida": body.cantidad_recibida,
        "actualizado_por": claims["sub"], "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="dte_linea_id").execute()


@router.post("/{dte_id}/lineas-manuales", status_code=status.HTTP_204_NO_CONTENT)
def agregar_linea_manual(dte_id: int, body: LineaManualIn, claims: dict = Depends(get_current_claims)):
    """Agrega una linea a mano para este DTE -- para un producto/cargo que el
    proveedor declaro en el Neto/Total pero que no vino como linea propia en
    el XML (ej. flete, envase). No toca l10n_cl.supplier.xml.line (esa tabla
    es la copia fiel de lo que declaro el SII) -- se guarda aparte y se suma
    a las lineas reales del DTE recien al crear la Orden de Compra (ver
    _ejecutar_creacion). No soportado para Doña Sofía -- se valida ahi
    mismo, al momento de crear, no aca."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_linea_manual").insert({
        "dte_id": dte_id, "odoo_product_id": body.odoo_product_id, "odoo_product_name": body.odoo_product_name,
        "qty": body.qty, "precio_unitario": body.precio_unitario, "descuento_pct": body.descuento_pct,
        "proveedor_rut": body.proveedor_rut, "agregado_por": claims["sub"],
    }).execute()


@router.put("/lineas-manuales/{linea_id}/descuento", status_code=status.HTTP_204_NO_CONTENT)
def fijar_descuento_linea_manual(linea_id: int, body: DescuentoLineaIn, claims: dict = Depends(get_current_claims)):
    """Igual que fijar_descuento_linea pero para una linea agregada a mano
    -- se guarda directo en su propia fila (no en facturas_dte_linea_descuento,
    que es solo para lineas reales del DTE)."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_linea_manual").update({"descuento_pct": body.descuento_pct}).eq("id", linea_id).execute()


@router.delete("/lineas-manuales/{linea_id}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_linea_manual(linea_id: int, claims: dict = Depends(get_current_claims)):
    """Quita una linea agregada a mano -- reversible en el sentido de que se
    puede volver a agregar, pero la fila se borra (no queda historial)."""
    _require_admin(claims)
    db = get_db()
    db.table("facturas_dte_linea_manual").delete().eq("id", linea_id).execute()


@router.get("/{dte_id}/comparar", response_model=CompararOut)
def comparar(dte_id: int, claims: dict = Depends(get_current_claims),
             odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Compara linea por linea lo que declaro el DTE del proveedor contra lo
    que realmente quedo creado en la factura de Odoo -- lee la factura REAL
    (no una simulacion), asi que solo funciona para DTE que ya tienen
    factura creada."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'invoice_id', 'amount_untaxed', 'amount_total']})
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

    # Empareja por product_id -- normalmente una sola linea de OC/factura
    # por producto (ver _ejecutar_creacion), pero puede haber DOS para el
    # mismo producto si ademas se agrego una linea manual con ese mismo
    # product_id (ver facturas_dte_linea_manual) -- se guardan en una cola
    # por producto y se consumen de a una para no pisar la comparacion de
    # una linea con la de otra.
    odoo_por_producto: dict[int, list[dict]] = {}
    for ml in move_lineas:
        if ml.get('product_id'):
            odoo_por_producto.setdefault(ml['product_id'][0], []).append(ml)

    lineas_out = []
    for l in lineas_dte:
        pid = l['product_id'][0] if l.get('product_id') else None
        ml = odoo_por_producto[pid].pop(0) if pid and odoo_por_producto.get(pid) else None
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

    neto_dte = _monto(doc.get('amount_untaxed'))
    total_dte = _monto(doc.get('amount_total'))
    return CompararOut(
        invoice_name=move['name'],
        # impuestos_dte = Total - Neto (TODOS los impuestos declarados, no
        # solo 'iva') -- ver el comentario en _verificar_montos: el campo
        # 'iva' del DTE no incluye otros impuestos reales como el ILA.
        neto_dte=neto_dte, impuestos_dte=round(total_dte - neto_dte, 2), total_dte=total_dte,
        neto_odoo=move.get('amount_untaxed') or 0, impuestos_odoo=move.get('amount_tax') or 0, total_odoo=move.get('amount_total') or 0,
        lineas=lineas_out,
    )


@router.get("/proveedor/{partner_id}/historico", response_model=list[HistoricoFacturaOut])
def historico_proveedor(partner_id: int, limite: int = 6, claims: dict = Depends(get_current_claims),
                         odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Ultimas facturas REALES (account.move, ya posteadas) de un proveedor
    -- por su id real de Odoo (res.partner, el mismo que odoo_supplier_id
    en nuestra tabla proveedores, para no depender de matchear por RUT --
    ver el problema de RUTs duplicados documentado en _ejecutar_creacion),
    con el precio real de cada linea. Solo lectura, para poder revisar a
    mano si el precio viene variando entre facturas antes de cargar un
    Precio Negociado en Proveedores (no se guarda nada solo, el admin
    decide que precio estipular con los datos que devuelve esto)."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)

    moves = cliente._call('account.move', 'search_read',
        [[['partner_id', '=', partner_id], ['move_type', '=', 'in_invoice'], ['state', '=', 'posted']]],
        {'fields': ['id', 'name', 'invoice_date'], 'order': 'invoice_date desc, id desc', 'limit': limite})
    if not moves:
        return []

    lineas = cliente._call('account.move.line', 'search_read',
        [[['move_id', 'in', [m['id'] for m in moves]], ['display_type', '=', 'product']]],
        {'fields': ['move_id', 'product_id', 'quantity', 'price_unit']})
    lineas_por_move: dict[int, list] = {}
    for l in lineas:
        if l.get('product_id'):
            lineas_por_move.setdefault(l['move_id'][0], []).append(l)

    return [
        HistoricoFacturaOut(
            invoice_name=m['name'], fecha=m.get('invoice_date'),
            lineas=[
                HistoricoLineaOut(
                    product_id=l['product_id'][0], product_name=l['product_id'][1],
                    cantidad=l['quantity'], precio_unit=l['price_unit'],
                )
                for l in lineas_por_move.get(m['id'], [])
            ],
        )
        for m in moves
    ]


@router.get("/{dte_id}/simular", response_model=SimularOut)
def simular(dte_id: int, claims: dict = Depends(get_current_claims),
            odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Calcula Neto, cada impuesto por separado y Total con lo que esta
    confirmado HOY para esta factura (producto asignado, descuento por
    linea, impuestos por producto guardados o el default del producto en
    Odoo) -- sin escribir nada en Odoo. Aproxima el motor de impuestos de
    Odoo (suma simple por %, sin impuestos compuestos -- el caso real de
    este negocio). Las lineas sin producto asignado no se pueden incluir
    (no se sabe que impuesto usan) y se cuentan aparte en
    lineas_sin_producto."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'company_id', 'amount_untaxed', 'amount_total']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    company_id = doc['company_id'][0]

    lineas = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'qty', 'item_price', 'product_id']})

    db = get_db()
    linea_ids = [l['id'] for l in lineas]
    descuentos = db.table("facturas_dte_linea_descuento").select("dte_linea_id,descuento_pct") \
        .in_("dte_linea_id", linea_ids).execute().data or [] if linea_ids else []
    descuento_por_linea = {d["dte_linea_id"]: d["descuento_pct"] for d in descuentos}

    lineas_manuales = db.table("facturas_dte_linea_manual").select("*").eq("dte_id", dte_id).execute().data or []

    # Impuestos por producto -- resuelto batcheado para todos los productos
    # de la factura de una vez (ver _impuestos_actuales_por_producto).
    product_ids = list({l['product_id'][0] for l in lineas if l.get('product_id')}
                        | {lm['odoo_product_id'] for lm in lineas_manuales})
    nombres_por_producto = _impuestos_actuales_por_producto(cliente, db, product_ids)

    nombres_unicos = list({n for ns in nombres_por_producto.values() for n in ns})
    tasa_por_nombre: dict[str, float] = {}
    if nombres_unicos:
        taxes = cliente._call('account.tax', 'search_read',
            [[['name', 'in', nombres_unicos], ['company_id', '=', company_id], ['type_tax_use', '=', 'purchase']]],
            {'fields': ['name', 'amount']})
        tasa_por_nombre = {t['name']: t['amount'] for t in taxes}

    neto = 0.0
    impuestos_acumulados: dict[str, float] = {}
    lineas_sin_producto = 0
    for l in lineas:
        if not l.get('product_id'):
            lineas_sin_producto += 1
            continue
        pid = l['product_id'][0]
        descuento = descuento_por_linea.get(l['id'], 0)
        subtotal = (l.get('qty') or 0) * float(l.get('item_price') or 0) * (1 - descuento / 100)
        neto += subtotal
        for nombre in nombres_por_producto.get(pid, []):
            tasa = tasa_por_nombre.get(nombre, 0)
            impuestos_acumulados[nombre] = impuestos_acumulados.get(nombre, 0) + subtotal * tasa / 100

    for lm in lineas_manuales:
        pid = lm['odoo_product_id']
        subtotal = (lm.get('qty') or 0) * float(lm.get('precio_unitario') or 0) * (1 - (lm.get('descuento_pct') or 0) / 100)
        neto += subtotal
        for nombre in nombres_por_producto.get(pid, []):
            tasa = tasa_por_nombre.get(nombre, 0)
            impuestos_acumulados[nombre] = impuestos_acumulados.get(nombre, 0) + subtotal * tasa / 100

    total = neto + sum(impuestos_acumulados.values())
    neto_dte = _monto(doc.get('amount_untaxed'))
    total_dte = _monto(doc.get('amount_total'))
    return SimularOut(
        neto=round(neto, 2),
        impuestos=[SimularImpuestoOut(nombre=n, monto=round(m, 2)) for n, m in impuestos_acumulados.items()],
        total=round(total, 2),
        lineas_sin_producto=lineas_sin_producto,
        # impuestos_dte = Total - Neto (TODOS los impuestos declarados) --
        # ver el comentario en _verificar_montos.
        neto_dte=neto_dte, impuestos_dte=round(total_dte - neto_dte, 2), total_dte=total_dte,
    )


@router.get("/{dte_id}", response_model=DteDetalleOut)
def detalle(dte_id: int, claims: dict = Depends(get_current_claims),
            odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Detalle de un DTE con sus lineas. Cuando el codigo de una linea ya
    tiene un mapeo aprendido (facturas_producto_mapa), se AUTOCONFIRMA
    solo -- se escribe el product_id directo en Odoo, sin pedir el clic
    manual de "Confirmar" (ya se sabe que es el producto correcto, se
    aprendio la primera vez que alguien lo confirmo a mano). Si la
    escritura falla por lo que sea, no se cae toda la pantalla -- la
    linea vuelve a quedar como sugerencia pendiente del clic manual
    (fallback, mismo comportamiento de antes). Observador puede abrir esta
    pantalla igual (ve el producto sugerido/conocido en cada linea), pero
    nunca dispara el autoconfirm real (ver mas abajo) -- solo mira, nunca
    cambia nada en Odoo."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date', 'invoice_id']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]

    lineas_raw = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'item_name', 'qty', 'item_price', 'product_id', 'code_ids']})

    code_ids = [c for l in lineas_raw for c in l.get('code_ids', [])]
    codigos_por_id = {}
    if code_ids:
        codigos = cliente._call('l10n_cl.supplier.xml.item.code', 'search_read',
            [[['id', 'in', code_ids]]], {'fields': ['code_type', 'code_value']})
        codigos_por_id = {c['id']: c for c in codigos}

    db = get_db()
    mapeos = db.table("facturas_producto_mapa").select("*").eq("proveedor_rut", doc.get("issuer_rut") or "").execute().data or []
    mapa = {(m["codigo_tipo"], m["codigo_valor"]): m for m in mapeos}
    linea_ids = [l['id'] for l in lineas_raw]
    descuentos = db.table("facturas_dte_linea_descuento").select("dte_linea_id,descuento_pct") \
        .in_("dte_linea_id", linea_ids).execute().data or [] if linea_ids else []
    descuento_por_linea = {d["dte_linea_id"]: d["descuento_pct"] for d in descuentos}

    recibidos = db.table("facturas_dte_linea_recibido").select("dte_linea_id,cantidad_recibida") \
        .in_("dte_linea_id", linea_ids).execute().data or [] if linea_ids else []
    recibido_por_linea = {r["dte_linea_id"]: r["cantidad_recibida"] for r in recibidos}

    # Historial de descuento por producto para ESTE proveedor puntual -- una
    # sola consulta (ordenada por mas reciente), se toma la primera
    # ocurrencia por producto en Python. Se usa para PRE-COMPLETAR (y dejar
    # guardado de una vez) el descuento de cualquier linea que todavia no
    # se confirmo para ESTA factura -- pedido explicito del usuario: que el
    # ultimo % usado para ese producto con ese proveedor salga solo, no
    # solo como referencia. Sigue editable, y el chequeo de montos contra
    # el DTE real (_verificar_montos) sigue siendo la red de seguridad si
    # el valor copiado no calza en esta factura puntual.
    historial_descuento_por_producto: dict[int, float] = {}
    if doc.get("issuer_rut"):
        filas_historial = db.table("facturas_dte_linea_descuento").select("odoo_product_id,descuento_pct,actualizado_en") \
            .eq("proveedor_rut", doc["issuer_rut"]).order("actualizado_en", desc=True).execute().data or []
        for f in filas_historial:
            pid = f.get("odoo_product_id")
            if pid is not None and pid not in historial_descuento_por_producto:
                historial_descuento_por_producto[pid] = f["descuento_pct"]

    lineas_procesadas = []
    por_producto_autoconfirmar: dict[int, list[int]] = {}
    for l in lineas_raw:
        codigos = [codigos_por_id[c] for c in l.get('code_ids', []) if c in codigos_por_id]
        codigo_tipo, codigo_valor = _mejor_codigo(codigos, l.get('item_name'))
        product_id = l['product_id'][0] if l.get('product_id') else None
        product_name = l['product_id'][1] if l.get('product_id') else None
        if not product_id and codigo_tipo and (codigo_tipo, codigo_valor) in mapa:
            m = mapa[(codigo_tipo, codigo_valor)]
            product_id, product_name = m["odoo_product_id"], m["odoo_product_name"]
            por_producto_autoconfirmar.setdefault(product_id, []).append(l['id'])
        lineas_procesadas.append([l, product_id, product_name, False, codigo_tipo, codigo_valor])

    # Autoconfirmar de a un PRODUCTO (todas sus lineas juntas en un solo
    # write), no de a una linea -- una factura con muchas lineas nuevas
    # significa muchos productos repetidos entre lineas, asi que agrupar
    # ahorra la mayoria de las idas y vueltas a Odoo. Si el write de un
    # grupo falla, esas lineas vuelven a quedar pendientes del clic manual
    # (mismo respaldo de antes, solo que ahora el radio de una falla
    # puntual es el grupo entero en vez de una sola linea).
    #
    # Solo un administrador dispara el write real -- un observador puede
    # abrir esta pantalla (pidio acceso a ver TODO), pero nunca debe cambiar
    # nada en Odoo con solo mirar. El product_id/product_name ya quedo
    # resuelto arriba para mostrarlo igual en pantalla.
    lineas_fallidas = set()
    for product_id, line_ids in (por_producto_autoconfirmar.items() if claims["rol"] == "administrador" else []):
        try:
            cliente._call('l10n_cl.supplier.xml.line', 'write', [line_ids, {'product_id': product_id}])
        except Exception:
            lineas_fallidas.update(line_ids)
    for fila in lineas_procesadas:
        if fila[0]['id'] in lineas_fallidas:
            fila[3] = True  # sugerido

    lineas_manuales = db.table("facturas_dte_linea_manual").select("*").eq("dte_id", dte_id).order("id").execute().data or []

    # Impuestos ACTUALES por producto -- resuelto batcheado para todos los
    # productos de la factura de una vez (ver _impuestos_actuales_por_producto).
    # Pedido explicito del usuario: que se vean directo en la fila de cada
    # linea, sin tener que abrir nada para saber que impuesto tiene aplicado hoy.
    product_ids_impuestos = list({pid for _, pid, *_ in lineas_procesadas if pid}
                                  | {lm['odoo_product_id'] for lm in lineas_manuales})
    nombres_por_producto = _impuestos_actuales_por_producto(cliente, db, product_ids_impuestos)

    lineas: list[DteLineaOut] = []
    for l, product_id, product_name, sugerido, codigo_tipo, codigo_valor in lineas_procesadas:
        descuento_pct = descuento_por_linea.get(l['id'])
        descuento_sugerido = False
        if descuento_pct is None and product_id in historial_descuento_por_producto:
            descuento_pct = historial_descuento_por_producto[product_id]
            descuento_sugerido = True
            # Igual que el autoconfirm de mas arriba: un observador puede
            # abrir esta pantalla y ver el descuento sugerido, pero nunca
            # debe dejar un write real solo por mirar.
            if claims["rol"] == "administrador":
                db.table("facturas_dte_linea_descuento").upsert({
                    "dte_linea_id": l['id'], "descuento_pct": descuento_pct,
                    "proveedor_rut": doc.get("issuer_rut") or "", "odoo_product_id": product_id,
                    "actualizado_en": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="dte_linea_id").execute()

        factor_conversion = (mapa[(codigo_tipo, codigo_valor)].get('factor_conversion') or 1) \
            if codigo_tipo and (codigo_tipo, codigo_valor) in mapa else 1

        lineas.append(DteLineaOut(
            id=l['id'], item_name=l.get('item_name') or '', qty=l.get('qty') or 0,
            item_price=float(l.get('item_price') or 0),
            codigo_tipo=codigo_tipo, codigo_valor=codigo_valor,
            product_id=product_id, product_name=product_name, sugerido=sugerido,
            descuento_pct=descuento_pct or 0, descuento_sugerido=descuento_sugerido,
            impuesto_nombres=nombres_por_producto.get(product_id, []) if product_id else [],
            factor_conversion=factor_conversion,
            cantidad_recibida=recibido_por_linea.get(l['id'], l.get('qty') or 0),
        ))

    # Lineas agregadas a mano (facturas_dte_linea_manual) -- id NEGATIVO a
    # proposito: los id reales de l10n_cl.supplier.xml.line son siempre
    # positivos, asi que no hay riesgo de que el id de una linea manual
    # choque con el de una linea real del DTE en el mismo detalle (el
    # frontend usa l.id como key de fila/selector -- una colision mezclaria
    # botones/filas de dos lineas distintas).
    for lm in lineas_manuales:
        lineas.append(DteLineaOut(
            id=-lm['id'], item_name=lm['odoo_product_name'], qty=lm['qty'], item_price=float(lm['precio_unitario']),
            codigo_tipo=None, codigo_valor=None,
            product_id=lm['odoo_product_id'], product_name=lm['odoo_product_name'], sugerido=False,
            descuento_pct=lm.get('descuento_pct') or 0, es_manual=True,
            impuesto_nombres=nombres_por_producto.get(lm['odoo_product_id'], []),
            cantidad_recibida=lm['qty'],
        ))

    return DteDetalleOut(
        id=doc['id'], proveedor_rut=doc.get('issuer_rut') or '', proveedor_nombre=doc.get('issuer_name') or '',
        folio=doc.get('l10n_latam_document_number') or '', fecha=doc.get('date'),
        tiene_factura=bool(doc.get('invoice_id')), lineas=lineas,
    )


@router.get("/{dte_id}/nota-credito", response_model=DteNotaCreditoDetalleOut)
def detalle_nota_credito(dte_id: int, claims: dict = Depends(get_current_claims),
                          odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Detalle de SOLO LECTURA de una Nota de Credito -- a diferencia de
    detalle() (para facturas), esta NUNCA escribe nada en Odoo ni en
    Supabase: sin autoconfirmar productos, sin precompletar descuentos, sin
    tocar facturas_producto_mapa. Las NC son solo visualizacion por ahora
    (ver listar_pendientes) -- este endpoint existe para que se pueda ver
    QUE contiene la NC (items, cantidad, precio) tal como viene en el DTE,
    sin depender de que este matcheada a un producto de Odoo."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
        {'fields': ['id', 'issuer_rut', 'issuer_name', 'l10n_latam_document_number', 'date', 'amount_total',
                    'l10n_latam_document_type_id_code']})
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DTE no encontrado")
    doc = docs[0]
    if doc.get('l10n_latam_document_type_id_code') != '61':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este documento no es una Nota de Crédito")

    lineas_raw = cliente._call('l10n_cl.supplier.xml.line', 'search_read', [[['invoice_id', '=', dte_id]]],
        {'fields': ['id', 'item_name', 'qty', 'item_price']})

    return DteNotaCreditoDetalleOut(
        id=doc['id'], proveedor_rut=doc.get('issuer_rut') or '', proveedor_nombre=doc.get('issuer_name') or '',
        folio=doc.get('l10n_latam_document_number') or '', fecha=doc.get('date'),
        monto_total=_monto(doc.get('amount_total')), es_nota_credito=True,
        lineas=[DteLineaSimpleOut(
            id=l['id'], item_name=l.get('item_name') or '', qty=l.get('qty') or 0,
            item_price=float(l.get('item_price') or 0),
        ) for l in lineas_raw],
    )


@router.post("/lineas/match", status_code=status.HTTP_204_NO_CONTENT)
def confirmar_match(body: DteMatchLineaIn, claims: dict = Depends(get_current_claims),
                     odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Un admin confirma que una linea del DTE corresponde a un producto ya
    existente en Odoo: escribe el product_id en la linea (unico cambio que
    se hace en Odoo aca) y guarda el mapeo para que la proxima factura del
    mismo proveedor con el mismo codigo se sugiera sola."""
    _require_admin(claims)
    cliente = _odoo(odoo_creds)
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


def _normalizar_folio(valor) -> str:
    """El folio del DTE viene sin rellenar (ej. "10199"), pero Odoo guarda
    l10n_latam_document_number con ceros a la izquierda hasta 6 digitos
    (ej. "010199", el mismo zfill(6) que usa _ejecutar_creacion al crear la
    factura) -- comparar como texto exacto nunca calza salvo que el folio
    tenga exactamente 6 digitos. Confirmado con un caso real (Doña Sofía,
    folio 10199 vs "010199": el chequeo de duplicados y el vinculado de
    "Ingresada Manualmente" nunca encontraban la factura real que sí
    existía). Se comparan como numero -- los folios chilenos son siempre
    numericos."""
    texto = str(valor or '').strip()
    if not texto:
        return ''
    try:
        return str(int(texto))
    except ValueError:
        return texto


def _impuestos_actuales_por_producto(cliente: OdooClient, db, product_ids: list[int]) -> dict[int, list[str]]:
    """Impuestos que aplican HOY a cada producto: el override guardado en
    facturas_producto_impuesto si existe, si no el default que el producto
    ya tiene en Odoo (supplier_taxes_id) -- mismo fallback de dos niveles
    usado por simular() y detalle(), resuelto batcheado (una consulta a
    Supabase + como maximo dos a Odoo) para cualquier cantidad de
    productos, nunca N+1."""
    nombres_por_producto: dict[int, list[str]] = {}
    if not product_ids:
        return nombres_por_producto
    filas_impuestos = db.table("facturas_producto_impuesto").select("odoo_product_id,impuesto_nombre") \
        .in_("odoo_product_id", product_ids).execute().data or []
    for f in filas_impuestos:
        lista = nombres_por_producto.setdefault(f["odoo_product_id"], [])
        if f["impuesto_nombre"] not in lista:
            lista.append(f["impuesto_nombre"])
    sin_override = [pid for pid in product_ids if pid not in nombres_por_producto]
    if sin_override:
        productos_tax = cliente._call('product.product', 'read', [sin_override], {'fields': ['supplier_taxes_id']})
        tax_ids_defecto = list({t for p in productos_tax for t in (p.get('supplier_taxes_id') or [])})
        nombre_por_tax_id: dict[int, str] = {}
        if tax_ids_defecto:
            taxes = cliente._call('account.tax', 'read', [tax_ids_defecto], {'fields': ['name']})
            nombre_por_tax_id = {t['id']: t['name'] for t in taxes}
        for p in productos_tax:
            # supplier_taxes_id puede traer varios tax_id DISTINTOS que
            # resuelven al MISMO nombre -- caso real confirmado: un producto
            # compartido entre empresas quedo vinculado al impuesto "IVA 19%
            # Compra" de 8 empresas distintas (8 registros account.tax con
            # ids distintos, mismo nombre), inflando el IVA calculado 8x
            # (Alca Spa / Doña Estela, folio 401229: $254.387 calculado vs
            # $31.798 real). El nombre es lo que importa para el calculo
            # (se resuelve la tasa POR NOMBRE dentro de la empresa correcta
            # en simular()/_ejecutar_creacion), asi que se dedupea por
            # nombre resuelto, no por id crudo.
            nombres = []
            for t in (p.get('supplier_taxes_id') or []):
                nombre = nombre_por_tax_id.get(t)
                if nombre and nombre not in nombres:
                    nombres.append(nombre)
            nombres_por_producto[p['id']] = nombres
    return nombres_por_producto


def _verificar_montos(doc: dict, odoo_datos: dict) -> list[str]:
    """Compara Neto/Impuestos/Total del DTE contra los mismos montos ya
    calculados en Odoo (la OC en borrador, antes de confirmar nada) -- deben
    coincidir o tener maximo TOLERANCIA_MONTOS pesos de diferencia
    (redondeos). Devuelve la lista de desajustes encontrados (vacia si todo
    calza).

    Ojo: el campo 'iva' del DTE trae SOLO el IVA (19%) -- si el proveedor
    declara ademas otro impuesto (ej. ILA 31.5% en bebidas alcoholicas), ese
    monto no queda incluido ahi. odoo_datos['amount_tax'], en cambio, es la
    suma de TODOS los impuestos de la orden. Comparar 'iva' contra
    'amount_tax' directo marcaba diferencia SIEMPRE que hubiera un impuesto
    adicional real y bien configurado (confirmado con un caso real: ILA
    31.5%, $26.234 de "diferencia" que en realidad era el ILA, no un error).
    Por eso el lado del DTE se calcula como Total - Neto (todos los
    impuestos que declara el documento, sin importar el tipo), que es la
    base correcta para comparar contra el amount_tax de Odoo."""
    impuestos_dte = _monto(doc.get('amount_total')) - _monto(doc.get('amount_untaxed'))
    comparaciones = (
        ("Neto", doc.get('amount_untaxed'), odoo_datos.get('amount_untaxed')),
        ("Impuestos", impuestos_dte, odoo_datos.get('amount_tax')),
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
        {'fields': ['id', 'supplier_rank', 'name']})
    if not partners:
        raise RuntimeError(f"No encontré el proveedor con RUT {doc['issuer_rut']} en Odoo")
    if len(partners) == 1:
        partner_id = partners[0]['id']
        proveedor_nombre = partners[0]['name']
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
        proveedor_nombre = ranking[0]['name']

    # Verificar que no exista YA una factura real para este mismo documento
    # (mismo proveedor + mismo folio), aunque el DTE nunca haya quedado
    # vinculado a ella -- esto puede pasar si alguien crea la factura por
    # otro camino (a mano en Odoo, u otro proceso de compras) sin pasar por
    # esta pantalla. Encontrado con un caso real: una factura de Alimentos y
    # Frutos S.A. ya existia (creada por otro proceso, nunca vinculada al
    # DTE) y este sistema creo una segunda factura duplicada para el mismo
    # folio antes de tener esta validacion. Aplica a CUALQUIER proveedor,
    # no solo a Doña Sofía.
    # Ojo: 'l10n_latam_document_number' no se puede filtrar de forma
    # confiable en el dominio de busqueda de Odoo -- se ignora en silencio
    # y devuelve TODAS las facturas del proveedor (confirmado con un caso
    # real: CCU, filtrando por folio "179225651" devolvio 40 facturas con
    # folios completamente distintos). Por eso se trae el universo acotado
    # (proveedor + tipo factura + no cancelada) y se compara el folio en
    # Python, igual que ya se hizo en el escaneo de duplicados anterior.
    folio = _normalizar_folio(doc.get('l10n_latam_document_number'))
    if folio:
        facturas_proveedor = cliente._call('account.move', 'search_read',
            [[['partner_id', '=', partner_id], ['company_id', '=', company_id],
              ['move_type', '=', 'in_invoice'], ['state', '!=', 'cancel']]],
            {'fields': ['id', 'name', 'amount_total', 'l10n_latam_document_number']})
        ya_facturada = [m for m in facturas_proveedor if _normalizar_folio(m.get('l10n_latam_document_number')) == folio]
        if ya_facturada:
            nombres = ', '.join(m['name'] for m in ya_facturada)
            raise RuntimeError(
                f"Ya existe una factura en Odoo para este folio ({nombres}) aunque el DTE no estaba vinculado "
                f"a ella -- no se creó nada nuevo. Si es la factura correcta, usa el botón \"Ingresada "
                f"Manualmente\" en la lista de pendientes para vincularla (no \"Limpiar\" acá, eso solo saca "
                f"esta fila de la vista, no vincula nada); si no, revisar con contabilidad"
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

    db = get_db()

    # Lineas agregadas a mano (facturas_dte_linea_manual, ver detalle()) --
    # se suman a las lineas reales del DTE para armar la OC. No soportado
    # para Doña Sofía: esa rama REUSA una OC ya confirmada de antes (ver
    # _buscar_oc_sofia) y solo actualiza precio/descuento de sus lineas
    # existentes -- no hay forma de agregarle una linea nueva por este
    # camino sin escribir codigo aparte, asi que mejor fallar claro que
    # ignorar en silencio una linea que el admin agrego a proposito.
    lineas_manuales = db.table("facturas_dte_linea_manual").select("*").eq("dte_id", dte_id).execute().data or []
    if lineas_manuales and doc['issuer_rut'] == RUT_DONA_SOFIA:
        raise RuntimeError(
            "Doña Sofía: las líneas agregadas a mano no están soportadas para este proveedor -- "
            "se reusa una Orden de Compra ya existente y no se le pueden agregar productos nuevos por acá"
        )

    product_ids = list({l['product_id'][0] for l in lineas} | {lm['odoo_product_id'] for lm in lineas_manuales})
    productos = cliente._call('product.product', 'read', [product_ids], {'fields': ['uom_id', 'display_name']})
    info_por_producto = {p['id']: p for p in productos}

    # Impuestos guardados por producto (tabla facturas_producto_impuesto,
    # hasta 3 por producto) -- si un producto no tiene fila aca, Odoo usa el
    # impuesto que ya tenga configurado por defecto (el caso normal). Los
    # impuestos son por EMPRESA en Odoo, asi que se guarda el NOMBRE y se
    # resuelve al id real de la empresa de este DTE recien aca.
    filas_impuestos = db.table("facturas_producto_impuesto").select("odoo_product_id,impuesto_nombre") \
        .in_("odoo_product_id", product_ids).execute().data or []
    nombres_por_producto: dict[int, list[str]] = {}
    for f in filas_impuestos:
        lista = nombres_por_producto.setdefault(f["odoo_product_id"], [])
        if f["impuesto_nombre"] not in lista:
            lista.append(f["impuesto_nombre"])

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

    # % de descuento POR LINEA -- confirmado a mano por el admin desde la
    # pantalla (facturas_dte_linea_descuento). El descuento real varia linea
    # por linea (confirmado con OC reales de CCU/Andina: distintos % en la
    # misma factura) -- no es un valor parejo para toda la factura. El DTE
    # nunca trae el descuento poblado por linea, asi que el default es 0
    # (sin descuento) para cualquier linea que no se haya tocado a mano.
    #
    # El precio unitario de la linea queda SIEMPRE en su valor de lista (sin
    # descontar) -- el % va en el campo real de Odoo (purchase.order.line.discount,
    # "Discount (%)"), igual que cuando se completa la OC a mano (mismo
    # patron real: price_subtotal = qty * price_unit * (1 - discount/100)).
    # Pedido explicito del usuario -- si el precio unitario quedara ya
    # descontado, el seguimiento de precio del producto a futuro quedaria
    # adulterado.
    linea_ids = [l['id'] for l in lineas]
    filas_descuento = db.table("facturas_dte_linea_descuento").select("dte_linea_id,descuento_pct") \
        .in_("dte_linea_id", linea_ids).execute().data or []
    descuento_por_linea = {f["dte_linea_id"]: f["descuento_pct"] for f in filas_descuento}

    # Cantidad REAL recibida por linea -- cuando difiere de lo facturado
    # (factura mal despachada), esto es lo que se le acredita al Stock de
    # Bodega interno. La OC/factura real en Odoo (order_lines, mas abajo)
    # SIEMPRE usa lo facturado -- nunca se toca, es el documento contable/SII.
    # Se arma en paralelo a order_lines (cantidades_bodega, mismo orden) y
    # solo se usa mas abajo, dentro de _alimentar_stock_bodega.
    filas_recibido = db.table("facturas_dte_linea_recibido").select("dte_linea_id,cantidad_recibida") \
        .in_("dte_linea_id", linea_ids).execute().data or []
    recibido_por_linea = {f["dte_linea_id"]: f["cantidad_recibida"] for f in filas_recibido}

    fecha_dte = f"{doc['date']} 12:00:00"
    order_lines = []
    cantidades_bodega = []
    for l in lineas:
        pid = l['product_id'][0]
        prod = info_por_producto[pid]
        factor_conversion = _factor_de_linea(l)
        precio_real = (float(l.get('item_price') or 0) / factor_conversion) if factor_conversion else float(l.get('item_price') or 0)
        product_qty = (l.get('qty') or 0) * factor_conversion
        linea_oc = {
            'product_id': pid,
            'name': prod['display_name'],
            'product_qty': product_qty,
            'price_unit': round(precio_real, 2),
            'discount': descuento_por_linea.get(l['id'], 0),
            'product_uom': prod['uom_id'][0] if prod.get('uom_id') else False,
        }
        nombres_impuestos = nombres_por_producto.get(pid)
        if nombres_impuestos:
            linea_oc['taxes_id'] = [(6, 0, [tax_id_por_nombre[n] for n in nombres_impuestos])]
        order_lines.append((0, 0, linea_oc))
        recibido = recibido_por_linea.get(l['id'])
        cantidades_bodega.append(recibido * factor_conversion if recibido is not None else product_qty)

    # Lineas agregadas a mano -- mismo armado que las reales del DTE, sin
    # factor de conversion (no tienen codigo de proveedor asociado). No
    # tienen "cantidad recibida" propia -- lo que se tipeo a mano ya es lo
    # que se quiere acreditar.
    for lm in lineas_manuales:
        pid = lm['odoo_product_id']
        prod = info_por_producto[pid]
        linea_oc = {
            'product_id': pid,
            'name': prod['display_name'],
            'product_qty': lm['qty'],
            'price_unit': round(float(lm['precio_unitario']), 2),
            'discount': lm.get('descuento_pct') or 0,
            'product_uom': prod['uom_id'][0] if prod.get('uom_id') else False,
        }
        nombres_impuestos = nombres_por_producto.get(pid)
        if nombres_impuestos:
            linea_oc['taxes_id'] = [(6, 0, [tax_id_por_nombre[n] for n in nombres_impuestos])]
        order_lines.append((0, 0, linea_oc))
        cantidades_bodega.append(lm['qty'])

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
            [[['order_id', '=', oc_id]]], {'fields': ['product_id', 'price_unit', 'product_qty', 'discount']})
        linea_id_por_producto = {l['product_id'][0]: l['id'] for l in lineas_oc_actuales if l.get('product_id')}
        valores_originales = {l['id']: {'price_unit': l['price_unit'], 'product_qty': l['product_qty'], 'discount': l['discount']}
                               for l in lineas_oc_actuales}

        # Se actualiza el PRECIO (de lista, sin descontar) y el % de
        # DESCUENTO de toda linea -- pedido explícito del usuario ("los
        # precios que mandan son los de la factura, no los de la OC"). La
        # CANTIDAD de la OC solo se toca para los dos productos con peso
        # variable real (PRODUCTOS_PESO_VARIABLE_SOFIA) -- para cualquier
        # otro producto, si la cantidad no calza es un desajuste real que
        # debe revisarse a mano, no ajustarse solo.
        for _, _, linea_oc in order_lines:
            pid = linea_oc['product_id']
            linea_id = linea_id_por_producto.get(pid)
            if not linea_id:
                continue
            valores = {'price_unit': linea_oc['price_unit'], 'discount': linea_oc['discount']}
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
            fallos_revert = []
            for linea_id, valores in valores_originales.items():
                try:
                    cliente._call('purchase.order.line', 'write', [[linea_id], valores])
                except Exception:
                    fallos_revert.append(linea_id)
            detalle_revert = (
                "se revirtió todo lo que se acababa de escribir, no se tocó nada más" if not fallos_revert
                else f"OJO -- no se pudo revertir la línea {fallos_revert} de vuelta a su valor original, "
                     f"esa Orden de Compra puede haber quedado con datos mezclados, revisar a mano en Odoo"
            )
            raise RuntimeError(
                f"No coinciden los valores con la Orden de Compra {oc_name} de Doña Sofía -- {detalle_revert}: "
                + "; ".join(desajustes)
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

    # La factura ya quedo creada en Odoo (lo que importa) -- alimentar el
    # stock de Bodega es un extra que nunca debe hacer fallar la creacion.
    uom_nombre_por_producto = {pid: p['uom_id'][1] for pid, p in info_por_producto.items() if p.get('uom_id')}
    try:
        _alimentar_stock_bodega(db, cliente, company_id, dte_id, move_id, move['name'], proveedor_nombre,
                                 doc['issuer_rut'], partner_id, uom_nombre_por_producto, order_lines, cantidades_bodega)
    except Exception:
        pass

    return move_id, move['name']


def _alimentar_stock_bodega(db, cliente, company_id: int, dte_id: int, move_id: int, invoice_name: str,
                             proveedor_nombre: str, proveedor_rut: str, odoo_partner_id: int,
                             uom_nombre_por_producto: dict[int, str], order_lines: list,
                             cantidades_bodega: list[float]) -> None:
    """Wrapper de _creditar_stock_bodega para el flujo de creacion automatica
    de factura (_ejecutar_creacion) -- arma `lineas` a partir de order_lines
    (formato Odoo (0,0,dict), solo tiene sentido para ese flujo) + la lista
    paralela de cantidades corregidas por "Cantidad recibida" en Revisar.
    Ver _creditar_stock_bodega para el resto del comportamiento."""
    lineas = [
        {'product_id': linea_oc['product_id'], 'name': linea_oc['name'], 'price_unit': linea_oc.get('price_unit'),
         'product_uom': linea_oc.get('product_uom'), 'cantidad_facturada': linea_oc['product_qty'],
         'cantidad_bodega': cantidad_bodega}
        for (_, _, linea_oc), cantidad_bodega in zip(order_lines, cantidades_bodega)
    ]
    _creditar_stock_bodega(db, cliente, company_id, dte_id, move_id, invoice_name, proveedor_nombre,
                            proveedor_rut, odoo_partner_id, uom_nombre_por_producto, lineas, origen="factura_odoo")


def _creditar_stock_bodega(db, cliente, company_id: int, dte_id: int, move_id: int, invoice_name: str,
                            proveedor_nombre: str, proveedor_rut: str, odoo_partner_id: int,
                            uom_nombre_por_producto: dict[int, str], lineas: list[dict], origen: str) -> None:
    """Suma automaticamente a bodega_movimientos el ingreso de cada linea de
    una factura -- pedido explicito del usuario, para no tener que cargar el
    stock a mano cada vez que se ingresa una factura. Generica: la usan
    tanto _alimentar_stock_bodega (factura creada por este sistema, ver
    _ejecutar_creacion) como cargar_stock_manual (factura creada a mano
    directo en Odoo, vinculada via "Ingresada Manualmente") -- cada una arma
    `lineas` a su manera, pero ambas terminan aca. `origen` distingue el
    rastro en bodega_movimientos ('factura_odoo' vs 'factura_manual').

    cada `linea` trae 'cantidad_facturada' (lo que declara la factura real)
    y 'cantidad_bodega' (lo que se acredita a Bodega -- igual a la
    facturada salvo que el admin haya corregido "Cantidad recibida" por una
    factura mal despachada). El historial de precios siempre usa
    'cantidad_facturada' a proposito -- ese historial es de PRECIOS, no de
    cantidad fisica.

    Si el local (por la empresa de Odoo) o el insumo (por el producto de
    Odoo, via odoo_mapping) todavia no se pueden resolver, la linea queda
    en bodega_stock_pendiente en vez de sumarse -- se resuelve despues con
    el boton "Actualizar" en Inventario (si solo faltaba el local) o con
    "Vincular" (si faltaba el insumo -- ver inventario.py::vincular_pendiente,
    que usa proveedor_rut/odoo_partner_id/precio/uom para no tener que
    retipear a mano lo que la factura ya trajo). Tambien se guarda
    unidad_sugerida ("kg"/"un"), resuelta contra los ids estandar de Odoo
    (product_uom_kgm/product_uom_unit, mismo patron que pedidos.py::
    _generar_oc_cuerpo) en vez de adivinada por texto -- reduce el modal de
    Vincular a un clic de confirmacion en el caso comun.

    Cuando el insumo SI se resuelve, ademas se guarda el precio real de esa
    linea en historial_precios_compra (base del reporte "Ahorro por Acuerdos
    Comerciales", ver proveedores.py::ahorro_mensual) y se generan dos tipos
    de alerta en alertas_precio_factura (tarjeta "Alertas de precio" en
    Facturas Odoo): 'sobreprecio' si el proveedor de esta factura cobro mas
    caro que SU propio precio_negociado, y 'oportunidad' si CUALQUIER
    proveedor factura mas barato que el mejor precio_negociado vigente entre
    todos los proveedores de ese insumo (para evaluar cambiar de proveedor
    prioritario)."""
    locales = db.table("locales").select("id").eq("odoo_company_id", company_id).execute().data
    local_id = locales[0]["id"] if locales else None

    product_ids = list({linea["product_id"] for linea in lineas})
    mapeos = db.table("odoo_mapping").select("odoo_id,ingrediente_key,proveedor_id,precio_negociado") \
        .in_("odoo_id", product_ids).execute().data or []
    mapeo_por_producto = {m["odoo_id"]: m for m in mapeos}

    # Mejor precio pactado GLOBAL (entre todos los proveedores, no solo el
    # de esta factura) para cada insumo de esta factura -- para la alerta
    # 'oportunidad'. Nunca debe tumbar el resto de la funcion si Odoo/la
    # consulta fallan.
    mejor_por_key: dict[str, tuple[float, str | None]] = {}
    try:
        ingrediente_keys = list({m["ingrediente_key"] for m in mapeos if m.get("ingrediente_key")})
        if ingrediente_keys:
            todos = db.table("odoo_mapping").select("ingrediente_key,precio_negociado,proveedor_id") \
                .in_("ingrediente_key", ingrediente_keys).not_.is_("precio_negociado", "null").execute().data or []
            for t in todos:
                k, p = t["ingrediente_key"], t["precio_negociado"]
                if k not in mejor_por_key or p < mejor_por_key[k][0]:
                    mejor_por_key[k] = (p, t.get("proveedor_id"))
    except Exception:
        pass

    # Ids estandar de Odoo para "Kilogramos"/"Unidades", resueltos una sola
    # vez por factura -- para poder guardar unidad_sugerida sin adivinar por
    # texto. Si esto falla, unidad_sugerida simplemente queda null (el admin
    # la completa a mano, como hoy).
    unidad_por_uom_id: dict[int, str] = {}
    try:
        ids_uom = cliente._call('ir.model.data', 'search_read',
            [[['module', '=', 'uom'], ['name', 'in', ['product_uom_kgm', 'product_uom_unit']]]],
            {'fields': ['name', 'res_id']})
        uom_por_nombre = {u['name']: u['res_id'] for u in ids_uom}
        if uom_por_nombre.get('product_uom_kgm'):
            unidad_por_uom_id[uom_por_nombre['product_uom_kgm']] = 'kg'
        if uom_por_nombre.get('product_uom_unit'):
            unidad_por_uom_id[uom_por_nombre['product_uom_unit']] = 'un'
    except Exception:
        pass

    ahora = datetime.now(timezone.utc).isoformat()
    for linea in lineas:
        pid = linea["product_id"]
        cantidad_bodega = linea["cantidad_bodega"]
        mapeo = mapeo_por_producto.get(pid)
        ingrediente_key = mapeo["ingrediente_key"] if mapeo else None
        if not local_id or not ingrediente_key:
            db.table("bodega_stock_pendiente").insert({
                "dte_id": dte_id, "invoice_id": move_id, "invoice_name": invoice_name,
                "odoo_company_id": company_id, "local_id": local_id, "odoo_product_id": pid,
                "producto_nombre": linea["name"], "cantidad": cantidad_bodega,
                "proveedor_nombre": proveedor_nombre, "motivo": "sin_local" if not local_id else "sin_insumo",
                "proveedor_rut": proveedor_rut, "odoo_partner_id": odoo_partner_id,
                "precio": linea.get("price_unit"), "uom_odoo_id": linea.get("product_uom") or None,
                "uom_odoo_nombre": uom_nombre_por_producto.get(pid),
                "unidad_sugerida": unidad_por_uom_id.get(linea.get("product_uom")),
            }).execute()
            continue
        db.table("bodega_movimientos").insert({
            "local_id": local_id, "ingrediente_key": ingrediente_key, "tipo": "ingreso",
            "cantidad": cantidad_bodega, "origen": origen, "ref": invoice_name,
            "nota": f"Factura Odoo {invoice_name} ({proveedor_nombre})", "fecha": ahora,
        }).execute()

        # El stock (arriba) ya quedo sumado -- eso es lo que importa. El
        # historial de precios y las alertas son un extra que, igual que el
        # resto de esta funcion, nunca debe hacer fallar el procesamiento
        # de las lineas SIGUIENTES de la factura (antes de este try/except
        # un fallo aca cortaba el loop entero, dejando esas lineas sin
        # sumar stock ni quedar pendientes -- se perdian sin rastro).
        try:
            precio_real = linea.get("price_unit")
            db.table("historial_precios_compra").insert({
                "ingrediente_key": ingrediente_key, "proveedor_id": mapeo.get("proveedor_id"),
                "precio": precio_real, "cantidad": linea["cantidad_facturada"],
                "invoice_name": invoice_name, "dte_id": dte_id, "fecha": ahora,
            }).execute()

            precio_negociado = mapeo.get("precio_negociado")
            if precio_negociado is not None and precio_real is not None and precio_real > precio_negociado:
                db.table("alertas_precio_factura").insert({
                    "dte_id": dte_id, "invoice_name": invoice_name, "ingrediente_key": ingrediente_key,
                    "proveedor_id": mapeo.get("proveedor_id"), "precio_real": precio_real,
                    "precio_negociado": precio_negociado, "fecha": ahora, "tipo": "sobreprecio",
                }).execute()

            mejor = mejor_por_key.get(ingrediente_key)
            if (mejor is not None and precio_real is not None and precio_real < mejor[0]
                    and mapeo.get("proveedor_id") != mejor[1]):
                db.table("alertas_precio_factura").insert({
                    "dte_id": dte_id, "invoice_name": invoice_name, "ingrediente_key": ingrediente_key,
                    "proveedor_id": mapeo.get("proveedor_id"), "precio_real": precio_real,
                    "precio_negociado": mejor[0], "fecha": ahora, "tipo": "oportunidad",
                }).execute()
        except Exception:
            pass


def _procesar_item_cola(cola_id: str, dte_id: int, odoo_creds: tuple[str, str]):
    """Corre en un hilo aparte (FastAPI BackgroundTasks) -- no bloquea al
    resto del servidor mientras Odoo procesa la OC/recepcion/factura.
    odoo_creds viaja como argumento de funcion (nunca a disco/Supabase) --
    se captura en crear_factura, que si tiene la request activa para leer
    los headers, antes de encolar."""
    db = get_db()
    db.table("facturas_dte_cola").update({"estado": "procesando"}).eq("id", cola_id).execute()
    try:
        cliente = _odoo_sin_http(odoo_creds)
        docs = cliente._call('l10n_cl.supplier.xml', 'search_read', [[['id', '=', dte_id]]],
            {'fields': ['id', 'issuer_rut', 'date', 'invoice_id', 'company_id', 'l10n_latam_document_number',
                        'amount_untaxed', 'amount_total']})
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


def _odoo_sin_http(odoo_creds: tuple[str, str]) -> OdooClient:
    """Igual que _odoo() pero sin HTTPException -- para usar desde el hilo
    en segundo plano, donde no hay una request activa a la que responder."""
    usuario, password = odoo_creds
    cliente = OdooClient(os.environ["ODOO_URL"], os.environ["ODOO_DB"], usuario, password)
    ok, msg = cliente.connect()
    if not ok:
        raise RuntimeError(f"No se pudo conectar a Odoo: {msg}")
    return cliente


@router.post("/{dte_id}/crear-factura", response_model=ColaFacturaOut, status_code=status.HTTP_202_ACCEPTED)
def crear_factura(dte_id: int, background_tasks: BackgroundTasks, claims: dict = Depends(get_current_claims),
                   odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Valida rapido (lecturas nomas) y encola la creacion real -- crear la
    factura implica 6 llamadas seguidas a Odoo (OC, confirmar, recibir,
    facturar, fijar fecha, fijar folio) y puede demorar varios segundos.
    Encolar en vez de bloquear permite seguir revisando/confirmando otros
    DTE mientras este se procesa en segundo plano (ver _procesar_item_cola)."""
    _require_admin(claims)
    cliente = _odoo(odoo_creds)

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

    background_tasks.add_task(_procesar_item_cola, fila["id"], dte_id, odoo_creds)
    return ColaFacturaOut(**fila)


TIMEOUT_COLA_PROCESANDO_MINUTOS = 5


@router.get("/cola/estado", response_model=list[ColaFacturaOut])
def listar_cola(claims: dict = Depends(get_current_claims)):
    """Ultimos items de la cola de creacion -- para el panel que muestra el
    progreso mientras se sigue trabajando en otros DTE.

    Antes de listar, cualquier item que lleve "procesando" mas de
    TIMEOUT_COLA_PROCESANDO_MINUTOS se marca como error -- el estado
    "procesando" se fija ANTES de hacer ninguna llamada a Odoo
    (_procesar_item_cola), asi que si el servidor se reinicia a mitad de
    camino (un deploy, o que Render lo duerma/reinicie en plan Free), el
    hilo en segundo plano se pierde para siempre y esa fila queda huerfana
    "procesando" sin que nada la vuelva a tocar. Procesar una factura real
    tarda segundos, nunca minutos, asi que este timeout no deberia
    disparar nunca en un caso normal. Reintentar despues es seguro: el
    chequeo anti-duplicados de _ejecutar_creacion detecta si algo ya
    alcanzo a crearse en Odoo antes del corte, en vez de duplicarlo."""
    _require_lectura(claims)
    db = get_db()
    limite = (datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_COLA_PROCESANDO_MINUTOS)).isoformat()
    db.table("facturas_dte_cola").update({
        "estado": "error",
        "error_mensaje": "Se interrumpió mientras se creaba (probablemente un reinicio del servidor) -- "
                          "puedes reintentar: si algo ya se alcanzó a crear en Odoo, el reintento lo va a "
                          "detectar y avisar en vez de duplicarlo.",
    }).eq("estado", "procesando").lt("creado_en", limite).execute()
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
