-- Categoria de gasto (Tipo) por PROVEEDOR para la Planilla de Compras --
-- replica el Excel "PLANILLA DE COMPRAS OFICIAL 2026". El Tipo se asigna
-- UNA VEZ por proveedor (ej. Paltas Royal = AL) y se reusa siempre; vive
-- solo aqui, nunca se escribe en Odoo.
--   AL = Alimentos
--   BA = Barra
--   GF = Gastos Fijos
--   OT = Otros
--   AS = Aseo
create table if not exists planilla_compras_proveedor_tipo (
  odoo_partner_id bigint primary key,
  proveedor_nombre text not null,
  tipo text not null check (tipo in ('AL','BA','GF','OT','AS')),
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now()
);
