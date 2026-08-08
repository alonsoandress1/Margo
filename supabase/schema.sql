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

-- ── Recetas (predefinidas manualmente por Administrador, por local) ────
create table recetas (
    id            uuid primary key default gen_random_uuid(),
    local_id      uuid not null references locales(id) on delete cascade,
    plato_sku     text not null,
    plato_nombre  text not null,
    ingrediente   text not null,
    cantidad      numeric not null,
    unidad        text not null,
    updated_at    timestamptz not null default now(),
    updated_by    uuid references usuarios(id)
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

-- ── Stock de Cocina (conteo manual diario, hoy vía Excel Mermas) ───────
create table stock_cocina (
    local_id          uuid not null references locales(id) on delete cascade,
    ingrediente_key   text not null,
    fecha             date not null,
    cantidad_informada numeric not null,
    created_by        uuid references usuarios(id),
    created_at        timestamptz not null default now(),
    primary key (local_id, ingrediente_key, fecha)
);

-- ── Mapeo de insumos a Odoo (producto/proveedor/precio) ─────────────────
create table odoo_mapping (
    ingrediente_key  text primary key,
    ref              text,
    odoo_id          integer not null,
    odoo_name        text not null,
    supplier_id      integer not null,
    supplier_name    text not null,
    price            numeric not null default 0,
    currency         text not null default 'CLP',
    last_sync        timestamptz
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

-- ── PO Tracking (link local ↔ Orden de Compra creada en Odoo) ──────────
create table po_tracking (
    id            uuid primary key default gen_random_uuid(),
    po_id         integer not null,
    po_name       text not null,
    local_id      uuid not null references locales(id) on delete cascade,
    pedido_id     uuid references pedidos(id),
    proveedor     text not null,
    categoria     text,
    creado_por    uuid references usuarios(id),
    fecha         timestamptz not null default now()
);
create index on po_tracking (local_id);

-- ── Seed inicial: el local piloto ───────────────────────────────────────
insert into locales (nombre) values ('Doña Delfina');
