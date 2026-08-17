-- Corre esto en el SQL Editor de Supabase para que "Stock pendiente" en
-- Inventario pueda traer los datos reales de la factura (RUT del
-- proveedor, precio, unidad de medida real en Odoo) y asi poder vincular
-- un producto sin retipear nada.

alter table bodega_stock_pendiente
  add column if not exists proveedor_rut text,
  add column if not exists odoo_partner_id integer,
  add column if not exists precio numeric,
  add column if not exists uom_odoo_id integer,
  add column if not exists uom_odoo_nombre text;
