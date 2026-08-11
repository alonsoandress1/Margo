-- Evita condicion de carrera: si el mismo DTE se encola dos veces casi al
-- mismo tiempo (doble clic, dos pestanas, etc.), el chequeo "todavia no
-- tiene factura" en Odoo no alcanza a detectarlo porque crear la factura
-- demora varios segundos -- las dos pasan el chequeo antes de que la
-- primera termine de escribir el resultado. Un indice unico a nivel de
-- base de datos si lo bloquea, de forma atomica, sin importar el timing:
-- solo puede haber UN item pendiente/procesando por DTE a la vez.
create unique index if not exists facturas_dte_cola_dte_activo_idx
  on facturas_dte_cola (dte_id)
  where estado in ('pendiente', 'procesando');
