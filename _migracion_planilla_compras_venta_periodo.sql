-- Venta del periodo ($) por mes -- se ingresa a mano (igual que en el
-- Excel real, no viene de ningun sistema todavia) para poder calcular el
-- % Costo Venta = (compras Alimentos+Barra) / (venta neta), la misma
-- formula que ya usaba la planilla original.
create table if not exists planilla_compras_venta_periodo (
  anio int not null,
  mes int not null,
  venta_periodo numeric not null,
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now(),
  primary key (anio, mes)
);
