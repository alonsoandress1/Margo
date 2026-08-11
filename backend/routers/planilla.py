import os
import sys
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..planilla_parser import hojas_disponibles, parsear_dia
from ..schemas import (PlanillaConfirmarIn, PlanillaConfirmarOut, PlanillaHojasOut,
                       PlanillaInsumoPreview, PlanillaPreviewOut, PlanillaVentaPreview)
from ..tcpos_report_parser import parsear_article_analysis

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tcpos_connector import TcposWebReportSession, construir_parametros  # noqa: E402

router = APIRouter(prefix="/planilla", tags=["planilla"])

# Confirmados via el CLI de descubrimiento (tcpos_connector.py) -- si TCPOS
# cambia esto en el futuro, se puede volver a correr el CLI para actualizar.
_TCPOS_REPORT_FORM_NAME = "ArticleAnalysisForm"
_TCPOS_REPORT_ASSEMBLY_NAME = "Report.ArticleAnalysis"
_TCPOS_OUTLET_ID_MARGO_ISIDORA = 13  # "1001 Margo Isidora" == local "Doña Delfina" en este sistema


def _require_admin(claims: dict):
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador puede importar la planilla")


@router.post("/hojas", response_model=PlanillaHojasOut)
async def hojas(archivo: UploadFile = File(...), claims: dict = Depends(get_current_claims)):
    """Lista las hojas de dia disponibles en el archivo subido (excluye el resumen)."""
    _require_admin(claims)
    contenido = await archivo.read()
    try:
        return PlanillaHojasOut(hojas=hojas_disponibles(BytesIO(contenido)))
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo leer el archivo: {e}")


@router.post("/importar", response_model=PlanillaPreviewOut)
async def importar(
    archivo: UploadFile = File(...),
    hoja: str = Form(...),
    local_id: str = Form(...),
    claims: dict = Depends(get_current_claims),
):
    """Parsea una hoja de dia y arma un preview -- no escribe nada en la
    base de datos todavia, eso pasa en /confirmar despues de revisar."""
    _require_admin(claims)
    verificar_acceso_local(claims, local_id)
    contenido = await archivo.read()
    try:
        datos = parsear_dia(BytesIO(contenido), hoja)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No se pudo leer la planilla: {e}")

    db = get_db()

    platos = db.table("platos").select("id,sku").eq("local_id", local_id).execute().data or []
    plato_id_por_sku = {p["sku"]: p["id"] for p in platos}

    catalogo = db.table("odoo_mapping").select("ingrediente_key").execute().data or []
    key_por_nombre: dict[str, str] = {}
    for c in catalogo:
        nombre_cat = c["ingrediente_key"].split("||")[0].strip().lower()
        key_por_nombre.setdefault(nombre_cat, c["ingrediente_key"])

    ventas = [
        PlanillaVentaPreview(
            codigo=v["codigo"], nombre=v["nombre"], cantidad=v["cantidad"],
            plato_id=plato_id_por_sku.get(v["codigo"]), reconocido=v["codigo"] in plato_id_por_sku,
        )
        for v in datos["ventas"]
    ]
    insumos = [
        PlanillaInsumoPreview(
            nombre=i["nombre"], ingrediente_key=key_por_nombre.get(i["nombre"].strip().lower()),
            stock_informado=i["stock_informado"], mermas_desglose=i["mermas_desglose"],
            entrega_cantidad=i["entrega_cantidad"],
            reconocido=i["nombre"].strip().lower() in key_por_nombre,
        )
        for i in datos["insumos"]
    ]
    return PlanillaPreviewOut(ventas=ventas, insumos=insumos)


@router.post("/confirmar", response_model=PlanillaConfirmarOut, status_code=status.HTTP_201_CREATED)
def confirmar(body: PlanillaConfirmarIn, claims: dict = Depends(get_current_claims)):
    """Guarda el preview ya revisado: ventas al historial (para el futuro
    motor de pronostico), stock informado + mermas a stock_cocina, y las
    entregas a Cocina como egreso de Bodega. No vuelve a leer el archivo."""
    _require_admin(claims)
    verificar_acceso_local(claims, body.local_id)
    db = get_db()

    ventas_guardadas = 0
    for v in body.ventas:
        db.table("ventas_historial").upsert({
            "local_id": body.local_id, "fecha": body.fecha, "plato_id": v.plato_id,
            "plato_sku": v.codigo, "plato_nombre": v.nombre, "cantidad": v.cantidad,
            "created_by": claims["sub"],
        }, on_conflict="local_id,fecha,plato_sku").execute()
        ventas_guardadas += 1

    insumos_guardados = 0
    entregas_registradas = 0
    for i in body.insumos:
        if not i.reconocido or not i.ingrediente_key:
            continue
        if i.stock_informado is not None:
            db.table("stock_cocina").upsert({
                "local_id": body.local_id, "ingrediente_key": i.ingrediente_key, "fecha": body.fecha,
                "cantidad_informada": i.stock_informado, "mermas_desglose": i.mermas_desglose or None,
                "created_by": claims["sub"],
            }, on_conflict="local_id,ingrediente_key,fecha").execute()
            insumos_guardados += 1
        if i.entrega_cantidad and i.entrega_cantidad > 0:
            # bodega_movimientos es un libro append-only -- si el mismo dia se
            # reimporta (ej. corrigiendo un dato), no se debe duplicar el
            # egreso, se reemplaza el que ya existia para ese dia/insumo.
            ya = db.table("bodega_movimientos").select("id") \
                .eq("local_id", body.local_id).eq("ingrediente_key", i.ingrediente_key) \
                .eq("origen", "entrega_cocina") \
                .gte("fecha", f"{body.fecha}T00:00:00+00:00").lt("fecha", f"{body.fecha}T23:59:59.999999+00:00") \
                .execute()
            nota = f"Entrega a Cocina -- importado de planilla ({body.fecha})"
            if ya.data:
                db.table("bodega_movimientos").update({"cantidad": i.entrega_cantidad, "nota": nota}) \
                    .eq("id", ya.data[0]["id"]).execute()
            else:
                db.table("bodega_movimientos").insert({
                    "local_id": body.local_id, "ingrediente_key": i.ingrediente_key, "tipo": "egreso",
                    "cantidad": i.entrega_cantidad, "origen": "entrega_cocina", "nota": nota,
                    "fecha": f"{body.fecha}T00:00:00+00:00", "created_by": claims["sub"],
                }).execute()
            entregas_registradas += 1

    return PlanillaConfirmarOut(
        ventas_guardadas=ventas_guardadas, insumos_guardados=insumos_guardados,
        entregas_registradas=entregas_registradas,
    )


def _verificar_cron_secret(x_cron_secret: str | None = Header(default=None)):
    """No usa login de usuario -- este endpoint lo llama un cron externo sin
    nadie presente, se protege con un secreto compartido (CRON_SECRET en
    Render) en vez de un JWT."""
    esperado = os.environ.get("CRON_SECRET")
    if not esperado or x_cron_secret != esperado:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Secreto de cron inválido o no configurado")


@router.post("/importar-ventas-tcpos", status_code=status.HTTP_201_CREATED)
def importar_ventas_tcpos(_: None = Depends(_verificar_cron_secret)):
    """Descarga automaticamente el reporte de ventas de AYER desde TCPOS
    (Article Analysis, local Margo Isidora = Doña Delfina, agrupado por
    Group D) y lo guarda en ventas_historial. Pensado para llamarse una vez
    al dia desde un cron externo (GitHub Actions) -- no requiere que nadie
    entre a la web ni escriba credenciales."""
    db = get_db()

    local = db.table("locales").select("id").eq("nombre", "Doña Delfina").execute()
    if not local.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se encontró el local 'Doña Delfina'")
    local_id = local.data[0]["id"]

    ayer = date.today() - timedelta(days=1)
    ayer_iso = ayer.strftime("%Y-%m-%dT00:00:00")
    fecha = ayer.isoformat()

    try:
        session = TcposWebReportSession(
            os.environ["TCPOS_URL"], os.environ["TCPOS_OPERATOR_CODE"], os.environ["TCPOS_PASSWORD"],
        )
        formulario = session.formulario_de_parametros(_TCPOS_REPORT_FORM_NAME, _TCPOS_REPORT_ASSEMBLY_NAME)
        overrides = {
            "edDateFrom": ayer_iso, "edDateTo": ayer_iso,
            "edTimeFrom": 0, "edTimeTo": 1439,
            "rbCalendarDate": True,
            "clbShops": [_TCPOS_OUTLET_ID_MARGO_ISIDORA],
            "rbGroupD": True,
        }
        parametros = construir_parametros(formulario, overrides)
        resultado = session.ejecutar_reporte(_TCPOS_REPORT_FORM_NAME, _TCPOS_REPORT_ASSEMBLY_NAME, parametros)
        pdf_url = resultado.get("pdfUrl") if isinstance(resultado, dict) else None
        if not pdf_url:
            raise RuntimeError(f"TCPOS no devolvió un pdfUrl valido: {resultado}")
        pdf_bytes = session.descargar_archivo(pdf_url)
    except KeyError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error al traer el reporte de TCPOS: {e}")

    # Respaldo del PDF original en Supabase Storage, nombrado por fecha --
    # si falla no debe tirar abajo el guardado de las ventas (lo importante
    # ya se descargo y se va a parsear igual).
    pdf_guardado = True
    try:
        db.storage.from_("reportes-ventas").upload(
            f"{local_id}/{fecha}-ArticleAnalysis.pdf", pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
    except Exception:
        pdf_guardado = False

    filas = parsear_article_analysis(pdf_bytes)

    platos = db.table("platos").select("id,sku").eq("local_id", local_id).execute().data or []
    plato_id_por_sku = {p["sku"]: p["id"] for p in platos}

    for f in filas:
        db.table("ventas_historial").upsert({
            "local_id": local_id, "fecha": fecha, "plato_id": plato_id_por_sku.get(f["codigo"]),
            "plato_sku": f["codigo"], "plato_nombre": f["nombre"], "cantidad": f["cantidad"],
        }, on_conflict="local_id,fecha,plato_sku").execute()

    return {"fecha": fecha, "ventas_guardadas": len(filas), "pdf_guardado": pdf_guardado}
