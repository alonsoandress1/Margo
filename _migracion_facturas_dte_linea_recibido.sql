create table if not exists facturas_dte_linea_recibido (
  dte_linea_id integer primary key,
  cantidad_recibida numeric not null,
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now()
);
