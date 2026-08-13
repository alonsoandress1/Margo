-- Agrega proveedor_rut y odoo_product_id a facturas_dte_linea_descuento, y
-- proveedor_rut a facturas_dte_linea_manual -- para poder mostrar de
-- REFERENCIA (no autocompletar -- el descuento real varia factura a
-- factura, confirmado con datos reales de CCU/Andina) el ultimo % usado
-- para este producto + este proveedor puntual, separado por proveedor como
-- el resto de las confirmaciones de este sistema (impuestos, factor de
-- conversion). Columnas nullable -- las filas viejas quedan sin dato de
-- referencia, no rompe nada.
alter table facturas_dte_linea_descuento add column if not exists proveedor_rut text;
alter table facturas_dte_linea_descuento add column if not exists odoo_product_id integer;
create index if not exists facturas_dte_linea_descuento_ref_idx
  on facturas_dte_linea_descuento(proveedor_rut, odoo_product_id, actualizado_en desc);

alter table facturas_dte_linea_manual add column if not exists proveedor_rut text;
create index if not exists facturas_dte_linea_manual_ref_idx
  on facturas_dte_linea_manual(proveedor_rut, odoo_product_id, agregado_en desc);
