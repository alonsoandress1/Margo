-- Corre esto en el SQL Editor de Supabase.
--
-- Guarda la unidad ("kg"/"un") resuelta de forma confiable contra los ids
-- estandar de Odoo (product_uom_kgm/product_uom_unit) al momento de
-- procesar la factura -- en vez de que el frontend la adivine con un
-- match de texto sobre el nombre de la UoM (ver inventario.py::
-- listar_stock_pendiente y facturas_dte.py::_alimentar_stock_bodega).
-- Null si esa linea usa una UoM que no calza con ninguno de los dos ids
-- conocidos.

alter table bodega_stock_pendiente add column if not exists unidad_sugerida text;
