-- Descuento por DTE en Ingreso de Facturas -- el % de descuento con el que
-- se crea la OC (campo real de Odoo purchase.order.line.discount, no se
-- baja el precio unitario) se calcula por defecto comparando el Neto
-- declarado en la cabecera del DTE contra la suma sin descuento de las
-- lineas -- pero el admin puede confirmarlo o corregirlo a mano desde la
-- pantalla antes de crear la factura. Aditiva, no toca nada existente.
create table if not exists facturas_dte_descuento (
  dte_id integer primary key,
  descuento_pct numeric not null,
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now()
);
