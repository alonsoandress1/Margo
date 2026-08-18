"""Planilla de Compras -- replica del Excel "PLANILLA DE COMPRAS OFICIAL
2026": ledger mensual de las facturas de proveedor ya ingresadas en Odoo,
con una categoria (Tipo) POR PROVEEDOR que solo vive en nuestra base --
nunca se escribe en Odoo, se asigna una vez y se reusa siempre.

Tipos: AL=Alimentos, BA=Barra, GF=Gastos Fijos, OT=Otros, AS=Aseo.

Escanea TODAS las empresas de Odoo que tengan un local mapeado
(locales.odoo_company_id) -- no una empresa fija -- para no quedar ciega
en silencio el dia que se agregue un local nuevo (ver _company_ids_locales)."""
import os
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from postgrest.exceptions import APIError

from ..db import get_db
from ..deps import get_current_claims, get_odoo_credentials
from ..excel_exporter_compras import exportar_mes

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooClient  # noqa: E402
from tcpos_connector import TcposWebReportSession, construir_parametros  # noqa: E402

from ..schemas import (PlanillaComprasItem, PlanillaComprasOut, PlanillaComprasResumen, PlanillaFaltanteOut,
                       ProveedorTipoIn, ProveedorTipoOut, VentaPeriodoIn, VentaPeriodoJobOut)
from ..tcpos_report_parser import parsear_financial_overview_cash_to_deposit

_MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
             "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

router = APIRouter(prefix="/planilla-compras", tags=["planilla-compras"])

TIPOS_VALIDOS = {"AL", "BA", "GF", "OT", "AS"}
TIPOS_COSTO_VENTA = {"AL", "BA"}  # igual que el Excel real: Costo Venta = N6+O6 (solo Alimentos + Barra)

# Reporte "Financial overview" de TCPOS -- confirmados via el endpoint de
# descubrimiento (ya borrado). Mismo outlet que el import diario de ventas
# (planilla.py) -- "1001 Margo Isidora" == Doña Delfina en este sistema.
_TCPOS_REPORT_FORM_NAME = "FinancialOverview1Form"
_TCPOS_REPORT_ASSEMBLY_NAME = "Report.FinancialOverview1"
_TCPOS_OUTLET_ID_MARGO_ISIDORA = 13


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede ver la Planilla de Compras")


def _require_lectura(claims: dict):
    """Observador puede ver todo (pedido explicito del usuario), nunca
    cambiar nada -- se usa solo en los endpoints puramente de lectura."""
    if claims["rol"] not in ("administrador", "observador"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a la Planilla de Compras")


def _odoo(odoo_creds: tuple[str, str]) -> OdooClient:
    """Conecta con las credenciales de Odoo de la persona que esta usando el
    sistema en este momento -- nunca una cuenta compartida (ver
    get_odoo_credentials en deps.py)."""
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


def _company_ids_locales(db) -> list[int]:
    """Empresas de Odoo de TODOS los locales mapeados (locales.odoo_company_id)
    -- se resuelve en vivo en vez de una empresa fija, para que un local
    nuevo aparezca solo en Planilla de Compras sin tener que tocar codigo."""
    rows = db.table("locales").select("odoo_company_id").execute().data or []
    return list({r["odoo_company_id"] for r in rows if r.get("odoo_company_id")})


def _obtener_items_y_resumen(anio: int, mes: int, odoo_creds: tuple[str, str]) -> PlanillaComprasOut:
    cliente = _odoo(odoo_creds)
    ultimo_dia = monthrange(anio, mes)[1]
    desde = f"{anio:04d}-{mes:02d}-01"
    hasta = f"{anio:04d}-{mes:02d}-{ultimo_dia:02d}"

    db = get_db()
    company_ids = _company_ids_locales(db)
    if not company_ids:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Ningún local tiene odoo_company_id configurado -- no hay ninguna empresa que escanear")

    # invoice_origin != False -- solo facturas que vienen de una Orden de
    # Compra (el flujo OC -> recepcion -> factura). Sin eso, "Facturas de
    # proveedores" tambien trae bancos, seguros, arriendos (inmobiliarias),
    # telefonia, etc. -- gastos administrativos que nunca pasan por una OC
    # y que esta planilla NO debe mostrar (solo compras de mercaderia).
    # EXCEPCION -- planilla_compras_factura_manual: facturas ingresadas a
    # mano directo en Odoo (boton "Ingresada Manualmente" en Facturas SII)
    # que por eso mismo no tienen invoice_origin, pero SI son una compra
    # real y deben aparecer igual (ver marcar_ingresada_manual en
    # facturas_dte.py).
    ids_manual = [f["factura_id"] for f in (db.table("planilla_compras_factura_manual").select("factura_id").execute().data or [])]
    # Dominio de Odoo (notacion Polaca) -- el operador '|' va SUELTO en la
    # lista plana, aplicando a los dos terminos que le siguen; no se puede
    # anidar como un elemento normal o Odoo lo interpreta mal.
    condiciones_base = [['move_type', '=', 'in_invoice'], ['company_id', 'in', company_ids],
                         ['invoice_date', '>=', desde], ['invoice_date', '<=', hasta], ['state', '!=', 'cancel']]
    condiciones_origen = (['|', ['invoice_origin', '!=', False], ['id', 'in', ids_manual]]
                           if ids_manual else [['invoice_origin', '!=', False]])
    moves = cliente._call('account.move', 'search_read',
        [condiciones_base + condiciones_origen],
        {'fields': ['id', 'partner_id', 'l10n_latam_document_number', 'invoice_date', 'amount_untaxed', 'amount_total'],
         'order': 'invoice_date'})
    mapeos = db.table("planilla_compras_proveedor_tipo").select("odoo_partner_id,tipo").execute().data or []
    tipo_por_partner = {m["odoo_partner_id"]: m["tipo"] for m in mapeos}

    items = []
    for m in moves:
        partner_id, partner_nombre = m.get('partner_id') or [None, '']
        subtotal = m.get('amount_untaxed') or 0
        total = m.get('amount_total') or 0
        items.append(PlanillaComprasItem(
            factura_id=m['id'], proveedor_id=partner_id, proveedor_nombre=partner_nombre,
            num_factura=m.get('l10n_latam_document_number') or '', fecha=m.get('invoice_date'),
            subtotal=subtotal, iva=total - subtotal, total=total,
            tipo=tipo_por_partner.get(partner_id),
        ))

    # % Costo Venta -- misma formula del Excel real: Costo Venta = compras
    # Tipo AL+BA del mes (subtotal, sin IVA); Venta Neta = Venta del Periodo
    # (ingresada a mano, igual que en el Excel) / 1.19.
    costo_venta = sum(it.subtotal for it in items if it.tipo in TIPOS_COSTO_VENTA)
    fila_venta = db.table("planilla_compras_venta_periodo").select("venta_periodo") \
        .eq("anio", anio).eq("mes", mes).execute().data
    venta_periodo = fila_venta[0]["venta_periodo"] if fila_venta else None
    venta_neta = venta_periodo / 1.19 if venta_periodo else None
    pct_costo_venta = costo_venta / venta_neta if venta_neta else None

    resumen = PlanillaComprasResumen(
        venta_periodo=venta_periodo, venta_neta=venta_neta,
        costo_venta=costo_venta, pct_costo_venta=pct_costo_venta,
    )
    return PlanillaComprasOut(items=items, resumen=resumen)


@router.get("", response_model=PlanillaComprasOut)
def listar(anio: int, mes: int, claims: dict = Depends(get_current_claims),
           odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Todas las facturas de proveedor del mes en Odoo, de todas las
    empresas con un local mapeado, con el Tipo de cada una resuelto por su
    proveedor -- null si ese proveedor todavia no tiene Tipo asignado (hay
    que clasificarlo en /proveedores)."""
    _require_lectura(claims)
    return _obtener_items_y_resumen(anio, mes, odoo_creds)


@router.get("/exportar")
def exportar(anio: int, mes: int, claims: dict = Depends(get_current_claims),
             odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Genera el Excel real "PLANILLA DE COMPRAS OFICIAL", ya lleno con las
    facturas del mes -- misma plantilla original, con sus formulas intactas.
    Escribe Tipo/Proveedor/N Factura/IVA/Total tal cual vienen de Odoo (sin
    intentar matchear el nombre corto de las columnas de desglose por
    proveedor -- esas quedan en 0 hasta que se ajusten a mano, igual que
    cualquier fila nueva en el Excel real)."""
    _require_lectura(claims)
    if not (1 <= mes <= 12):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mes inválido")
    datos = _obtener_items_y_resumen(anio, mes, odoo_creds)
    contenido = exportar_mes(anio, mes, [it.model_dump() for it in datos.items], datos.resumen.model_dump())
    nombre_mes = _MESES_ES[mes - 1].capitalize()
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Planilla de Compras {nombre_mes} {anio}.xlsx"'},
    )


@router.get("/faltantes", response_model=list[PlanillaFaltanteOut])
def listar_faltantes(anio: int, mes: int, claims: dict = Depends(get_current_claims),
                      odoo_creds: tuple[str, str] = Depends(get_odoo_credentials)):
    """Compara las facturas de Facturas SII que YA tienen una factura real
    creada en Odoo (invoice_id) contra lo que Planilla de Compras muestra
    este mes -- solo para detectar facturas reales que quedan omitidas
    porque no tienen Orden de Compra detras (invoice_origin vacio) y
    todavia no estan en planilla_compras_factura_manual (mismo caso real
    encontrado con Doña Sofía: la factura existia en Odoo pero Planilla la
    excluia por parecer un gasto administrativo). NO agrega nada solo --
    es puramente informativo, cada una se agrega a mano con POST
    /faltantes/{factura_id}/agregar."""
    _require_lectura(claims)
    cliente = _odoo(odoo_creds)
    company_ids = _company_ids_locales(get_db())
    ultimo_dia = monthrange(anio, mes)[1]
    desde = f"{anio:04d}-{mes:02d}-01"
    hasta = f"{anio:04d}-{mes:02d}-{ultimo_dia:02d}"

    ids_en_planilla = {it.factura_id for it in _obtener_items_y_resumen(anio, mes, odoo_creds).items}

    # Acotado por la fecha del DTE (con margen de 15 dias a cada lado, por si
    # difiere un poco de la invoice_date real que usa Planilla) -- sin esto,
    # la busqueda trae CADA DTE con invoice_id de toda la historia del
    # sistema, cada vez que se abre "Verificar facturas faltantes" para
    # cualquier mes, cada vez mas pesado a medida que crece el historial.
    desde_margen = (date.fromisoformat(desde) - timedelta(days=15)).isoformat()
    hasta_margen = (date.fromisoformat(hasta) + timedelta(days=15)).isoformat()
    docs = cliente._call('l10n_cl.supplier.xml', 'search_read',
        [[['invoice_id', '!=', False], ['date', '>=', desde_margen], ['date', '<=', hasta_margen]]],
        {'fields': ['id', 'issuer_name', 'l10n_latam_document_number', 'invoice_id']})
    move_ids = list({d['invoice_id'][0] for d in docs if d['invoice_id'][0] not in ids_en_planilla})
    if not move_ids:
        return []
    moves = cliente._call('account.move', 'read', [move_ids],
        {'fields': ['id', 'company_id', 'invoice_date', 'amount_untaxed', 'amount_total', 'state']})
    moves_por_id = {m['id']: m for m in moves}

    faltantes = []
    for d in docs:
        move_id = d['invoice_id'][0]
        move = moves_por_id.get(move_id)
        if not move or move.get('state') == 'cancel':
            continue
        if not move.get('company_id') or move['company_id'][0] not in company_ids:
            continue
        fecha = move.get('invoice_date')
        if not fecha or not (desde <= fecha <= hasta):
            continue
        faltantes.append(PlanillaFaltanteOut(
            factura_id=move_id, dte_id=d['id'], proveedor_nombre=d.get('issuer_name') or '',
            folio=d.get('l10n_latam_document_number') or '', fecha=fecha,
            subtotal=move.get('amount_untaxed') or 0, total=move.get('amount_total') or 0,
        ))
    faltantes.sort(key=lambda f: f.fecha or '')
    return faltantes


@router.post("/faltantes/{factura_id}/agregar", status_code=status.HTTP_204_NO_CONTENT)
def agregar_faltante(factura_id: int, claims: dict = Depends(get_current_claims)):
    """Agrega esta factura real de Odoo a Planilla de Compras aunque no
    tenga Orden de Compra detras -- mismo mecanismo que "Ingresada
    Manualmente" en Facturas SII. Upsert sobre factura_id (clave primaria)
    -- no puede quedar duplicada aunque se apriete mas de una vez."""
    _require_admin(claims)
    db = get_db()
    db.table("planilla_compras_factura_manual").upsert({
        "factura_id": factura_id, "agregado_por": claims["sub"],
    }).execute()


@router.put("/venta-periodo", status_code=status.HTTP_204_NO_CONTENT)
def fijar_venta_periodo(body: VentaPeriodoIn, claims: dict = Depends(get_current_claims)):
    """Venta del periodo ($) del mes -- editable a mano (igual que en el
    Excel real), y tambien se puede precargar desde TCPOS con
    GET /venta-periodo/tcpos antes de guardar."""
    _require_admin(claims)
    db = get_db()
    db.table("planilla_compras_venta_periodo").upsert({
        "anio": body.anio, "mes": body.mes, "venta_periodo": body.venta_periodo,
        "actualizado_por": claims["sub"],
    }, on_conflict="anio,mes").execute()


def _procesar_venta_periodo_tcpos(job_id: str, anio: int, mes: int) -> None:
    """Corre en un hilo aparte (FastAPI BackgroundTasks) -- confirmado en
    vivo que el reporte "Financial overview" de TCPOS para el mes corrido
    puede tardar mas de 90s (y crece a medida que avanza el mes), muy por
    encima de lo que un timeout de peticion HTTP sincrona puede esperar sin
    arriesgarse a chocar con el propio limite de proxy de Render (~100s).
    Encolar saca ese tiempo de espera de la peticion HTTP -- el frontend
    hace polling de GET /venta-periodo/tcpos/estado en vez de quedarse
    colgado en un solo fetch."""
    db = get_db()
    db.table("planilla_compras_venta_periodo_job").update({"estado": "procesando"}).eq("id", job_id).execute()
    try:
        ultimo_dia_mes = monthrange(anio, mes)[1]
        hasta = date(anio, mes, ultimo_dia_mes)
        ayer = date.today() - timedelta(days=1)
        if hasta > ayer:
            hasta = ayer
        desde = date(anio, mes, 1)
        if desde > hasta:
            raise RuntimeError("Todavía no hay ventas cerradas para ese mes")

        session = TcposWebReportSession(
            os.environ["TCPOS_URL"], os.environ["TCPOS_OPERATOR_CODE"], os.environ["TCPOS_PASSWORD"],
            timeout=280,  # ya no esta atado al timeout de una peticion HTTP -- margen generoso
        )
        formulario = session.formulario_de_parametros(_TCPOS_REPORT_FORM_NAME, _TCPOS_REPORT_ASSEMBLY_NAME)
        overrides = {
            "edDateFrom": f"{desde.isoformat()}T00:00:00", "edDateTo": f"{hasta.isoformat()}T00:00:00",
            "rbSolarDate": True, "clbShops": [_TCPOS_OUTLET_ID_MARGO_ISIDORA], "ckWithdrawalDeposit": True,
        }
        parametros = construir_parametros(formulario, overrides)
        resultado = session.ejecutar_reporte(_TCPOS_REPORT_FORM_NAME, _TCPOS_REPORT_ASSEMBLY_NAME, parametros)
        pdf_url = resultado.get("pdfUrl") if isinstance(resultado, dict) else None
        if not pdf_url:
            raise RuntimeError(f"TCPOS no devolvió un pdfUrl válido: {resultado}")
        pdf_bytes = session.descargar_archivo(pdf_url)
        venta_periodo = parsear_financial_overview_cash_to_deposit(pdf_bytes)

        db.table("planilla_compras_venta_periodo_job").update({
            "estado": "completado", "venta_periodo": venta_periodo,
            "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        }).eq("id", job_id).execute()
    except Exception as e:
        db.table("planilla_compras_venta_periodo_job").update({
            "estado": "error", "error_mensaje": str(e)[:500],
        }).eq("id", job_id).execute()


@router.post("/venta-periodo/tcpos", response_model=VentaPeriodoJobOut, status_code=status.HTTP_202_ACCEPTED)
def encolar_venta_periodo_tcpos(anio: int, mes: int, background_tasks: BackgroundTasks,
                                 claims: dict = Depends(get_current_claims)):
    """Encola traer la Venta del Periodo real desde TCPOS (reporte
    "Financial overview", "Cash to deposit" de la fila Total) en vez de
    esperarlo en la misma peticion -- ver _procesar_venta_periodo_tcpos.
    El frontend hace polling de GET /venta-periodo/tcpos/estado para saber
    cuando termino. Solo trae el valor, no lo guarda -- el admin confirma
    con PUT /venta-periodo."""
    _require_admin(claims)
    db = get_db()
    try:
        fila = db.table("planilla_compras_venta_periodo_job").insert({
            "anio": anio, "mes": mes, "estado": "pendiente", "creado_por": claims["sub"],
        }).execute().data[0]
    except APIError as e:
        if e.code == "23505":
            raise HTTPException(status.HTTP_409_CONFLICT,
                "Ya hay una consulta a TCPOS en curso para este mes -- espera a que termine") from e
        raise
    background_tasks.add_task(_procesar_venta_periodo_tcpos, fila["id"], anio, mes)
    return VentaPeriodoJobOut(**fila)


TIMEOUT_VENTA_PERIODO_JOB_MINUTOS = 6


@router.get("/venta-periodo/tcpos/estado", response_model=VentaPeriodoJobOut | None)
def estado_venta_periodo_tcpos(anio: int, mes: int, claims: dict = Depends(get_current_claims)):
    """Ultimo job de este mes -- para hacer polling desde el frontend (y
    para retomarlo solo si se recarga la pagina mientras esta en curso).
    None si nunca se pidio para este mes.

    Igual que TIMEOUT_COLA_PROCESANDO_MINUTOS en facturas_dte.py: si un job
    lleva "procesando" mas de TIMEOUT_VENTA_PERIODO_JOB_MINUTOS, se marca
    como error -- cubre el caso de que el servidor se reinicie a mitad de
    camino (deploy, o que Render lo duerma/reinicie en plan Free) y el hilo
    en segundo plano se pierda para siempre, dejando el job huerfano
    "procesando" sin que nada lo vuelva a tocar."""
    _require_lectura(claims)
    db = get_db()
    limite = (datetime.now(timezone.utc) - timedelta(minutes=TIMEOUT_VENTA_PERIODO_JOB_MINUTOS)).isoformat()
    db.table("planilla_compras_venta_periodo_job").update({
        "estado": "error",
        "error_mensaje": "Se interrumpió mientras consultaba TCPOS (probablemente un reinicio del servidor) -- "
                          "puedes reintentar.",
    }).eq("anio", anio).eq("mes", mes).eq("estado", "procesando").lt("creado_en", limite).execute()
    filas = db.table("planilla_compras_venta_periodo_job").select("*") \
        .eq("anio", anio).eq("mes", mes).order("creado_en", desc=True).limit(1).execute().data
    return VentaPeriodoJobOut(**filas[0]) if filas else None


@router.get("/proveedores", response_model=list[ProveedorTipoOut])
def listar_proveedores(claims: dict = Depends(get_current_claims)):
    """Catalogo completo proveedor -> Tipo, visible y editable."""
    _require_lectura(claims)
    db = get_db()
    rows = db.table("planilla_compras_proveedor_tipo").select("*").order("proveedor_nombre").execute().data or []
    return [ProveedorTipoOut(**r) for r in rows]


@router.put("/proveedores", status_code=status.HTTP_204_NO_CONTENT)
def asignar_tipo(body: ProveedorTipoIn, claims: dict = Depends(get_current_claims)):
    _require_admin(claims)
    if body.tipo not in TIPOS_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Tipo inválido -- debe ser uno de {sorted(TIPOS_VALIDOS)}")
    db = get_db()
    db.table("planilla_compras_proveedor_tipo").upsert({
        "odoo_partner_id": body.odoo_partner_id, "proveedor_nombre": body.proveedor_nombre,
        "tipo": body.tipo, "actualizado_por": claims["sub"],
    }, on_conflict="odoo_partner_id").execute()
