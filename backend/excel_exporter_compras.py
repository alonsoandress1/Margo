# -*- coding: utf-8 -*-
"""Exporta la Planilla de Compras de la web al Excel real "PLANILLA DE COMPRAS
OFICIAL" -- usa la plantilla real (backend/templates/planilla_compras_meses/,
un archivo POR MES, limpio de datos pero con TODAS las formulas originales
intactas, incluido el desglose por Tipo y por columna-de-proveedor arrastrado
hasta el final de la hoja) y solo escribe en las celdas de entrada
(Tipo/Proveedor/N Factura/IVA/Total por fila, mas Venta Periodo/Venta Actual
del resumen). El resto lo calcula el propio Excel al abrirlo.

Un archivo por mes (no un unico workbook de 12 hojas) a propósito -- el
archivo real completo tiene ~650 filas x 106 columnas x 12 hojas con formula
en casi todas las celdas, y openpyxl tarda ~25s solo en CARGARLO (confirmado
midiendo en local) -- eso hacia expirar el request en Render (502 a los
~45s). Cargar solo la hoja del mes pedido baja eso a ~2-3s.

Las columnas y la fila de Total fueron confirmadas leyendo el archivo real mes
por mes (no son un formato inventado) -- Tipo/Proveedor/N Factura/IVA/Total
caen siempre en las mismas columnas (D/E/F/H/I) en los 12 meses, pero la fila
de Total varia por mes (637-657 segun el mes), por eso se ubica en runtime
buscando la celda "Total" en la columna B en vez de asumir una fila fija."""
from io import BytesIO
from pathlib import Path

import openpyxl

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "planilla_compras_meses"

_MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
          "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

_COL_TIPO, _COL_PROVEEDOR, _COL_FACTURA, _COL_SUBTOTAL, _COL_IVA, _COL_TOTAL = 4, 5, 6, 7, 8, 9
_FILA_DATOS_INICIO = 9
_COL_VENTA_PERIODO = 5  # E3
_COL_VENTA_ACTUAL = 4   # D4


def _fila_total(ws) -> int:
    for r in range(_FILA_DATOS_INICIO, ws.max_row + 1):
        v = ws.cell(row=r, column=2).value
        if v and str(v).strip().upper() == "TOTAL":
            return r
    raise ValueError(f"No se encontró la fila 'Total' en la hoja {ws.title}")


def exportar_mes(anio: int, mes: int, items: list[dict], venta_periodo: float | None) -> bytes:
    """Genera el Excel real, ya lleno, para un mes.

    items: [{proveedor_nombre, num_factura, subtotal, iva, total, tipo}], en el orden en
    que se quieren escribir (ya vienen ordenados por fecha desde Odoo).
    venta_periodo: mismo valor que "Venta del período" de la pantalla web --
    se escribe tanto en VENTA PERIODO (E3) como en VENTA ACTUAL (D4), son el
    mismo dato en este Excel.
    """
    hoja = _MESES[mes - 1]
    wb = openpyxl.load_workbook(_TEMPLATES_DIR / f"{hoja.lower()}.xlsx")
    ws = wb[hoja]

    fila_total = _fila_total(ws)
    filas_disponibles = fila_total - _FILA_DATOS_INICIO
    if len(items) > filas_disponibles:
        raise ValueError(
            f"{hoja} {anio} tiene {len(items)} facturas pero la plantilla solo tiene "
            f"{filas_disponibles} filas disponibles antes de la fila de Total")

    for i, it in enumerate(items):
        fila = _FILA_DATOS_INICIO + i
        ws.cell(row=fila, column=_COL_TIPO).value = it.get("tipo")
        ws.cell(row=fila, column=_COL_PROVEEDOR).value = it.get("proveedor_nombre")
        ws.cell(row=fila, column=_COL_FACTURA).value = it.get("num_factura")
        # SUB TOTAL (G) se escribe como valor fijo, no se deja la formula
        # =TOTAL-IVA de la plantilla -- algunos visores de Excel no
        # recalculan las formulas al abrir (no respetan fullCalcOnLoad) y la
        # celda queda en blanco hasta forzar un recalculo manual.
        ws.cell(row=fila, column=_COL_SUBTOTAL).value = it.get("subtotal")
        ws.cell(row=fila, column=_COL_IVA).value = it.get("iva")
        ws.cell(row=fila, column=_COL_TOTAL).value = it.get("total")

    if venta_periodo is not None:
        ws.cell(row=3, column=_COL_VENTA_PERIODO).value = venta_periodo
        ws.cell(row=4, column=_COL_VENTA_ACTUAL).value = venta_periodo

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
