-- DTE marcados como "ingresada manualmente" en Ingreso de Facturas -- para
-- cuando alguien ya creo la factura real directo en Odoo (por fuera de esta
-- pantalla) y el DTE quedo sin invoice_id vinculado (no hay forma
-- automatica de saberlo). Marcarlo saca el DTE de la lista de pendientes
-- sin tocar nada en Odoo -- reversible (DELETE /facturas-dte/{dte_id}/marcar-manual).
create table if not exists facturas_dte_ingresado_manual (
  dte_id integer primary key,
  marcado_por uuid references usuarios(id),
  marcado_en timestamptz not null default now()
);
