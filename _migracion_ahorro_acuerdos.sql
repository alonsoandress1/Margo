-- Corre esto en el SQL Editor de Supabase para activar las alertas de
-- precio y el reporte "Ahorro por Acuerdos Comerciales".
--
-- precio_negociado es el precio pactado con ESE proveedor para ESE insumo
-- (distinto del campo Precio que ya existia, que es de uso libre). Se
-- carga a mano en Proveedores, junto a Formato/Unidad Odoo.
--
-- historial_precios_compra guarda el precio REAL de cada linea de cada
-- factura creada desde Facturas Odoo, desde ahora en adelante (no hay
-- forma de reconstruir el pasado) -- es la base del reporte mensual.
--
-- alertas_precio_factura se llena sola cuando el precio real de una
-- factura supera el precio_negociado de ese proveedor puntual.

alter table odoo_mapping add column if not exists precio_negociado numeric;

comment on column odoo_mapping.precio_negociado is
  'Precio pactado en un acuerdo comercial con este proveedor para este insumo -- null = sin acuerdo. Distinto del campo price (de uso libre).';

create table if not exists historial_precios_compra (
    id              uuid primary key default gen_random_uuid(),
    ingrediente_key text not null,
    proveedor_id    uuid references proveedores(id),
    precio          numeric not null,
    cantidad        numeric not null,
    invoice_name    text,
    dte_id          bigint,
    fecha           timestamptz not null default now()
);
create index if not exists historial_precios_key_idx on historial_precios_compra(ingrediente_key, fecha desc);

create table if not exists alertas_precio_factura (
    id                uuid primary key default gen_random_uuid(),
    dte_id            bigint,
    invoice_name      text,
    ingrediente_key   text not null,
    proveedor_id      uuid references proveedores(id),
    precio_real       numeric not null,
    precio_negociado  numeric not null,
    fecha             timestamptz not null default now(),
    resuelta          boolean not null default false
);
create index if not exists alertas_precio_pendientes_idx on alertas_precio_factura(resuelta) where not resuelta;
