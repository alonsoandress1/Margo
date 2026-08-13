-- Facturas SIN Orden de Compra detras (invoice_origin vacio en Odoo) que
-- de todas formas deben aparecer en la Planilla de Compras -- para
-- facturas ingresadas a mano directo en Odoo (boton "Ingresada
-- Manualmente" en Facturas SII), que la planilla normalmente excluye
-- porque se ven identicas a un gasto administrativo (arriendo, seguro,
-- telefonia) que nunca pasa por una OC. Se llena sola desde
-- marcar_ingresada_manual cuando encuentra la factura real y esta no
-- tiene invoice_origin.
create table if not exists planilla_compras_factura_manual (
  factura_id integer primary key,
  agregado_por uuid references usuarios(id),
  agregado_en timestamptz not null default now()
);

-- Guarda a que factura real de Odoo quedo vinculado un DTE al marcarlo
-- "Ingresada Manualmente" -- para poder deshacer el agregado a la
-- planilla si se desmarca por error.
alter table facturas_dte_ingresado_manual add column if not exists factura_id_vinculada integer;
