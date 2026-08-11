-- Tabla de impuestos por producto para el ingreso manual de facturas DTE.
-- Los impuestos de Odoo son por EMPRESA (cada local tiene su propio id de
-- "IVA 19% Compra"), así que guardamos el NOMBRE del impuesto, no el id --
-- en cada empresa se busca el impuesto real por ese nombre al crear la
-- factura. Si un producto no tiene fila aquí, se usa 'IVA 19% Compra' por
-- defecto (el caso normal para casi todo).
create table if not exists facturas_producto_impuesto (
  odoo_product_id bigint primary key,
  odoo_product_name text not null,
  impuesto_nombre text not null default 'IVA 19% Compra',
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now()
);
