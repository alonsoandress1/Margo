-- Esquema inicial — Sistema de compras automatizado Margo/Nelí
-- Ejecutar en Supabase: Dashboard > SQL Editor > New query > pegar y correr.
--
-- Diseño: solo el backend (Render, con la service_role key) toca esta base.
-- El frontend nunca habla directo con Supabase, siempre pasa por la API.
-- Por eso no se usan políticas RLS — el control de acceso (Solicitante /
-- Administrador / Observador) vive en el backend, no en la base.

create extension if not exists "pgcrypto";

-- ── Locales ──────────────────────────────────────────────────────────
create table locales (
    id          uuid primary key default gen_random_uuid(),
    nombre      text not null unique,
    activo      boolean not null default true,
    created_at  timestamptz not null default now()
);

-- ── Usuarios (login propio, independiente de Odoo) ─────────────────────
create table usuarios (
    id             uuid primary key default gen_random_uuid(),
    email          text not null unique,
    password_hash  text not null,
    nombre         text not null,
    rol            text not null check (rol in ('solicitante', 'administrador', 'observador')),
    activo         boolean not null default true,
    created_at     timestamptz not null default now()
);

-- Locales asignados a cada usuario (solo aplica a rol solicitante;
-- administrador/observador ven todos los locales sin necesidad de filas aquí)
create table usuario_locales (
    usuario_id  uuid not null references usuarios(id) on delete cascade,
    local_id    uuid not null references locales(id) on delete cascade,
    primary key (usuario_id, local_id)
);

-- ── Platos (catálogo de artículos vendidos, importado desde el POS) ────
create table platos (
    id        uuid primary key default gen_random_uuid(),
    local_id  uuid not null references locales(id) on delete cascade,
    sku       text not null,
    nombre    text not null,
    unique (local_id, sku)
);

-- ── Recetas (predefinidas manualmente por Administrador, por plato) ────
create table recetas (
    id              uuid primary key default gen_random_uuid(),
    plato_id        uuid not null references platos(id) on delete cascade,
    ingrediente_key text,  -- referencia al insumo del catálogo de Proveedores, si ya está mapeado
    ingrediente     text not null,
    cantidad        numeric not null,
    unidad          text not null,
    updated_at      timestamptz not null default now(),
    updated_by      uuid references usuarios(id)
);

-- ── Par Stock de Bodega (por local, por insumo) ─────────────────────────
create table par_stock (
    local_id          uuid not null references locales(id) on delete cascade,
    ingrediente_key   text not null,
    unidad            text not null,
    categoria         text,
    par_cantidad      numeric not null,
    updated_at        timestamptz not null default now(),
    updated_by        uuid references usuarios(id),
    primary key (local_id, ingrediente_key)
);

-- ── Insumos a rastrear en Mermas -- copia identica de la planilla ──────
-- Independiente del catalogo de Proveedores/Par Stock: la idea es que
-- sea exactamente la misma lista de "Inventario Cocina Semanal", exista
-- o no todavia como producto de compra registrado.
create table mermas_seguimiento (
    local_id        uuid not null references locales(id) on delete cascade,
    ingrediente_key text not null,
    nombre          text not null,
    unidad          text not null,
    tramo           text not null default 'kg' check (tramo in ('kg', 'unidades')),  -- 'kg' tiene columna Reutilizar en Mermas, 'unidades' no -- igual que el Excel real
    created_at      timestamptz not null default now(),
    primary key (local_id, ingrediente_key)
);

-- ── Movimientos de Bodega (ledger append-only, nunca editar/borrar) ────
create table bodega_movimientos (
    id                uuid primary key default gen_random_uuid(),
    local_id          uuid not null references locales(id) on delete cascade,
    ingrediente_key   text not null,
    tipo              text not null check (tipo in ('ingreso', 'egreso', 'ajuste')),
    cantidad          numeric not null,
    origen            text,
    ref               text,
    nota              text,
    fecha             timestamptz not null default now(),
    created_by        uuid references usuarios(id)
);
create index on bodega_movimientos (local_id, ingrediente_key);

-- ── Stock de Cocina (conteo diario -- manual o importado de la planilla) ──
create table stock_cocina (
    local_id          uuid not null references locales(id) on delete cascade,
    ingrediente_key   text not null,
    fecha             date not null,
    cantidad_informada numeric not null,
    mermas_total      numeric,  -- merma del dia ingresada a mano en la web
    mermas_desglose   jsonb,  -- {produccion, defectuosos, clientes, cortesia, reutilizar} -- solo si vino de la planilla
    created_by        uuid references usuarios(id),
    created_at        timestamptz not null default now(),
    primary key (local_id, ingrediente_key, fecha)
);

-- ── Producción interna de Cocina -- copia identica de los 3 bloques del
-- Excel ("Entregas de proteínas para producciones de cocina", "Registro
-- Producciones Pastelería", "Registro de Chocolates"). En los tres, la
-- IDENTIDAD del proceso (que materia prima -> que producto, o que producto
-- de pastelería/chocolate) es un catalogo FIJO -- nadie la escribe a mano,
-- solo se cargan las cantidades del dia. Mismo patron que mermas_seguimiento
-- (catalogo) + stock_cocina (valores diarios).

-- Bloque "Entregas de proteínas para producciones de cocina"
create table produccion_proteinas_recetas (
    id                     uuid primary key default gen_random_uuid(),
    local_id               uuid not null references locales(id) on delete cascade,
    orden                  integer not null,
    materia_prima_nombre   text not null,
    materia_prima_unidad   text not null,
    producto_final_nombre  text,     -- null si esa materia prima no tiene producto final en el Excel (ej. Almejas Julianas)
    producto_final_key     text,     -- ingrediente_key en mermas_seguimiento, si el producto final se rastrea ahi
    producto_final_unidad  text
);
create index on produccion_proteinas_recetas (local_id, orden);

create table produccion_proteinas_diaria (
    receta_id           uuid not null references produccion_proteinas_recetas(id) on delete cascade,
    fecha                date not null,
    cantidad_consumida  numeric,
    cantidad_producida  numeric,
    mermas              numeric,
    created_by          uuid references usuarios(id),
    updated_at          timestamptz not null default now(),
    primary key (receta_id, fecha)
);

-- Bloque "Registro Producciones Pastelería"
create table pasteleria_seguimiento (
    local_id         uuid not null references locales(id) on delete cascade,
    producto_key     text not null,  -- ingrediente_key en mermas_seguimiento
    producto_nombre  text not null,
    unidad           text not null,
    primary key (local_id, producto_key)
);

create table pasteleria_diaria (
    local_id            uuid not null references locales(id) on delete cascade,
    producto_key        text not null,
    fecha               date not null,
    cantidad_producida  numeric,
    created_by          uuid references usuarios(id),
    updated_at          timestamptz not null default now(),
    primary key (local_id, producto_key, fecha)
);

-- Bloque "Registro de Chocolates"
create table chocolates_seguimiento (
    local_id         uuid not null references locales(id) on delete cascade,
    producto_key     text not null,  -- ingrediente_key en mermas_seguimiento
    producto_nombre  text not null,
    unidad           text not null,
    primary key (local_id, producto_key)
);

create table chocolates_diaria (
    local_id            uuid not null references locales(id) on delete cascade,
    producto_key        text not null,
    fecha               date not null,
    cantidad_entregada  numeric,
    cantidad_utilizada  numeric,
    created_by          uuid references usuarios(id),
    updated_at          timestamptz not null default now(),
    primary key (local_id, producto_key, fecha)
);

-- ── Historial de ventas por plato (para el motor de pronostico) ────────
-- Se llena importando la planilla semanal de mermas (hoja "VENTAS" de
-- cada dia) -- es la base de datos que Fase B (pronostico a 3 dias)
-- necesita acumular antes de poder proyectar nada.
create table ventas_historial (
    id          uuid primary key default gen_random_uuid(),
    local_id    uuid not null references locales(id) on delete cascade,
    fecha       date not null,
    plato_id    uuid references platos(id),
    plato_sku   text not null,
    plato_nombre text not null,
    cantidad    numeric not null,
    created_by  uuid references usuarios(id),
    created_at  timestamptz not null default now(),
    unique (local_id, fecha, plato_sku)
);
create index on ventas_historial (local_id, fecha);

-- ── Receta embebida en el bloque VENTAS del Excel real (filas 66-153) --
-- copia exacta, sembrada una sola vez por local. Desacoplada a propósito
-- de la tabla `recetas` (esa es del módulo de Compras/Pedidos, un sistema
-- distinto sin relación con el Excel de Mermas) -- el consumo de insumo por
-- venta en Mermas usa SOLO esta tabla, igual que la fórmula SUMPRODUCT real.
create table ventas_recetas (
    id                  uuid primary key default gen_random_uuid(),
    local_id            uuid not null references locales(id) on delete cascade,
    plato_sku           text not null,
    plato_nombre        text not null,
    ingrediente_key     text,  -- null si el insumo no está en mermas_seguimiento (ej. Ostiones, Jamón de Pavo)
    ingrediente_nombre  text not null,
    cantidad            numeric not null,
    unidad              text not null
);
create index on ventas_recetas (local_id, plato_sku);

-- ── Proveedores (catálogo, solo administrador lo gestiona) ─────────────
create table proveedores (
    id                uuid primary key default gen_random_uuid(),
    nombre            text not null,
    odoo_supplier_id  integer not null,  -- res.partner id en Odoo, el admin lo verifica el mismo
    usa_odoo          boolean not null default false,  -- true = se genera OC real en Odoo; false = se avisa por correo
    activo            boolean not null default true,
    created_at        timestamptz not null default now()
);

-- ── Mapeo de insumos a Odoo (producto/proveedor/precio/formato) ────────
-- Un mismo ingrediente_key puede tener hasta 3 filas (una por proveedor);
-- el sistema elige la de menor precio al generar la sugerencia/OC.
create table odoo_mapping (
    id               uuid primary key default gen_random_uuid(),
    ingrediente_key  text not null,
    proveedor_id     uuid references proveedores(id),
    ref              text,
    odoo_id          integer not null,
    odoo_name        text not null,
    supplier_id      integer not null,
    supplier_name    text not null,
    price            numeric not null default 0,
    currency         text not null default 'CLP',
    tamano_empaque   numeric,  -- null = a granel; ej. 1.6 = viene en paquetes de 1.6 kg
    last_sync        timestamptz,
    unique (ingrediente_key, proveedor_id)
);
create index on odoo_mapping (ingrediente_key);

-- ── Configuración de notificaciones por correo (proveedores sin Odoo) ──
create table configuracion_email (
    id            uuid primary key default gen_random_uuid(),
    destinatario  text not null,
    cc            text,  -- direcciones adicionales separadas por coma
    updated_at    timestamptz not null default now(),
    updated_by    uuid references usuarios(id)
);

-- ── Pedidos (sugerencia → punto humano #1: aceptar/rechazar/editar) ────
create table pedidos (
    id            uuid primary key default gen_random_uuid(),
    local_id      uuid not null references locales(id) on delete cascade,
    fecha         date not null default current_date,
    estado        text not null default 'pendiente'
                  check (estado in ('pendiente', 'aprobado', 'rechazado', 'editado')),
    items         jsonb not null,       -- [{ingrediente_key, cantidad_sugerida, cantidad_final, precio}, ...]
    favorito      boolean not null default false,
    creado_por    uuid references usuarios(id),
    revisado_por  uuid references usuarios(id),
    revisado_at   timestamptz,
    created_at    timestamptz not null default now()
);

-- ── PO Tracking (acciones de compra: OC real en Odoo, o aviso por correo) ──
create table po_tracking (
    id            uuid primary key default gen_random_uuid(),
    tipo          text not null default 'odoo' check (tipo in ('odoo', 'email')),
    po_id         integer,       -- solo si tipo = 'odoo'
    po_name       text,          -- solo si tipo = 'odoo'
    local_id      uuid not null references locales(id) on delete cascade,
    pedido_id     uuid references pedidos(id),
    proveedor     text not null,
    categoria     text,
    creado_por    uuid references usuarios(id),
    fecha         timestamptz not null default now()
);
create index on po_tracking (local_id);

-- ── Facturas de proveedor (Odoo) ya aceptadas -- ingreso a Bodega ───────
-- Detectar/aceptar: se listan facturas nuevas de Odoo, un admin revisa y
-- acepta cada una, recien ahi se registra el ingreso real. Este registro
-- evita procesar la misma factura dos veces.
create table factura_tracking (
    id                uuid primary key default gen_random_uuid(),
    odoo_invoice_id   integer not null unique,
    odoo_invoice_name text not null,
    proveedor         text not null,
    local_id          uuid references locales(id),
    pedido_id         uuid references pedidos(id),
    items             jsonb not null default '[]',
    procesada_por     uuid references usuarios(id),
    procesada_en      timestamptz not null default now()
);
create index on factura_tracking (local_id);

-- ── Seed inicial: el local piloto ───────────────────────────────────────
insert into locales (nombre) values ('Doña Delfina');
