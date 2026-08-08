// Margo · Compras — frontend (vanilla JS, sin build step)
// El backend sirve estos archivos estáticos, así que la API está en el mismo origen.

const SECCIONES = [
  { id: 'pedidos',   label: 'Pedidos',              roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'inventario', label: 'Inventario',          roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'mermas',    label: 'Mermas',                roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'oc',        label: 'Órdenes de Compra',     roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'parstock',  label: 'Par Stock',             roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'recetas',   label: 'Recetas',               roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'locales',   label: 'Locales',                roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'usuarios',  label: 'Usuarios',               roles: ['administrador'], editRoles: ['administrador'] },
];

let state = {
  token: localStorage.getItem('token') || null,
  usuario: JSON.parse(localStorage.getItem('usuario') || 'null'),
  section: 'pedidos',
  locales: [],
};

function seccion(id) { return SECCIONES.find(s => s.id === id); }
function puedeVer(s) { return state.usuario && s.roles.includes(state.usuario.rol); }
function puedeEditar(s) { return state.usuario && s.editRoles.includes(state.usuario.rol); }

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Error ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- Auth ----------

function showLogin() {
  document.getElementById('login-view').hidden = false;
  document.getElementById('app-view').hidden = true;
}

function showApp() {
  document.getElementById('login-view').hidden = true;
  document.getElementById('app-view').hidden = false;
  document.getElementById('user-info').textContent =
    `${state.usuario.nombre} · ${state.usuario.rol}`;
  renderNav();
  renderView();
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('usuario');
  state.token = null;
  state.usuario = null;
  showLogin();
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  const btn = e.target.querySelector('button[type=submit]');
  errorEl.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Ingresando… (puede tardar hasta 1 min si el servidor estaba dormido)';
  try {
    const data = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    state.token = data.access_token;
    state.usuario = data.usuario;
    localStorage.setItem('token', state.token);
    localStorage.setItem('usuario', JSON.stringify(state.usuario));
    showApp();
  } catch (err) {
    errorEl.textContent = err.message === 'Failed to fetch'
      ? 'No se pudo conectar con el servidor. Intenta de nuevo en unos segundos.'
      : 'Email o contraseña incorrectos.';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Ingresar';
  }
});

document.getElementById('logout-btn').addEventListener('click', logout);

// ---------- Nav ----------

function renderNav() {
  const nav = document.getElementById('nav-list');
  nav.innerHTML = '';
  SECCIONES.forEach((s) => {
    if (!puedeVer(s)) return;
    const a = document.createElement('a');
    a.textContent = s.label;
    a.className = s.id === state.section ? 'active' : '';
    a.onclick = () => { state.section = s.id; renderNav(); renderView(); };
    nav.appendChild(a);
  });
}

// ---------- Views ----------

async function renderView() {
  const el = document.getElementById('view-content');
  el.innerHTML = '<p class="placeholder">Cargando…</p>';
  const s = seccion(state.section);
  try {
    if (state.section === 'pedidos') return renderPedidos(el, s);
    if (state.section === 'locales') return renderLocales(el, s);
    return renderPlaceholder(el, s);
  } catch (err) {
    el.innerHTML = `<p class="error-msg">${err.message}</p>`;
  }
}

function renderPlaceholder(el, s) {
  el.innerHTML = `
    <h2>${s.label}</h2>
    <div class="card">
      <p class="placeholder">Esta sección está en construcción — próximamente.</p>
    </div>`;
}

async function renderLocales(el, s) {
  const locales = await api('/locales');
  el.innerHTML = `
    <h2>Locales</h2>
    ${!puedeEditar(s) ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    <div class="card">
      <table>
        <thead><tr><th>Nombre</th><th>Estado</th></tr></thead>
        <tbody>
          ${locales.map(l => `<tr><td>${l.nombre}</td><td>${l.activo ? 'Activo' : 'Inactivo'}</td></tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

async function renderPedidos(el, s) {
  const locales = await api('/locales');
  state.locales = locales;
  const pedidos = await api('/pedidos');
  const editable = puedeEditar(s);

  const badgeClass = { pendiente: 'badge-pendiente', aprobado: 'badge-aprobado', rechazado: 'badge-rechazado', editado: 'badge-editado' };
  const nombreLocal = (id) => (locales.find(l => l.id === id) || {}).nombre || id;

  el.innerHTML = `
    <h2>Pedidos</h2>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Nuevo pedido</h3>
        <form id="pedido-form">
          <label class="field-label">Local</label>
          <select id="pedido-local" required class="field" style="margin-bottom:1rem;width:100%;max-width:280px">
            ${locales.map(l => `<option value="${l.id}">${l.nombre}</option>`).join('')}
          </select>
          <div id="items-rows"></div>
          <button type="button" id="add-item-btn" class="btn">+ Agregar insumo</button>
          <button type="button" id="sugerencia-btn" class="btn">Cargar sugerencia (Par Stock)</button>
          <br><br>
          <button type="submit" class="btn btn-primary">Crear pedido</button>
          <p id="pedido-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      <table>
        <thead><tr><th>Local</th><th>Fecha</th><th>Insumos</th><th>Estado</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${pedidos.map(p => `
            <tr>
              <td>${nombreLocal(p.local_id)}</td>
              <td>${p.fecha}</td>
              <td>${(p.items || []).length}</td>
              <td><span class="badge ${badgeClass[p.estado] || ''}">${p.estado}</span></td>
              ${editable ? `<td>
                ${p.estado === 'pendiente' ? `
                  <button class="btn btn-approve" data-id="${p.id}" data-estado="aprobado">Aprobar</button>
                  <button class="btn btn-reject" data-id="${p.id}" data-estado="rechazado">Rechazar</button>
                ` : ''}
              </td>` : ''}
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  if (editable) {
    const rowsEl = document.getElementById('items-rows');
    const addRow = (nombre = '', cantidad = '', unidad = '') => {
      const row = document.createElement('div');
      row.className = 'item-row';
      row.innerHTML = `
        <input placeholder="Insumo" class="item-nombre field" style="flex:2" value="${nombre}">
        <input placeholder="Cantidad" type="number" step="0.01" class="item-cantidad field" value="${cantidad}">
        <input placeholder="Unidad (g/kg/un)" class="item-unidad field" value="${unidad}">`;
      rowsEl.appendChild(row);
    };
    addRow();
    document.getElementById('add-item-btn').onclick = () => addRow();

    document.getElementById('sugerencia-btn').onclick = async () => {
      const local_id = document.getElementById('pedido-local').value;
      const errorEl = document.getElementById('pedido-error');
      errorEl.textContent = '';
      try {
        const sugerencia = await api(`/pedidos/sugerencia?local_id=${local_id}`);
        const conCompra = sugerencia.filter(i => i.sugerido > 0);
        if (!conCompra.length) {
          errorEl.textContent = 'Según el Par Stock actual, no hace falta comprar nada.';
          return;
        }
        rowsEl.innerHTML = '';
        conCompra.forEach(i => addRow(i.nombre, i.sugerido, i.unidad));
      } catch (err) {
        errorEl.textContent = err.message;
      }
    };

    document.getElementById('pedido-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const local_id = document.getElementById('pedido-local').value;
      const items = Array.from(rowsEl.children).map(row => ({
        ingrediente: row.querySelector('.item-nombre').value.trim(),
        cantidad: parseFloat(row.querySelector('.item-cantidad').value) || 0,
        unidad: row.querySelector('.item-unidad').value.trim(),
      })).filter(i => i.ingrediente);

      if (!items.length) {
        document.getElementById('pedido-error').textContent = 'Agrega al menos un insumo.';
        return;
      }
      try {
        await api('/pedidos', { method: 'POST', body: JSON.stringify({ local_id, items }) });
        renderView();
      } catch (err) {
        document.getElementById('pedido-error').textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-estado]').forEach(btn => {
      btn.onclick = async () => {
        try {
          await api(`/pedidos/${btn.dataset.id}/estado`, {
            method: 'PATCH',
            body: JSON.stringify({ estado: btn.dataset.estado }),
          });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }
}

// ---------- Init ----------

if (state.token && state.usuario) {
  showApp();
} else {
  showLogin();
}
