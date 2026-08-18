-- Corre esto en el SQL Editor de Supabase para activar la proteccion
-- contra reimportaciones duplicadas al descontar stock por ventas TCPOS
-- (bodega_service.py::registrar_venta_descuento).
--
-- Sin este indice, reimportar el reporte de ventas de un mismo dia (ej.
-- corrida manual despues del cron, o una correccion) podria crear DOS
-- filas de egreso para el mismo local+insumo+dia, duplicando el
-- descuento en el calculo de stock. La fecha para este origen siempre
-- se guarda normalizada a medianoche UTC, igual que entrega_cocina.

create unique index if not exists bodega_movimientos_venta_tcpos_unica
  on bodega_movimientos (local_id, ingrediente_key, fecha)
  where origen = 'venta_tcpos';
