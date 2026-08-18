-- Corre esto en el SQL Editor de Supabase para que dos "Vincular"
-- concurrentes del mismo proveedor nuevo (mismo odoo_partner_id) no
-- puedan crear dos filas duplicadas en Proveedores -- el backend ya
-- espera este indice para resolver la carrera (ver inventario.py::
-- _resolver_proveedor).

create unique index if not exists proveedores_odoo_supplier_id_unico
  on proveedores (odoo_supplier_id);
