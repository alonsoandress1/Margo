-- Corre esto en el SQL Editor de Supabase para activar la proteccion
-- contra doble clic al registrar una entrega de Bodega -> Cocina
-- (Mermas -- bodega_service.py::registrar_entrega_cocina).
--
-- Sin este indice, dos clics (o dos pestañas) casi simultaneos podian
-- crear DOS filas de entrega para el mismo local+insumo+dia, duplicando
-- la cantidad entregada en el calculo de stock y mermas. La fecha para
-- este origen siempre se guarda normalizada a medianoche UTC, asi que
-- no hace falta una columna calculada aparte.

create unique index if not exists bodega_movimientos_entrega_cocina_unica
  on bodega_movimientos (local_id, ingrediente_key, fecha)
  where origen = 'entrega_cocina';
