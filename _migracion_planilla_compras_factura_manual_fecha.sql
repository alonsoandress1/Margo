-- planilla_compras_factura_manual no guardaba la fecha de la factura, asi
-- que cada vez que se abria Planilla de Compras (de CUALQUIER mes) habia
-- que traer la tabla entera para saber cuales aplicaban -- inofensivo hoy
-- porque son pocas filas (son la excepcion, no la norma), pero crece sin
-- limite con los anios y ese "id IN (...)" se manda entero a Odoo en cada
-- consulta. Con invoice_date guardado, se puede filtrar por mes antes de
-- armar esa lista. Las filas existentes quedan con invoice_date null --
-- eso es SEGURO (no rompe nada): el codigo trata null como "incluir
-- siempre", igual que el comportamiento de antes de esta migracion.
alter table planilla_compras_factura_manual add column if not exists invoice_date date;
