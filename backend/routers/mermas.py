from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from ..catalogo import productos_mas_baratos
from ..db import get_db
from ..deps import get_current_claims, verificar_acceso_local
from ..schemas import MermaItem, StockCocinaIn

router = APIRouter(prefix="/mermas", tags=["mermas"])


def _dia_anterior(fecha: str) -> str:
    return (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()


def _stock_inicial_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """El Stock Inicial de un dia es el Stock Informado (conteo fisico) del
    dia anterior -- se arrastra, igual que en la planilla."""
    fecha_ant = _dia_anterior(fecha)
    rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada") \
        .eq("local_id", local_id).eq("fecha", fecha_ant).execute().data or []
    return {r["ingrediente_key"]: r["cantidad_informada"] for r in rows}


def _entregas_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Entregas de Bodega a Cocina ese dia (bodega_movimientos, origen
    entrega_cocina -- via importar planilla o registrado a mano en
    Inventario)."""
    rows = db.table("bodega_movimientos").select("ingrediente_key,cantidad") \
        .eq("local_id", local_id).eq("origen", "entrega_cocina") \
        .gte("fecha", f"{fecha}T00:00:00+00:00").lt("fecha", f"{fecha}T23:59:59.999999+00:00") \
        .execute().data or []
    resultado: dict[str, float] = {}
    for r in rows:
        resultado[r["ingrediente_key"]] = resultado.get(r["ingrediente_key"], 0) + r["cantidad"]
    return resultado


def _ventas_por_insumo(db, local_id: str, fecha: str) -> dict[str, float]:
    """Consumo de insumo por las ventas del dia: ventas_historial (por
    plato, ya automatizado desde TCPOS) x receta.cantidad (factor) --
    mismo calculo que hacia la formula SUMPRODUCT de la planilla. Solo
    suma lineas de receta que ya tienen ingrediente_key enlazado al
    catalogo -- si la receta no esta armada todavia, no aporta."""
    ventas = db.table("ventas_historial").select("plato_id,cantidad") \
        .eq("local_id", local_id).eq("fecha", fecha).execute().data or []
    cantidad_por_plato: dict[str, float] = {}
    for v in ventas:
        if v.get("plato_id"):
            cantidad_por_plato[v["plato_id"]] = cantidad_por_plato.get(v["plato_id"], 0) + v["cantidad"]
    if not cantidad_por_plato:
        return {}

    recetas = db.table("recetas").select("plato_id,ingrediente_key,cantidad") \
        .in_("plato_id", list(cantidad_por_plato.keys())).execute().data or []

    resultado: dict[str, float] = {}
    for r in recetas:
        key = r.get("ingrediente_key")
        if not key:
            continue
        vendido = cantidad_por_plato.get(r["plato_id"], 0)
        resultado[key] = resultado.get(key, 0) + vendido * r["cantidad"]
    return resultado


@router.get("", response_model=list[MermaItem])
def listar_mermas(local_id: str, fecha: str | None = None, claims: dict = Depends(get_current_claims)):
    """Vista tipo planilla del dia: Stock Inicial (arrastrado de ayer),
    Entregas y Ventas se calculan solas; Mermas y Stock Informado se
    ingresan a mano. Por defecto muestra AYER -- es el dia cuyas ventas ya
    estan completas y disponibles (la automatizacion trae las ventas de
    ayer cada madrugada, igual que antes se pegaban a mano)."""
    verificar_acceso_local(claims, local_id)
    fecha = fecha or (date.today() - timedelta(days=1)).isoformat()
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).eq("seguimiento_mermas", True).execute().data or []
    if not par_rows:
        return []
    keys = [r["ingrediente_key"] for r in par_rows]

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,cantidad_informada,mermas_total") \
        .eq("local_id", local_id).eq("fecha", fecha).in_("ingrediente_key", keys).execute().data or []
    informado = {c["ingrediente_key"]: c for c in cocina_rows}

    stock_inicial = _stock_inicial_por_insumo(db, local_id, fecha)
    entregas = _entregas_por_insumo(db, local_id, fecha)
    ventas = _ventas_por_insumo(db, local_id, fecha)
    precios = productos_mas_baratos(db, keys)

    return [
        MermaItem(
            ingrediente_key=r["ingrediente_key"], nombre=r["ingrediente_key"].split("||")[0],
            unidad=r["unidad"], categoria=r["categoria"], fecha=fecha,
            cantidad_informada=(informado.get(r["ingrediente_key"]) or {}).get("cantidad_informada"),
            mermas_total=(informado.get(r["ingrediente_key"]) or {}).get("mermas_total"),
            stock_inicial=stock_inicial.get(r["ingrediente_key"], 0),
            entregas=entregas.get(r["ingrediente_key"], 0),
            ventas=round(ventas.get(r["ingrediente_key"], 0), 3),
            precio=precios.get(r["ingrediente_key"], {}).get("price", 0),
        )
        for r in par_rows
    ]


@router.post("", status_code=201)
def registrar_merma(body: StockCocinaIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede registrar mermas")
    verificar_acceso_local(claims, body.local_id)
    fecha = body.fecha or (date.today() - timedelta(days=1)).isoformat()

    db = get_db()
    res = db.table("stock_cocina").upsert({
        "local_id": body.local_id,
        "ingrediente_key": body.ingrediente_key,
        "fecha": fecha,
        "cantidad_informada": body.cantidad_informada,
        "mermas_total": body.mermas_total,
        "created_by": claims["sub"],
    }, on_conflict="local_id,ingrediente_key,fecha").execute()
    return res.data[0]
