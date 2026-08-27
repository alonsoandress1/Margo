-- Si falla por filas duplicadas ya existentes para la misma combinacion
-- (local_id, plato_sku, ingrediente_key), hay que limpiarlas primero.
create unique index if not exists ventas_recetas_local_plato_ingrediente_key
  on ventas_recetas (local_id, plato_sku, ingrediente_key);
