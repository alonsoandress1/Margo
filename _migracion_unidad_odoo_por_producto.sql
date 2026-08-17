-- Corre esto en el SQL Editor de Supabase antes de usar el nuevo campo
-- "Unidad de compra (Odoo)" en Proveedores.
--
-- Agrega un campo independiente de la "unidad" original del insumo
-- (Und/Kgs/Porcion, fija desde que se crea el producto) para poder definir
-- -- y editar despues, en cualquier momento -- que unidad de medida se le
-- impone a Odoo al crear una OC/factura para ESE producto en particular.
-- Si queda en null, se usa la que ese producto tenga configurada por
-- defecto en su propia ficha de Odoo.

alter table odoo_mapping add column if not exists unidad_odoo text check (unidad_odoo in ('un', 'kg'));

comment on column odoo_mapping.unidad_odoo is
  'Unidad que se le impone a Odoo en purchase.order.line.product_uom al generar la OC/factura para este producto -- null = usar la que ese producto tenga por defecto en Odoo.';
