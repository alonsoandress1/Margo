-- Limpieza masiva de "Facturas Odoo" pendientes que en realidad ya tienen
-- una factura real en Odoo (creada por otro camino, sin quedar vinculada
-- al DTE) -- version masiva del boton "Ingresada Manualmente" existente.
-- Caso real que la origino: Doña Estela, 2.782 de 3.167 DTE "pendientes"
-- ya tenian su factura real en Odoo. Aplicar eso a mano, uno por uno, no
-- es viable -- este job corre en segundo plano (misma logica que
-- facturas_dte_cola) y deja registro de cuantos se resolvieron.
create table if not exists facturas_dte_limpieza_masiva (
  id uuid primary key default gen_random_uuid(),
  odoo_company_id integer not null,
  desde date not null,
  hasta date not null,
  estado text not null default 'procesando' check (estado in ('procesando','completado','error')),
  total integer not null default 0,
  procesados integer not null default 0,
  vinculados integer not null default 0,
  ambiguos integer not null default 0,
  errores integer not null default 0,
  error_mensaje text,
  creado_por uuid references usuarios(id),
  creado_en timestamptz not null default now(),
  actualizado_en timestamptz not null default now()
);
create index if not exists facturas_dte_limpieza_masiva_estado_idx on facturas_dte_limpieza_masiva(estado);
