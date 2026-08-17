-- Corre esto en el SQL Editor de Supabase para poder editar la unidad base
-- (Und/Kgs/Porcion) de un insumo ya cargado en Proveedores.
--
-- La unidad es parte de ingrediente_key ("nombre||unidad"), y ese mismo
-- insumo puede repetirse en odoo_mapping (uno por proveedor que lo vende),
-- en Par Stock de varios locales, y en el historial de bodega_movimientos /
-- stock_cocina / ventas_recetas -- por eso el cambio se hace todo junto,
-- dentro de una sola funcion (una sola transaccion): si algo choca (ya
-- existe otro insumo con el nombre+unidad nuevo en alguna de esas tablas),
-- se aborta completo y no queda nada a medio migrar.

create or replace function renombrar_unidad_insumo(p_old_key text, p_new_key text, p_nueva_unidad text)
returns void
language plpgsql
as $$
begin
  if p_old_key = p_new_key then
    return;
  end if;

  if exists (
    select 1 from odoo_mapping a
    join odoo_mapping b on b.proveedor_id = a.proveedor_id
    where a.ingrediente_key = p_old_key and b.ingrediente_key = p_new_key
  ) then
    raise exception 'Ya existe un producto con ese nombre y esa unidad para uno de los proveedores que venden este insumo';
  end if;

  if exists (
    select 1 from par_stock a
    join par_stock b on b.local_id = a.local_id
    where a.ingrediente_key = p_old_key and b.ingrediente_key = p_new_key
  ) then
    raise exception 'Ya existe un insumo con ese nombre y esa unidad en el Par Stock de uno de los locales que tienen este insumo';
  end if;

  update odoo_mapping set ingrediente_key = p_new_key where ingrediente_key = p_old_key;
  update par_stock set ingrediente_key = p_new_key, unidad = p_nueva_unidad where ingrediente_key = p_old_key;
  update bodega_movimientos set ingrediente_key = p_new_key where ingrediente_key = p_old_key;
  update stock_cocina set ingrediente_key = p_new_key where ingrediente_key = p_old_key;
  update ventas_recetas set ingrediente_key = p_new_key where ingrediente_key = p_old_key;
end;
$$;
