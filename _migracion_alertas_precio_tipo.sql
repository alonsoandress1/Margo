-- Corre esto en el SQL Editor de Supabase.
--
-- Distingue el tipo de alerta en alertas_precio_factura: 'sobreprecio' (ya
-- existia -- el proveedor de esta factura cobro mas caro que SU propio
-- precio pactado) vs. 'oportunidad' (nueva -- cualquier proveedor factura
-- mas barato que el mejor precio pactado vigente entre todos, para
-- evaluar cambiar de proveedor prioritario en ese insumo). Las alertas ya
-- existentes quedan como 'sobreprecio' por el default, sin backfill manual.

alter table alertas_precio_factura add column if not exists tipo text not null default 'sobreprecio'
  check (tipo in ('sobreprecio', 'oportunidad'));
