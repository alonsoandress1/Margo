import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status
from postgrest.exceptions import APIError

from ..bodega_service import consumo_promedio_por_dia_semana, stock_bodega_por_insumo
from ..catalogo import productos_mas_baratos
from ..db import get_db
from ..deps import get_current_claims, get_odoo_credentials, locales_permitidos, verificar_acceso_local
from ..email_sender import enviar_aviso_pedido, enviar_oc_pdf
from ..schemas import (AccionCompra, FavoritoIn, GenerarOCOut, PedidoEstadoIn,
                       PedidoIn, PedidoOut, SugerenciaItem)

# odoo_connector.py vive en la raiz del repo (lo comparte tambien la app de
# escritorio y los scripts de terminal) -- se agrega esa ruta para poder
# importarlo sin duplicar el archivo dentro del paquete backend.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from odoo_connector import OdooWebSession  # noqa: E402

router = APIRouter(prefix="/pedidos", tags=["pedidos"])

ESTADOS_VALIDOS = ("aprobado", "rechazado", "editado")
MAX_ITEMS_POR_OC = 20  # Doña Sofía no acepta OC con mas de 20 lineas -- se parte en varias


def _en_bloques(items: list, tamano: int):
    for i in range(0, len(items), tamano):
        yield items[i:i + tamano]


def _redondear_a_empaque(cantidad: float, tamano_empaque: float | None) -> float:
    """Redondea hacia arriba al multiplo del tamano de empaque -- no se
    puede pedir una cantidad que el proveedor no despacha tal cual
    (ej. Filete Salteado viene en paquetes de 1.6 kg)."""
    if not tamano_empaque or tamano_empaque <= 0 or cantidad <= 0:
        return cantidad
    paquetes = math.ceil(round(cantidad / tamano_empaque, 6))
    return round(paquetes * tamano_empaque, 3)


def _dias_cobertura(dias_entrega: int, dias_pedido: list[int], hoy_wd: int) -> int:
    """Cuantos dias de consumo tiene que cubrir un pedido hecho HOY: desde
    hoy hasta que llegue el SIGUIENTE pedido (no solo hasta que llegue
    este). Ej. Doña Sofia pide Lunes/Miercoles/Sabado con 2 dias de
    espera -- un pedido de Miercoles llega el Viernes, pero recien se
    repone de nuevo cuando llegue el del Sabado, el Lunes -- tiene que
    durar 5 dias (Mie,Jue,Vie,Sab,Dom), no solo los 2 de espera.

    Sin dias_pedido configurado (proveedor sin agenda definida todavia),
    se usa solo dias_entrega -- mismo comportamiento que antes de esto."""
    if not dias_pedido:
        return dias_entrega
    dias_pedido_set = set(dias_pedido)
    for d in range(1, 8):
        if (hoy_wd + d) % 7 in dias_pedido_set:
            return d + dias_entrega
    return dias_entrega  # dias_pedido vacio de hecho pese al chequeo -- no deberia pasar


def _con_po_tracking(db, pedidos: list[dict]) -> list[dict]:
    if not pedidos:
        return pedidos
    ids = [p["id"] for p in pedidos]
    tracking = db.table("po_tracking").select("pedido_id,tipo,po_id,po_name,proveedor").in_("pedido_id", ids).execute().data or []
    por_pedido: dict[str, list] = {}
    for t in tracking:
        por_pedido.setdefault(t["pedido_id"], []).append(t)
    for p in pedidos:
        p["acciones"] = [
            {"proveedor": t["proveedor"], "tipo": t["tipo"], "po_id": t.get("po_id"), "po_name": t.get("po_name")}
            for t in por_pedido.get(p["id"], [])
        ]
    return pedidos


@router.get("/sugerencia", response_model=list[SugerenciaItem])
def sugerencia_compra(local_id: str, claims: dict = Depends(get_current_claims)):
    """Sugerencia basada en Par Stock - stock actual (bodega + cocina) +
    consumo proyectado. Elige automaticamente el proveedor mas barato
    entre los registrados para cada insumo.

    consumo_proyectado cubre desde HOY hasta que llegue el SIGUIENTE
    pedido (no solo hasta que llegue este) -- si los pedidos no son
    diarios (ej. Doña Sofia: Lunes/Miercoles/Sabado, 2 dias de espera),
    un pedido hecho hoy Miercoles llega el Viernes, pero tiene que durar
    hasta que llegue el del Sabado (el Lunes siguiente) -- 5 dias, no 2.
    Mirar solo dias_entrega dejaba el pedido corto para el fin de semana.
    Ver _dias_cobertura. Sin dias_pedido configurado, se usa solo
    dias_entrega (mismo comportamiento que antes para proveedores sin
    agenda definida); dias_entrega=0 deja la formula identica a como era
    antes de sumar el consumo proyectado."""
    verificar_acceso_local(claims, local_id)
    db = get_db()

    par_rows = db.table("par_stock").select("*").eq("local_id", local_id).order("ingrediente_key").execute().data or []
    if not par_rows:
        return []
    keys = [r["ingrediente_key"] for r in par_rows]
    stock_bodega = stock_bodega_por_insumo(db, local_id, keys)
    consumo_promedio = consumo_promedio_por_dia_semana(db, local_id, keys)

    cocina_rows = db.table("stock_cocina").select("ingrediente_key,fecha,cantidad_informada") \
        .eq("local_id", local_id).in_("ingrediente_key", keys) \
        .order("fecha", desc=True).execute().data or []
    stock_cocina: dict[str, float] = {}
    for c in cocina_rows:
        stock_cocina.setdefault(c["ingrediente_key"], c["cantidad_informada"])  # primera = mas reciente (ya ordenado)

    mapping = productos_mas_baratos(db, keys)
    proveedor_ids = list({m["proveedor_id"] for m in mapping.values() if m.get("proveedor_id")})
    proveedores_info = {
        p["id"]: p
        for p in (db.table("proveedores").select("id,dias_entrega,dias_pedido").in_("id", proveedor_ids).execute().data or [])
    } if proveedor_ids else {}

    hoy = date.today()
    resultado = []
    for r in par_rows:
        key = r["ingrediente_key"]
        nombre = key.split("||")[0]
        en_bodega = stock_bodega.get(key, 0)
        en_cocina = stock_cocina.get(key, 0)
        disponible = en_bodega + en_cocina
        m = mapping.get(key, {})
        prov_info = proveedores_info.get(m.get("proveedor_id"), {})
        dias_entrega = prov_info.get("dias_entrega", 0)
        dias_cobertura = _dias_cobertura(dias_entrega, prov_info.get("dias_pedido") or [], hoy.weekday())
        promedios_insumo = consumo_promedio.get(key, {})
        consumo_proyectado = sum(
            promedios_insumo.get((hoy + timedelta(days=i)).weekday(), 0)
            for i in range(dias_cobertura)
        )
        sugerido = max(0.0, r["par_cantidad"] - disponible + consumo_proyectado)
        sugerido = _redondear_a_empaque(sugerido, m.get("tamano_empaque"))
        resultado.append(SugerenciaItem(
            ingrediente_key=key, nombre=nombre, unidad=r["unidad"], categoria=r["categoria"],
            par=r["par_cantidad"], stock_bodega=en_bodega, stock_cocina=en_cocina,
            sugerido=sugerido, precio=m.get("price", 0), proveedor=m.get("supplier_name"),
            tamano_empaque=m.get("tamano_empaque"),
            consumo_proyectado=round(consumo_proyectado, 3), dias_entrega=dias_entrega,
            dias_cobertura=dias_cobertura,
        ))
    return resultado


@router.get("", response_model=list[PedidoOut])
def listar_pedidos(local_id: str | None = None, claims: dict = Depends(get_current_claims)):
    db = get_db()
    permitidos = locales_permitidos(claims)

    if local_id:
        verificar_acceso_local(claims, local_id)
        q = db.table("pedidos").select("*").eq("local_id", local_id)
    else:
        if permitidos is not None:
            if not permitidos:
                return []
            q = db.table("pedidos").select("*").in_("local_id", permitidos)
        else:
            q = db.table("pedidos").select("*")

    res = q.order("created_at", desc=True).execute()
    return _con_po_tracking(db, res.data or [])


@router.post("", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def crear_pedido(body: PedidoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede crear pedidos")
    verificar_acceso_local(claims, body.local_id)

    db = get_db()
    res = db.table("pedidos").insert({
        "local_id": body.local_id,
        "items": body.items,
        "estado": "pendiente",
        "creado_por": claims["sub"],
    }).execute()
    return _con_po_tracking(db, res.data)[0]


@router.patch("/{pedido_id}/estado", response_model=PedidoOut)
def actualizar_estado(pedido_id: str, body: PedidoEstadoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede modificar pedidos")
    if body.estado not in ESTADOS_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Estado invalido, debe ser uno de: {ESTADOS_VALIDOS}")

    db = get_db()
    existente = db.table("pedidos").select("local_id,creado_por").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    # Separacion de funciones: quien creo el pedido no puede ser quien lo
    # aprueba o rechaza (aunque sea administrador) -- si podria, un mismo
    # solicitante/administrador podria pedir y auto-aprobarse sin que nadie
    # mas lo revise. "editado" no cuenta (es la propia persona ajustando su
    # pedido antes de que otro lo revise), solo aprobado/rechazado.
    if body.estado in ("aprobado", "rechazado") and existente.data[0].get("creado_por") == claims["sub"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No puedes aprobar o rechazar un pedido que tu mismo creaste -- pidele a otra persona que lo revise",
        )

    update = {
        "estado": body.estado,
        "revisado_por": claims["sub"],
        "revisado_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.items is not None:
        update["items"] = body.items

    res = db.table("pedidos").update(update).eq("id", pedido_id).execute()
    return _con_po_tracking(db, res.data)[0]


@router.patch("/{pedido_id}/favorito", response_model=PedidoOut)
def marcar_favorito(pedido_id: str, body: FavoritoIn, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede marcar favoritos")

    db = get_db()
    existente = db.table("pedidos").select("local_id").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    res = db.table("pedidos").update({"favorito": body.favorito}).eq("id", pedido_id).execute()
    return _con_po_tracking(db, res.data)[0]


@router.delete("/{pedido_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_pedido(pedido_id: str, claims: dict = Depends(get_current_claims)):
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede eliminar pedidos")

    db = get_db()
    existente = db.table("pedidos").select("local_id").eq("id", pedido_id).execute()
    if not existente.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    verificar_acceso_local(claims, existente.data[0]["local_id"])

    con_acciones = db.table("po_tracking").select("id").eq("pedido_id", pedido_id).execute()
    if con_acciones.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No se puede eliminar: ya se generó una OC o aviso de compra para este pedido",
        )

    db.table("pedidos").delete().eq("id", pedido_id).execute()


@router.post("/{pedido_id}/generar-oc", response_model=GenerarOCOut)
def generar_oc(pedido_id: str, claims: dict = Depends(get_current_claims),
                x_odoo_user: str | None = Header(default=None),
                x_odoo_password: str | None = Header(default=None),
                x_odoo_company_id: str | None = Header(default=None)):
    """Genera la accion de compra de un pedido ya aprobado, insumo por
    insumo se elige el proveedor mas barato entre los registrados:
    - Si ese proveedor tiene integracion a Odoo (usa_odoo=true, hoy solo
      Doña Sofía), se crea la Orden de Compra real con las credenciales de
      Odoo de la persona conectada (nunca una cuenta compartida) -- por eso
      NO se usa Depends(get_odoo_credentials) aca: solo hace falta pedirlas
      si algun proveedor del pedido realmente usa Odoo, no siempre.
      x_odoo_company_id es la empresa que la persona eligio en el frontend
      (GET /odoo/empresas, solo se le pregunta si tiene acceso a 2 o mas) --
      si no viene (usuario con una sola empresa), se cae al viejo mecanismo
      de adivinarla por el nombre del local.
    - Si no, se envia un correo con el nombre del proveedor y las
      cantidades solicitadas, al destinatario configurado en Configuración."""
    if claims["rol"] == "observador":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El rol observador no puede generar OC")

    db = get_db()
    pedido_res = db.table("pedidos").select("*").eq("id", pedido_id).execute()
    if not pedido_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido no encontrado")
    pedido = pedido_res.data[0]
    verificar_acceso_local(claims, pedido["local_id"])

    if pedido["estado"] != "aprobado":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Solo se puede generar la OC de un pedido aprobado")

    ya_existe = db.table("po_tracking").select("id").eq("pedido_id", pedido_id).execute()
    if ya_existe.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ya se generó una acción de compra para este pedido")

    # Reclamo atomico ANTES de tocar Odoo/correo -- el chequeo de arriba
    # (leer po_tracking) por si solo no alcanza contra dos clics casi
    # simultaneos (o dos pestañas): los dos pueden pasar esa lectura antes
    # de que cualquiera alcance a insertar su primera fila de po_tracking,
    # y terminar creando dos OC reales en Odoo para el mismo pedido. Se
    # inserta una fila en pedido_oc_claim con pedido_id como llave unica --
    # solo el primer clic gana. Si algo falla despues (Odoo caido,
    # credenciales, correo), se libera el reclamo en el except de mas
    # abajo para que se pueda reintentar -- mismo criterio de "seguro
    # reintentar" que ya se usa en la cola de Facturas Odoo.
    try:
        db.table("pedido_oc_claim").insert({"pedido_id": pedido_id}).execute()
    except APIError as e:
        if e.code == "23505":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ya se generó (o se está generando en este momento) una acción de compra para este pedido",
            ) from e
        raise

    try:
        local = db.table("locales").select("nombre").eq("id", pedido["local_id"]).execute().data[0]

        keys = [i["ingrediente_key"] for i in pedido["items"] if i.get("ingrediente_key")]
        mapping = productos_mas_baratos(db, keys)

        grupos: dict[str, list[tuple[dict, dict]]] = {}
        omitidos = []
        for item in pedido["items"]:
            key = item.get("ingrediente_key")
            m = mapping.get(key) if key else None
            if not m or not m.get("proveedor_id"):
                omitidos.append(item.get("ingrediente", "?"))
                continue
            grupos.setdefault(m["proveedor_id"], []).append((m, item))

        if not grupos:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ningun insumo del pedido tiene un proveedor registrado -- nada que generar")

        resultado = _generar_oc_cuerpo(db, pedido, pedido_id, local, grupos, omitidos,
                                        claims, x_odoo_user, x_odoo_password, x_odoo_company_id)
    except Exception:
        db.table("pedido_oc_claim").delete().eq("pedido_id", pedido_id).execute()
        raise
    return resultado


def _generar_oc_cuerpo(db, pedido: dict, pedido_id: str, local: dict, grupos: dict, omitidos: list,
                        claims: dict, x_odoo_user, x_odoo_password, x_odoo_company_id) -> GenerarOCOut:
    proveedor_ids = list(grupos.keys())
    proveedores = {p["id"]: p for p in db.table("proveedores").select("*").in_("id", proveedor_ids).execute().data or []}

    config_res = db.table("configuracion_email").select("destinatario,cc").limit(1).execute()
    config = config_res.data[0] if config_res.data else None
    cc_list = [c.strip() for c in ((config or {}).get("cc") or "").split(",") if c.strip()] if config else []

    acciones: list[AccionCompra] = []
    odoo_session: OdooWebSession | None = None
    odoo_company_id: int | None = None

    # La conexion a Odoo (si hace falta) se resuelve ACA, antes de tocar
    # correo o po_tracking para cualquier proveedor -- si esto se dejara
    # para dentro del loop (como antes), un pedido con un proveedor por
    # correo Y uno por Odoo podia mandar el correo, insertar su po_tracking,
    # y solo AHI pedir credenciales de Odoo (428). El frontend reintenta
    # automaticamente tras el modal, pero el reintento volvia a entrar a
    # esta funcion, encontraba el po_tracking del correo ya insertado, y
    # rechazaba TODO con "ya se generó una acción de compra" -- dejando la
    # parte de Odoo sin crear para siempre, sin forma de reintentarla.
    if any((proveedores.get(pid) or {}).get("usa_odoo") for pid in grupos):
        if not x_odoo_user or not x_odoo_password:
            raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "Faltan tus credenciales de Odoo")
        try:
            odoo_session = OdooWebSession(os.environ["ODOO_URL"])
            ok, msg = odoo_session.connect(x_odoo_user, x_odoo_password)
        except KeyError as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e}")
        if not ok:
            if "login rechazado" in msg.lower():
                raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, f"Odoo: {msg}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo conectar a Odoo: {msg}")

        # Se fuerza la empresa correcta -- un usuario de Odoo con acceso a
        # varias empresas no necesariamente tiene activa la del local
        # correcto en su propia sesion de Odoo, y sin forzarla la OC se crea
        # bajo la empresa equivocada sin avisar. Primero la que la persona
        # eligio en el frontend (ve GET /odoo/empresas); si no vino (solo
        # tiene una empresa, no se le pregunto), se cae a adivinarla por el
        # nombre del local.
        if x_odoo_company_id:
            try:
                odoo_company_id = int(x_odoo_company_id)
            except ValueError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Odoo-Company-Id invalido")
        else:
            odoo_company_id = odoo_session.buscar_company_id_por_nombre(local["nombre"])
            if odoo_company_id is None:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"No se encontró una única empresa en Odoo con nombre parecido a \"{local['nombre']}\" -- "
                    "revisa que el nombre del local coincida con el de la empresa en Odoo (Ajustes > Empresas)",
                )

    for proveedor_id, entradas in grupos.items():
        proveedor = proveedores.get(proveedor_id)
        nombre_proveedor = proveedor["nombre"] if proveedor else "Proveedor desconocido"

        if proveedor and proveedor.get("usa_odoo"):
            # La unidad que se le manda a Odoo por linea sale, en orden de
            # prioridad: (1) la que nosotros mismos definimos explicitamente
            # para ESE producto en Proveedores (odoo_mapping.unidad_odoo --
            # justamente para no quedar a merced de como haya quedado
            # configurado alla), y si no la definimos, (2) la que ese
            # producto tenga configurada por defecto en su propia ficha de
            # Odoo (mejor eso que nada).
            ids_uom = odoo_session.call_kw('ir.model.data', 'search_read',
                [[['module', '=', 'uom'], ['name', 'in', ['product_uom_kgm', 'product_uom_unit']]]],
                {'fields': ['name', 'res_id']})
            uom_por_nombre = {u['name']: u['res_id'] for u in ids_uom}
            uom_odoo_a_id = {'kg': uom_por_nombre.get('product_uom_kgm'), 'un': uom_por_nombre.get('product_uom_unit')}

            ids_sin_override = list({m["odoo_id"] for m, _ in entradas if not m.get("unidad_odoo")})
            uom_default_producto = {}
            if ids_sin_override:
                productos_odoo = odoo_session.call_kw('product.product', 'read',
                    [ids_sin_override], {'fields': ['uom_id']})
                uom_default_producto = {p['id']: p['uom_id'][0] for p in productos_odoo if p.get('uom_id')}

            bloques = list(_en_bloques(entradas, MAX_ITEMS_POR_OC))
            total_bloques = len(bloques)

            for idx, bloque in enumerate(bloques, start=1):
                po_lines = []
                for m, item in bloque:
                    cantidad = float(item.get("cantidad", 0))
                    unidad = (item.get("unidad") or "").lower()
                    cantidad_kg = cantidad / 1000 if unidad == "g" else cantidad
                    cantidad_kg = _redondear_a_empaque(cantidad_kg, m.get("tamano_empaque"))
                    override = m.get("unidad_odoo")
                    uom_linea = uom_odoo_a_id.get(override) if override else uom_default_producto.get(m["odoo_id"])
                    # El precio pactado en un acuerdo comercial manda por
                    # sobre el campo "price" de uso libre -- si no hay
                    # acuerdo para este insumo+proveedor, se cae al precio
                    # de siempre (mismo caso que se encontro real esta
                    # sesion: precio viejo desactualizado vs. el pactado).
                    precio_linea = m.get("precio_negociado")
                    if precio_linea is None:
                        precio_linea = m.get("price", 0) or 0
                    linea = {
                        "product_id": m["odoo_id"], "name": m["odoo_name"],
                        "product_qty": round(cantidad_kg, 2), "price_unit": precio_linea,
                    }
                    if uom_linea:
                        linea["product_uom"] = uom_linea
                    po_lines.append(linea)

                notas = f"Generado automaticamente -- pedido {pedido_id}"
                if total_bloques > 1:
                    notas += f" (parte {idx}/{total_bloques} -- max {MAX_ITEMS_POR_OC} lineas por OC)"

                po_id, po_name = odoo_session.create_purchase_order(
                    proveedor["odoo_supplier_id"], po_lines, notes=notas, company_id=odoo_company_id)

                db.table("po_tracking").insert({
                    "tipo": "odoo", "po_id": po_id, "po_name": po_name, "local_id": pedido["local_id"],
                    "pedido_id": pedido_id, "proveedor": nombre_proveedor, "creado_por": claims["sub"],
                }).execute()

                # La OC ya quedo creada en Odoo (lo que importa) -- si el PDF no se
                # puede descargar o enviar, no se revierte nada, solo se avisa.
                aviso = None
                if not config:
                    aviso = "OC creada en Odoo, pero no hay destinatario de correo configurado (ve a Proveedores) para enviar el PDF"
                else:
                    try:
                        report_name = odoo_session.get_report_name_for_model("purchase.order") or "purchase.report_purchasequotation"
                        pdf_bytes = odoo_session.download_pdf_report(report_name, [po_id])
                        enviar_oc_pdf(config["destinatario"], nombre_proveedor, local["nombre"], po_name, pdf_bytes, cc=cc_list)
                    except KeyError as e:
                        aviso = f"OC creada en Odoo, pero falta configurar la variable de entorno {e} para enviar el PDF por correo"
                    except Exception as e:
                        aviso = f"OC creada en Odoo, pero no se pudo enviar el PDF por correo: {e}"

                acciones.append(AccionCompra(proveedor=nombre_proveedor, tipo="odoo", po_id=po_id, po_name=po_name, aviso=aviso))
        else:
            if not config:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "No hay un destinatario de correo configurado (ve a Proveedores)")
            items_email = [{"ingrediente": item.get("ingrediente", "?"), "cantidad": item.get("cantidad", 0), "unidad": item.get("unidad", "")}
                            for _, item in entradas]
            try:
                enviar_aviso_pedido(config["destinatario"], nombre_proveedor, local["nombre"], items_email, cc=cc_list)
            except KeyError as e:
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Falta configurar la variable de entorno {e} para poder enviar correos")
            except Exception as e:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"No se pudo enviar el correo a {nombre_proveedor}: {e}")

            db.table("po_tracking").insert({
                "tipo": "email", "local_id": pedido["local_id"], "pedido_id": pedido_id,
                "proveedor": nombre_proveedor, "creado_por": claims["sub"],
            }).execute()
            acciones.append(AccionCompra(proveedor=nombre_proveedor, tipo="email"))

    return GenerarOCOut(acciones=acciones, omitidos=omitidos)
