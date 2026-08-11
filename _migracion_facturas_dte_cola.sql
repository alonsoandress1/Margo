-- Cola de creacion de facturas (Ingreso de Facturas): crear una factura en
-- Odoo implica 6 llamadas seguidas (OC, confirmar, recibir, facturar, fijar
-- fecha, fijar folio) y puede demorar varios segundos. En vez de bloquear
-- al usuario mientras espera, el clic en "Crear Factura en Odoo" encola el
-- pedido y un proceso en segundo plano lo va resolviendo -- asi se puede
-- seguir revisando y confirmando otras facturas mientras tanto.
create table if not exists facturas_dte_cola (
  id uuid primary key default gen_random_uuid(),
  dte_id bigint not null,
  folio text not null,
  proveedor_nombre text not null,
  estado text not null default 'pendiente' check (estado in ('pendiente','procesando','completado','error')),
  invoice_id bigint,
  invoice_name text,
  error_mensaje text,
  creado_por uuid references usuarios(id),
  creado_en timestamptz not null default now(),
  actualizado_en timestamptz not null default now()
);
create index if not exists facturas_dte_cola_estado_idx on facturas_dte_cola(estado);
