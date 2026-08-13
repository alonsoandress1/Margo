-- Lineas AGREGADAS A MANO en Ingreso de Facturas -- para un producto/cargo
-- que el proveedor declaro en el Neto/Total del DTE pero que NO vino como
-- linea propia en el XML (ej. flete, envase, un item que no parseo). No se
-- toca l10n_cl.supplier.xml.line (esa tabla es la copia fiel de lo que
-- declaro el SII, no se debe adulterar) -- estas lineas se guardan aparte y
-- se suman a las reales del DTE recien al armar la Orden de Compra
-- (_ejecutar_creacion). No soportado para Doña Sofía (reusa una OC ya
-- confirmada de antes, no se le pueden agregar lineas nuevas por aca).
create table if not exists facturas_dte_linea_manual (
  id bigint generated always as identity primary key,
  dte_id integer not null,
  odoo_product_id integer not null,
  odoo_product_name text not null,
  qty numeric not null,
  precio_unitario numeric not null,
  descuento_pct numeric not null default 0,
  agregado_por uuid references usuarios(id),
  agregado_en timestamptz not null default now()
);
create index if not exists facturas_dte_linea_manual_dte_id_idx on facturas_dte_linea_manual(dte_id);
