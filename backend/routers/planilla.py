import os
import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse

from ..db import get_db
from ..deps import get_current_claims
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


@router.get("/tcpos-descubrir")
def tcpos_descubrir(reporte: str | None = None, ejecutar: bool = False, desde: str | None = None,
                     hasta: str | None = None, claims: dict = Depends(get_current_claims)):
    """TEMPORAL -- solo para descubrir el nombre/parametros exactos de un
    reporte de TCPOS (ej. 'Financial Overview') usando las credenciales de
    servicio que ya viven en Render, sin que nadie las escriba/vea en el
    chat. Admin-only, solo lectura contra TCPOS. Borrar una vez que se
    confirme el reporte de venta del periodo."""
    if claims["rol"] != "administrador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un administrador")
    import json as _json
    import traceback
    try:
        session = TcposWebReportSession(
            os.environ["TCPOS_URL"], os.environ["TCPOS_OPERATOR_CODE"], os.environ["TCPOS_PASSWORD"],
        )
        reportes_resp = session.listar_reportes()
        lista_reportes = reportes_resp.get("reports", []) if isinstance(reportes_resp, dict) else reportes_resp
        if not reporte:
            return PlainTextResponse(_json.dumps({"reportes": lista_reportes}, default=str, ensure_ascii=False))
        match = next((r for r in lista_reportes if r.get("displayName", "").strip().lower() == reporte.lower()), None)
        if not match:
            return PlainTextResponse(f"No se encontró un reporte con displayName='{reporte}'", status_code=404)
        formulario = session.formulario_de_parametros(match["formName"], match["assemblyName"])
        if not ejecutar:
            return PlainTextResponse(_json.dumps({"match": match, "formulario": formulario}, default=str, ensure_ascii=False))

        overrides = {
            "edDateFrom": f"{desde}T00:00:00", "edDateTo": f"{hasta}T00:00:00",
            "rbSolarDate": True, "clbShops": [_TCPOS_OUTLET_ID_MARGO_ISIDORA],
            "ckWithdrawalDeposit": True,
        }
        parametros = construir_parametros(formulario, overrides)
        resultado = session.ejecutar_reporte(match["formName"], match["assemblyName"], parametros)
        pdf_url = resultado.get("pdfUrl") if isinstance(resultado, dict) else None
        if not pdf_url:
            return PlainTextResponse(_json.dumps({"resultado": resultado}, default=str, ensure_ascii=False))
        pdf_bytes = session.descargar_archivo(pdf_url)

        import pdfplumber
        from io import BytesIO
        salida = []
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                for j, tabla in enumerate(pagina.extract_tables()):
                    salida.append(f"--- pagina {i} tabla {j} ---")
                    for fila in tabla:
                        salida.append(str(fila))
        return PlainTextResponse("\n".join(salida))
    except Exception:
        return PlainTextResponse(traceback.format_exc(), status_code=500)


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
