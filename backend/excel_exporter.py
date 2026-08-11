# -*- coding: utf-8 -*-
"""Exporta el dia de Mermas de la web al Excel real "Inventario Cocina
Semanal" -- usa la plantilla real (backend/templates/plantilla_inventario_cocina.xlsx,
limpia de datos pero con TODAS las formulas originales intactas) y solo
escribe en las celdas de entrada. Las formulas del propio Excel calculan
Entregas/Ventas/Mermas/Stock Real/Stock Informado/Diferencias solas al
abrirlo -- exactamente igual que si alguien lo hubiera llenado a mano.

Los mapeos de fila de cada bloque fueron reconstruidos leyendo la plantilla
real fila por fila (no son un formato inventado). Documentado por bloque.
"""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import openpyxl
from openpyxl.cell.cell import MergedCell

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "plantilla_inventario_cocina.xlsx"

_DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# ── Bloque 1 (tabla resumen, filas 4-57) -- columna E = Stock Inicial ──────
_FILA_TOP = {
    "Atún Steak": 4, "Atún Trozos": 5, "Almejas Julianas": 6, "Carpaccio de res": 7,
    "Chupe": 8, "Congrio": 9, "Filete despunte": 10, "Filete para churrasco": 11,
    "Filete para crudo": 12, "Filete Salteado": 13, "Ganso": 14, "Hamburguesas": 15,
    "Jamón serrano": 16, "Langostinos": 17, "Lasagna de Berenjenas": 18, "Locos": 19,
    "Lomo liso": 20, "Mejillones": 21, "Merluza": 22, "Plateada": 23, "Pulpo": 24,
    "Ragout Lasagna": 25, "Ragout Rigatoni": 26, "Reineta": 27, "Salmón ahumado en frío": 28,
    "Salmón ahumado en Caliente": 29, "Salmón cancato": 30, "Salmón fresco premium": 31,
    "Brownie Nutella": 37, "Brownie Vegano": 38, "Cheesecake de Berries": 39,
    "Cheesecake de Limón": 40, "Chocolate Blanco": 41, "Chocolate Leche": 42,
    "Chocolate Negro": 43, "Chocolate Neucober Cobertura": 44, "Chocolate Sicao Cobertura": 45,
    "Discos de Chocolate": 46, "Empanada Mechada": 47, "Flan de Caluga": 49,
    "Granola salada": 50, "Mix Conchas": 51, "Nutella": 52, "Queso Mozzarella": 53,
    "Sorrentinos carne mechada": 54, "Sorrentinos pulpo y salmón": 55,
    "Sorrentinos zapallo": 56, "Volcán de Chocolate": 57,
}

# ── Bloque 2 "Control de Stock" (filas 159-216) -- E=Stock Informado, F-J=desglose ──
# Nombres del bloque real difieren en algunos casos (mayusculas/tildes, o un
# nombre distinto para el mismo insumo, ej. "Atún apanado" == "Atún Steak") --
# se documenta explicito, no se adivina en runtime.
_FILA_CONTROL_STOCK = {
    "Atún Steak": 159, "Atún Trozos": 160, "Almejas Julianas": 161, "Carpaccio de res": 162,
    "Reineta": 163, "Congrio": 164, "Chupe": 165, "Filete despunte": 167,
    "Filete para churrasco": 168, "Filete para crudo": 169, "Filete Salteado": 170,
    "Ganso": 171, "Hamburguesas": 172, "Langostinos": 173, "Jamón serrano": 174,
    "Lasagna de Berenjenas": 175, "Lomo liso": 176, "Locos": 177, "Mejillones": 178,
    "Merluza": 179, "Plateada": 181, "Pulpo": 182, "Ragout Lasagna": 183,
    "Ragout Rigatoni": 184, "Salmón ahumado en frío": 185, "Salmón ahumado en Caliente": 186,
    "Salmón cancato": 187, "Salmón fresco premium": 188,
    "Brownie Nutella": 194, "Brownie Vegano": 195, "Cheesecake de Berries": 196,
    "Cheesecake de Limón": 197, "Chocolate Blanco": 198, "Chocolate Leche": 199,
    "Chocolate Negro": 200, "Chocolate Neucober Cobertura": 201, "Chocolate Sicao Cobertura": 202,
    "Discos de Chocolate": 203, "Empanada Mechada": 204, "Flan de Caluga": 208,
    "Granola salada": 209, "Mix Conchas": 210, "Nutella": 211, "Queso Mozzarella": 212,
    "Sorrentinos carne mechada": 213, "Sorrentinos pulpo y salmón": 214,
    "Sorrentinos zapallo": 215, "Volcán de Chocolate": 216,
}
_COL_STOCK_INFORMADO = 5  # E
_COLS_MERMAS_CAUSA = {"produccion": 6, "defectuosos": 7, "clientes": 8, "cortesia": 9, "reutilizar": 10}  # F-J

# ── Bloque "Entregas a Cocina / Salida de Bodega" (filas 221-242) -- E=Cantidad ──
_FILA_ENTREGAS_COCINA = {
    "Atún Steak": 221, "Atún Trozos": 222, "Carpaccio de res": 223, "Empanada Mechada": 225,
    "Filete para churrasco": 226, "Filete para crudo": 227, "Filete Salteado": 228,
    "Ganso": 229, "Granola salada": 230, "Hamburguesas": 231, "Jamón serrano": 232,
    "Lomo liso": 233, "Plateada": 234, "Pulpo": 235, "Queso Mozzarella": 236,
    "Salmón ahumado en Caliente": 237, "Salmón cancato": 238, "Salmón fresco premium": 239,
    "Sorrentinos carne mechada": 240, "Sorrentinos pulpo y salmón": 241, "Sorrentinos zapallo": 242,
}
_COL_ENTREGA_CANTIDAD = 5  # E

# ── Bloque "Entregas de proteínas para producciones de cocina" (filas 247-258) ──
_FILA_BASE_PROTEINAS = 246  # fila = _FILA_BASE_PROTEINAS + orden (orden 1..12)
_COL_PROT_CONSUMIDA = 5  # E
_COL_PROT_PRODUCIDA = 8  # H
_COL_PROT_MERMAS = 10  # J

# ── Bloque "Registro Producciones Pastelería" (filas 262-268) -- E=Cantidad ──
_FILA_PASTELERIA = {
    "Cheesecake de Berries": 262, "Cheesecake de Limón": 263, "Brownie Nutella": 264,
    "Brownie Vegano": 265, "Flan de Caluga": 266, "Volcán de Chocolate": 267,
    "Discos de Chocolate": 268,
}
_COL_PASTELERIA_CANTIDAD = 5  # E

# ── Bloque "Registro de Chocolates" (filas 262-267) -- H=Entregada, K=Utilizada ──
_FILA_CHOCOLATES = {
    "Chocolate Blanco": 262, "Chocolate Leche": 263, "Chocolate Negro": 264,
    "Chocolate Neucober Cobertura": 265, "Chocolate Sicao Cobertura": 266, "Nutella": 267,
}
_COL_CHOC_ENTREGADA = 8  # H
_COL_CHOC_UTILIZADA = 11  # K

# ── Área de pegado de Ventas (filas 272-977) -- B=Código, K=Cantidad Vendida
# (K:L viene combinado en la plantilla real -- K es la celda escribible, y es
# la que la formula de "Vendido" (INDEX K primero, L como respaldo) busca) ──
_FILA_VENTAS_INICIO = 272
_COL_VENTAS_CODIGO = 2  # B
_COL_VENTAS_CANTIDAD = 11  # K (celda superior-izquierda del merge K:L)


def _escribir(ws, fila: int, col: int, valor) -> None:
    """Algunas celdas de la plantilla son parte de un rango combinado (ej.
    filas de continuacion en el bloque de proteinas) -- solo la celda
    superior-izquierda del rango es escribible, el resto son MergedCell."""
    celda = ws.cell(row=fila, column=col)
    if not isinstance(celda, MergedCell):
        celda.value = valor


def _hoja_del_dia(fecha_iso: str) -> str:
    dia_semana = date.fromisoformat(fecha_iso).weekday()  # 0=Lunes
    return f"S1 {_DIAS_SEMANA[dia_semana]}"


def exportar_dia(fecha: str, seguimiento: list[dict], stock_cocina: dict, entregas_bodega: dict,
                  proteinas: list[dict], pasteleria: list[dict], chocolates: list[dict],
                  ventas: list[dict]) -> bytes:
    """Genera el Excel real, ya lleno, para un dia.

    seguimiento: filas de mermas_seguimiento (nombre -> stock_inicial via caller)
    stock_cocina: {ingrediente_key: {cantidad_informada, mermas_desglose}}
    entregas_bodega: {ingrediente_key: cantidad}
    proteinas: filas de produccion_proteinas_recetas + diaria (orden, cantidad_consumida, cantidad_producida, mermas)
    pasteleria: filas de pasteleria_seguimiento + diaria (producto_nombre, cantidad_producida)
    chocolates: filas de chocolates_seguimiento + diaria (producto_nombre, cantidad_entregada, cantidad_utilizada)
    ventas: filas de ventas_historial (plato_sku, cantidad)
    """
    wb = openpyxl.load_workbook(_TEMPLATE_PATH)
    hoja = _hoja_del_dia(fecha)
    ws = wb[hoja]

    for item in seguimiento:
        nombre = item["nombre"]
        fila_top = _FILA_TOP.get(nombre)
        if fila_top:
            _escribir(ws, fila_top, 5, item.get("stock_inicial") or None)

        key = item["ingrediente_key"]
        fila_control = _FILA_CONTROL_STOCK.get(nombre)
        if fila_control:
            cocina = stock_cocina.get(key) or {}
            _escribir(ws, fila_control, _COL_STOCK_INFORMADO, cocina.get("cantidad_informada"))
            desglose = cocina.get("mermas_desglose") or {}
            for causa, col in _COLS_MERMAS_CAUSA.items():
                _escribir(ws, fila_control, col, desglose.get(causa))

        fila_entrega = _FILA_ENTREGAS_COCINA.get(nombre)
        if fila_entrega:
            _escribir(ws, fila_entrega, _COL_ENTREGA_CANTIDAD, entregas_bodega.get(key))

    for p in proteinas:
        fila = _FILA_BASE_PROTEINAS + p["orden"]
        _escribir(ws, fila, _COL_PROT_CONSUMIDA, p.get("cantidad_consumida"))
        _escribir(ws, fila, _COL_PROT_PRODUCIDA, p.get("cantidad_producida"))
        _escribir(ws, fila, _COL_PROT_MERMAS, p.get("mermas"))

    for p in pasteleria:
        fila = _FILA_PASTELERIA.get(p["producto_nombre"])
        if fila:
            _escribir(ws, fila, _COL_PASTELERIA_CANTIDAD, p.get("cantidad_producida"))

    for c in chocolates:
        fila = _FILA_CHOCOLATES.get(c["producto_nombre"])
        if fila:
            _escribir(ws, fila, _COL_CHOC_ENTREGADA, c.get("cantidad_entregada"))
            _escribir(ws, fila, _COL_CHOC_UTILIZADA, c.get("cantidad_utilizada"))

    fila_venta = _FILA_VENTAS_INICIO
    for v in ventas:
        _escribir(ws, fila_venta, _COL_VENTAS_CODIGO, v["plato_sku"])
        _escribir(ws, fila_venta, _COL_VENTAS_CANTIDAD, v["cantidad"])
        fila_venta += 1

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
