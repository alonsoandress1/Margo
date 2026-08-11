from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..planilla_parser import hojas_disponibles, parsear_dia
from ..schemas import (PlanillaConfirmarIn, PlanillaConfirmarOut, PlanillaHojasOut,
                       PlanillaInsumoPreview, PlanillaPreviewOut, PlanillaVentaPreview)

router = APIRouter(prefix="/planilla", tags=["planilla"])


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
