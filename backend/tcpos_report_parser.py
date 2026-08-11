"""Parser del reporte "Article Analysis" de TCPOS (PDF) -- solo lectura.

Extrae por fila: codigo (SKU del POS, mismo formato que platos.sku),
nombre, y "Pieces Sold" (cuantas veces se vendio ese articulo -- lo
que necesitamos para ventas_historial, no "Quantity Sold" que es para
articulos por peso/volumen y casi siempre viene vacio).

Usa pdfplumber en vez de separar el texto plano por espacios: el PDF
trae los montos en formato europeo (punto de miles, coma decimal) y
filas resumen (Group Total, Grand Total) que hay que descartar --
extraer por posicion real de tabla es mucho mas confiable. Validado
contra un reporte real: la suma de "Pieces Sold" de las filas
extraidas coincide exactamente con el "Grand Total" del reporte.
"""
from io import BytesIO

import pdfplumber

_FILAS_A_IGNORAR = {"Article", "Group", ""}


def parsear_article_analysis(pdf_bytes: bytes) -> list[dict]:
    """Retorna [{codigo, nombre, cantidad}, ...], una fila por articulo.
    No filtra por cantidad > 0 -- se guarda tal cual, incluye ventas en 0."""
    filas: list[dict] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            tablas = pagina.extract_tables()
            for tabla in tablas[1:]:  # tabla 0 de cada pagina es el resumen de parametros (Shops/Tills/...)
                for fila in tabla:
                    if not fila or not fila[0]:
                        continue
                    codigo = fila[0].strip()
                    if codigo in _FILAS_A_IGNORAR or codigo.endswith("Total"):
                        continue
                    if len(fila) < 5:
                        continue
                    nombre = (fila[1] or codigo).strip()
                    piezas_raw = (fila[4] or "0").strip()
                    try:
                        cantidad = int(piezas_raw)
                    except ValueError:
                        continue
                    filas.append({"codigo": codigo, "nombre": nombre, "cantidad": cantidad})
    return filas


def _monto_cl_a_float(texto: str) -> float:
    """'90.742.367,00' (miles con punto, decimales con coma) -> 90742367.0"""
    return float(texto.replace(".", "").replace(",", ".").replace("\n", ""))


def parsear_financial_overview_cash_to_deposit(pdf_bytes: bytes) -> float:
    """Reporte "Financial overview" de TCPOS -- extrae "Cash to deposit" de
    la fila Total de la tabla "Tills" (columnas: Shop/Till, Gross, Tip &
    Service, Discount, Net, Credit card, Voucher, Digital, Card, Debitor,
    Cheque, Cash, Other prepaym., Cash prepaym., Cash to deposit).

    No se indexa por posicion de columna -- el PDF desalinea la fila Total
    respecto al header (una celda de menos al principio). "Cash to
    deposit" es siempre el ULTIMO valor no vacio de la fila Total, eso es
    estable independiente del desalineo -- validado contra un reporte
    real (fila Total con 16 columnas, el ultimo valor no vacio coincidia
    con el "Cash to deposit" de la unica fila de datos)."""
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                if not tabla or not tabla[0] or tabla[0][0] != "Tills":
                    continue
                fila_total = next((f for f in tabla if f and f[0] == "Total"), None)
                if not fila_total:
                    continue
                valores = [c for c in fila_total if c not in (None, "")]
                if len(valores) < 2:
                    continue
                return _monto_cl_a_float(valores[-1])
    raise ValueError('No se encontró la fila "Total" de la tabla "Tills" en el reporte Financial overview')
