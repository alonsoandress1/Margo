-- Impuestos por producto para Ingreso de Facturas -- hasta 3 impuestos por
-- producto (ej. "IVA 19% Compra" + "Impuesto a la Carne 5%"), elegidos al
-- momento de matchear el producto de una linea del DTE. Reemplaza el diseño
-- anterior (un solo impuesto por producto, nunca se uso) por una fila por
-- (producto, impuesto) -- deja el limite de 3 como regla de la app, no del
-- esquema.
--
-- Los impuestos de Odoo son por EMPRESA (cada local tiene su propio id de
-- "IVA 19% Compra"), asi que se guarda el NOMBRE del impuesto, no el id --
-- en cada empresa se busca el impuesto real por ese nombre al crear la
-- factura. Si un producto no tiene ninguna fila aqui, Odoo aplica el
-- impuesto que ya tenga configurado el producto por defecto (el caso normal
-- para casi todo) -- esto es solo para los productos que necesitan algo
-- distinto/adicional.

-- Nota 2026-08-18: el "drop table" original de este archivo se cambio a
-- "create table if not exists" -- auditoria de codigo encontro que era el
-- unico archivo de migracion del repo que no era idempotente/seguro de
-- re-correr (los otros 22 usan "if not exists" en todos lados). Si esto
-- se hubiera vuelto a ejecutar por error (ej. al re-correr "todas las
-- migraciones pendientes" de una lista), habria borrado en silencio los
-- impuestos por producto ya configurados a mano, sin ningun aviso. Esta
-- version no necesita volver a correrse -- la tabla ya existe con datos
-- reales -- pero deja el archivo seguro de aca en adelante.

create table if not exists facturas_producto_impuesto (
  id uuid primary key default gen_random_uuid(),
  odoo_product_id bigint not null,
  odoo_product_name text not null,
  impuesto_nombre text not null,
  actualizado_por uuid references usuarios(id),
  actualizado_en timestamptz not null default now(),
  unique (odoo_product_id, impuesto_nombre)
);

create index if not exists facturas_producto_impuesto_producto_idx on facturas_producto_impuesto(odoo_product_id);
