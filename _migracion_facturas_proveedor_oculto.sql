-- Proveedores ocultos en Ingreso de Facturas -- para proveedores de uso
-- excepcional (una sola vez, o que otra persona/flujo procesa) que no
-- deberian seguir apareciendo en la lista de "pendientes". No borra ni
-- toca nada de Odoo -- solo deja de listarlos en /facturas-dte. Reversible
-- en cualquier momento (se puede volver a mostrar el proveedor).
create table if not exists facturas_proveedor_oculto (
  proveedor_rut text primary key,
  proveedor_nombre text not null,
  ocultado_por uuid references usuarios(id),
  ocultado_en timestamptz not null default now()
);
