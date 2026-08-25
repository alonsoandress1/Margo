-- Agenda de pedidos por proveedor -- necesaria para automatizar (con
-- revision humana) los pedidos a Doña Sofía:
--   dias_entrega: cuantos dias pasan entre generar la OC y que llegue la
--     mercaderia -- se usa para sumar el consumo proyectado de esos dias a
--     la sugerencia de compra (ver consumo_promedio_por_dia_semana en
--     bodega_service.py). 0 = comportamiento identico al de siempre.
--   dias_pedido: en que dias de la semana corresponde generar el pedido
--     (0=Lunes .. 6=Domingo, misma convencion que date.weekday() ya usada
--     en mermas.py) -- dispara la tarjeta de recordatorio en Vista
--     Resumen, nunca genera nada solo.
alter table proveedores add column if not exists dias_entrega integer not null default 0;
alter table proveedores add column if not exists dias_pedido integer[] not null default '{}';

-- Doña Sofía: pide con 2 dias de anticipacion, los dias Lunes/Miercoles/Sabado.
update proveedores set dias_entrega = 2, dias_pedido = '{0,2,5}' where usa_odoo = true;
