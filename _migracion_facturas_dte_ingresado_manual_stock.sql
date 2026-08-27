alter table facturas_dte_ingresado_manual add column if not exists stock_cargado boolean not null default false;
