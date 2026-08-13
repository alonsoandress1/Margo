-- Descuento POR LINEA (no por factura completa) en Ingreso de Facturas --
-- reemplaza el diseño anterior (facturas_dte_descuento, un solo % por
-- factura) que resulto incorrecto: el descuento real varia linea por linea
-- (confirmado con OC reales de CCU/Andina, distintos % en la misma
-- factura), no es un valor parejo. El DTE nunca trae el descuento poblado
-- por linea, asi que el admin lo confirma a mano, producto por producto,
-- desde la pantalla. Default 0 (sin descuento) para cualquier linea sin
-- fila aca. Aditiva, no toca nada existente -- la tabla vieja
-- facturas_dte_descuento queda sin uso, se puede dejar o borrar despues.
create table if not exists facturas_dte_linea_descuento (
  dte_linea_id integer primary key,
  descuento_pct numeric not null,
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now()
);
