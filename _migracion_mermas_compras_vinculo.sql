create table if not exists mermas_compras_vinculo (
  id uuid primary key default gen_random_uuid(),
  local_id uuid not null references locales(id),
  mermas_ingrediente_key text not null,
  compras_ingrediente_key text not null,
  vinculado_por uuid references usuarios(id),
  vinculado_en timestamptz not null default now(),
  unique (local_id, mermas_ingrediente_key)
);
