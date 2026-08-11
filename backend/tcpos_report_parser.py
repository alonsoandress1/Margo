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
