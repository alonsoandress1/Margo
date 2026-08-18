-- Corre esto en el SQL Editor de Supabase.
--
-- Cola en segundo plano para traer la Venta del Periodo desde TCPOS
-- (Planilla de Compras). El reporte "Financial overview" del mes corrido
-- puede tardar mas de 90s -- confirmado en vivo que crece a medida que
-- avanza el mes -- muy por encima de lo que una peticion HTTP sincrona
-- puede esperar sin arriesgarse al timeout de proxy de Render (~100s).
-- Mismo patron que facturas_dte_cola (creacion de facturas en Odoo):
-- encolar y hacer polling del estado en vez de bloquear la peticion.
create table if not exists planilla_compras_venta_periodo_job (
  id uuid primary key default gen_random_uuid(),
  anio integer not null,
  mes integer not null,
  estado text not null default 'pendiente' check (estado in ('pendiente','procesando','completado','error')),
  venta_periodo numeric,
  desde date,
  hasta date,
  error_mensaje text,
  creado_por uuid references usuarios(id),
  creado_en timestamptz not null default now()
);
create index if not exists planilla_compras_venta_periodo_job_mes_idx
  on planilla_compras_venta_periodo_job (anio, mes, creado_en desc);

-- Evita condicion de carrera: solo un job pendiente/procesando a la vez
-- por mes (dos clics casi simultaneos en "Traer de TCPOS").
create unique index if not exists planilla_compras_venta_periodo_job_activo_idx
  on planilla_compras_venta_periodo_job (anio, mes)
  where estado in ('pendiente', 'procesando');
