-- Corre esto en el SQL Editor de Supabase para activar la proteccion
-- contra doble clic al generar la OC de un pedido (POST /pedidos/{id}/generar-oc).
--
-- pedido_id como llave primaria = solo el primer clic puede reclamar un
-- pedido; el segundo clic (o pestaña) casi simultaneo choca contra la
-- llave unica y se rechaza con 409 en vez de crear una OC real duplicada
-- en Odoo. Si algo falla despues del reclamo (Odoo caido, credenciales,
-- correo), el backend borra la fila para permitir reintentar.

create table if not exists pedido_oc_claim (
    pedido_id uuid primary key references pedidos(id)
);
