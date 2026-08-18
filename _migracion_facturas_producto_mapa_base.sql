-- Corre esto en el SQL Editor de Supabase (es seguro aunque la tabla ya
-- exista -- "create table if not exists" no toca nada si ya esta ahi).
--
-- Reconstruye la definicion base de facturas_producto_mapa: el aprendizaje
-- de "codigo de proveedor -> product_id de Odoo" que evita reconfirmar
-- cada factura a mano (ver facturas_dte.py). Esta tabla se creo directo en
-- el SQL Editor de Supabase en su momento y nunca quedo versionada en el
-- repo -- auditoria de codigo del 2026-08-18 encontro que si la base se
-- recreara desde cero con solo lo que hay en el repo, esta tabla
-- simplemente no existiria (solo estaba versionado el alter table que le
-- agrega factor_conversion despues, ver _migracion_facturas_producto_mapa_factor.sql).

create table if not exists facturas_producto_mapa (
  id uuid primary key default gen_random_uuid(),
  proveedor_rut text not null,
  proveedor_nombre text,
  codigo_tipo text not null,
  codigo_valor text not null,
  odoo_product_id bigint not null,
  odoo_product_name text not null,
  confirmado_por uuid references usuarios(id),
  factor_conversion numeric not null default 1,
  unique (proveedor_rut, codigo_tipo, codigo_valor)
);
