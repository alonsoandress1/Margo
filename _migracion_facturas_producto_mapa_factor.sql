-- Factor de conversion por mapeo (proveedor + codigo de producto) en Ingreso
-- de Facturas -- algunos proveedores declaran una cantidad que en realidad
-- representa un bulto con mas unidades reales (ej. DTE dice "1 azucar" pero
-- son 10 kg). Se guarda un factor multiplicador: cantidad_real = qty del DTE
-- x factor_conversion, y el precio unitario real = item_price / factor_conversion
-- (el total de la linea no cambia, solo se reparte distinto entre cantidad y
-- precio). Default 1 = sin cambios, comportamiento actual.
--
-- Aditiva -- no toca los mapeos ya aprendidos, todos quedan con factor 1.

alter table facturas_producto_mapa
  add column if not exists factor_conversion numeric not null default 1;
