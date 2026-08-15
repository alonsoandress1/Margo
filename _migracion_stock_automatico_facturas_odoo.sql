-- Alimentar el stock de Bodega automaticamente al crear una factura desde
-- Facturas Odoo (antes solo se alimentaba a mano, o via Recepcion en
-- Bodega que ya no se usa). Pedido explicito del usuario.

-- 1) Enlace entre cada local y su empresa correspondiente en Odoo -- sin
-- esto no hay forma de saber a que local sumarle el stock de una factura.
alter table locales add column if not exists odoo_company_id integer;
comment on column locales.odoo_company_id is 'Id de res.company en Odoo que corresponde a este local -- se usa para saber a que local sumarle el stock al crear una factura en Facturas Odoo.';

update locales set odoo_company_id = 2 where nombre = 'Doña Delfina' and odoo_company_id is null;

-- 2) Lineas de facturas que NO se pudieron sumar solas al stock -- producto
-- todavia sin insumo asociado (odoo_mapping) o local sin odoo_company_id
-- mapeado. Se resuelven despues con el boton "Actualizar" (ver
-- inventario.py::reprocesar_stock_pendiente), una vez que exista el mapeo
-- que faltaba.
create table if not exists bodega_stock_pendiente (
    id                uuid primary key default gen_random_uuid(),
    dte_id            bigint not null,
    invoice_id        bigint,
    invoice_name      text,
    odoo_company_id   integer,
    local_id          uuid references locales(id),
    odoo_product_id   integer not null,
    producto_nombre   text not null,
    cantidad          numeric not null,
    proveedor_nombre  text,
    motivo            text not null check (motivo in ('sin_insumo', 'sin_local')),
    creado_en         timestamptz not null default now()
);
create index if not exists bodega_stock_pendiente_producto_idx on bodega_stock_pendiente(odoo_product_id);
