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

// ---------- Modal: Generar OC ----------

let ocPedidoId = null;

function openOcModal(pedidoId) {
  ocPedidoId = pedidoId;
  document.getElementById('oc-email').value = '';
  document.getElementById('oc-password').value = '';
  document.getElementById('oc-error').textContent = '';
  document.getElementById('oc-modal').hidden = false;
}

function closeOcModal() {
  document.getElementById('oc-modal').hidden = true;
  ocPedidoId = null;
}

document.getElementById('oc-cancel').addEventListener('click', closeOcModal);

document.getElementById('oc-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('oc-error');
  const btn = e.target.querySelector('button[type=submit]');
  const email = document.getElementById('oc-email').value.trim();
  const password = document.getElementById('oc-password').value;
  errorEl.textContent = '';
  btn.disabled = true;
  btn.textContent = 'Creando…';
  try {
    const res = await api(`/pedidos/${ocPedidoId}/generar-oc`, {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    closeOcModal();
    let msg = `OC creada: ${res.po_name}`;
    if (res.omitidos && res.omitidos.length) {
      msg += `\n\nInsumos omitidos (sin mapeo a Odoo): ${res.omitidos.join(', ')}`;
    }
    alert(msg);
    renderView();
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Crear OC';
  }
});

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
    if (state.section === 'inventario') return renderInventario(el, s);
    if (state.section === 'mermas') return renderMermas(el, s);
    if (state.section === 'parstock') return renderParStock(el, s);
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

async function renderParStock(el, s) {
  const locales = await api('/locales');
  if (!locales.length) {
    el.innerHTML = '<h2>Par Stock</h2><div class="card"><p class="placeholder">No tienes locales asignados.</p></div>';
    return;
  }
  const editable = puedeEditar(s);
  const localId = state.parStockLocal && locales.some(l => l.id === state.parStockLocal) ? state.parStockLocal : locales[0].id;
  state.parStockLocal = localId;

  const items = await api(`/par-stock?local_id=${localId}`);

  el.innerHTML = `
    <h2>Par Stock</h2>
    <label class="field-label">Local</label>
    <select id="ps-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${l.nombre}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Agregar insumo nuevo</h3>
        <p class="placeholder" style="margin-bottom:1rem">El nombre/ID/referencia en Odoo debes verificarlos tú mismo en Odoo — el sistema nunca crea productos ni proveedores nuevos, solo registra la referencia.</p>
        <form id="ps-form">
          <div class="item-row">
            <input class="field" id="ps-nombre" placeholder="Nombre insumo" style="flex:2" required>
            <input class="field" id="ps-unidad" placeholder="Unidad (kg/un)" value="kg" required>
            <input class="field" id="ps-categoria" placeholder="Categoría (opcional)">
          </div>
          <div class="item-row">
            <input class="field" id="ps-par" type="number" step="0.01" placeholder="Par Stock" required>
            <input class="field" id="ps-precio" type="number" step="1" placeholder="Precio unitario">
          </div>
          <div class="item-row">
            <input class="field" id="ps-odoo-id" type="number" placeholder="ID producto Odoo" required>
            <input class="field" id="ps-odoo-name" placeholder="Nombre en Odoo" style="flex:2" required>
            <input class="field" id="ps-ref" placeholder="Referencia (opcional)">
          </div>
          <div class="item-row">
            <input class="field" id="ps-supplier-id" type="number" placeholder="ID proveedor Odoo" required>
            <input class="field" id="ps-supplier-name" placeholder="Nombre proveedor" style="flex:2" required>
          </div>
          <label style="font-size:.8rem;color:var(--t2);display:flex;align-items:center;gap:.4rem;margin-bottom:.75rem">
            <input type="checkbox" id="ps-granel"> Se compra a granel (sin empaque fijo)
          </label>
          <input class="field" id="ps-empaque" type="number" step="0.01" placeholder="Tamaño de empaque (kg)" style="max-width:220px;margin-bottom:.75rem">
          <br>
          <button type="submit" class="btn btn-primary">Agregar insumo</button>
          <p id="ps-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      <table>
        <thead><tr><th>Insumo</th><th>Par Stock</th><th>Nombre Odoo</th><th>Proveedor</th><th>Precio</th><th>Empaque</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${items.map(i => `
            <tr>
              <td>${i.nombre} (${i.unidad})</td>
              <td>${editable ? `<input class="field ps-edit-par" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:90px" value="${i.par_cantidad}">` : i.par_cantidad}</td>
              <td>${i.odoo_name || '—'}</td>
              <td>${i.supplier_name || '—'}</td>
              <td>${editable ? `<input class="field ps-edit-precio" data-key="${i.ingrediente_key}" type="number" style="width:90px" value="${i.precio}">` : i.precio}</td>
              <td>
                ${editable
                  ? `<input class="field ps-edit-empaque" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:90px" placeholder="A granel" value="${i.tamano_empaque ?? ''}">`
                  : (i.tamano_empaque ? `${i.tamano_empaque} kg/paquete` : 'A granel')}
              </td>
              ${editable ? `<td><button class="btn" data-guardar="${i.ingrediente_key}">Guardar</button></td>` : ''}
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  document.getElementById('ps-local').addEventListener('change', (e) => {
    state.parStockLocal = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('ps-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('ps-error');
      const granel = document.getElementById('ps-granel').checked;
      try {
        await api('/par-stock', {
          method: 'POST',
          body: JSON.stringify({
            local_id: localId,
            nombre: document.getElementById('ps-nombre').value.trim(),
            unidad: document.getElementById('ps-unidad').value.trim(),
            categoria: document.getElementById('ps-categoria').value.trim() || null,
            par_cantidad: parseFloat(document.getElementById('ps-par').value) || 0,
            odoo_id: parseInt(document.getElementById('ps-odoo-id').value, 10),
            odoo_name: document.getElementById('ps-odoo-name').value.trim(),
            ref: document.getElementById('ps-ref').value.trim() || null,
            supplier_id: parseInt(document.getElementById('ps-supplier-id').value, 10),
            supplier_name: document.getElementById('ps-supplier-name').value.trim(),
            precio: parseFloat(document.getElementById('ps-precio').value) || 0,
            a_granel: granel,
            tamano_empaque: granel ? null : (parseFloat(document.getElementById('ps-empaque').value) || null),
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-guardar]').forEach(btn => {
      btn.onclick = async () => {
        const key = btn.dataset.guardar;
        const par = el.querySelector(`.ps-edit-par[data-key="${key}"]`).value;
        const precio = el.querySelector(`.ps-edit-precio[data-key="${key}"]`).value;
        const empaqueVal = el.querySelector(`.ps-edit-empaque[data-key="${key}"]`).value;
        try {
          await api('/par-stock', {
            method: 'PATCH',
            body: JSON.stringify({
              local_id: localId,
              ingrediente_key: key,
              par_cantidad: parseFloat(par) || 0,
              precio: parseFloat(precio) || 0,
              a_granel: empaqueVal === '',
              tamano_empaque: empaqueVal === '' ? null : parseFloat(empaqueVal),
            }),
          });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }
}

async function renderInventario(el, s) {
  const locales = await api('/locales');
  if (!locales.length) {
    el.innerHTML = '<h2>Inventario</h2><div class="card"><p class="placeholder">No tienes locales asignados.</p></div>';
    return;
  }
  const editable = puedeEditar(s);
  const localId = state.invLocal && locales.some(l => l.id === state.invLocal) ? state.invLocal : locales[0].id;
  state.invLocal = localId;

  const items = await api(`/inventario?local_id=${localId}`);

  el.innerHTML = `
    <h2>Inventario de Bodega</h2>
    <label class="field-label">Local</label>
    <select id="inv-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${l.nombre}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Registrar movimiento</h3>
        <form id="mov-form">
          <div class="item-row">
            <select id="mov-insumo" class="field" style="flex:2" required>
              ${items.map(i => `<option value="${i.ingrediente_key}">${i.nombre} (${i.unidad})</option>`).join('')}
            </select>
            <select id="mov-tipo" class="field">
              <option value="ingreso">Ingreso</option>
              <option value="egreso">Egreso</option>
              <option value="ajuste">Ajuste</option>
            </select>
            <input id="mov-cantidad" class="field" type="number" step="0.01" placeholder="Cantidad" required>
          </div>
          <input id="mov-nota" class="field" style="width:100%;margin-bottom:.75rem" placeholder="Nota (opcional)">
          <button type="submit" class="btn btn-primary">Registrar</button>
          <p id="mov-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      <table>
        <thead><tr><th>Insumo</th><th>Unidad</th><th>Par Stock</th><th>Stock Bodega actual</th></tr></thead>
        <tbody>
          ${items.map(i => `
            <tr>
              <td>${i.nombre}</td>
              <td>${i.unidad}</td>
              <td>${i.par}</td>
              <td>${i.stock_bodega}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  document.getElementById('inv-local').addEventListener('change', (e) => {
    state.invLocal = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('mov-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('mov-error');
      try {
        await api('/inventario/movimiento', {
          method: 'POST',
          body: JSON.stringify({
            local_id: localId,
            ingrediente_key: document.getElementById('mov-insumo').value,
            tipo: document.getElementById('mov-tipo').value,
            cantidad: parseFloat(document.getElementById('mov-cantidad').value) || 0,
            nota: document.getElementById('mov-nota').value.trim() || null,
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  }
}

async function renderMermas(el, s) {
  const locales = await api('/locales');
  if (!locales.length) {
    el.innerHTML = '<h2>Mermas</h2><div class="card"><p class="placeholder">No tienes locales asignados.</p></div>';
    return;
  }
  const editable = puedeEditar(s);
  const localId = state.mermasLocal && locales.some(l => l.id === state.mermasLocal) ? state.mermasLocal : locales[0].id;
  state.mermasLocal = localId;

  const items = await api(`/mermas?local_id=${localId}`);
  const hoy = items[0]?.fecha || new Date().toISOString().slice(0, 10);

  el.innerHTML = `
    <h2>Mermas — Stock de Cocina</h2>
    <label class="field-label">Local</label>
    <select id="mermas-local" class="field" style="margin-bottom:.5rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${l.nombre}</option>`).join('')}
    </select>
    <p class="placeholder" style="margin-bottom:1.25rem">Conteo de hoy (${hoy}) — lo que informa cocina cada mañana.</p>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    <div class="card">
      <form id="mermas-form">
        <table>
          <thead><tr><th>Insumo</th><th>Unidad</th><th>Stock informado hoy</th></tr></thead>
          <tbody>
            ${items.map(i => `
              <tr>
                <td>${i.nombre}</td>
                <td>${i.unidad}</td>
                <td>
                  ${editable
                    ? `<input class="field merma-input" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:120px" value="${i.cantidad_informada ?? ''}">`
                    : (i.cantidad_informada ?? '—')}
                </td>
              </tr>`).join('')}
          </tbody>
        </table>
        ${editable ? '<br><button type="submit" class="btn btn-primary">Guardar mermas de hoy</button>' : ''}
        <p id="mermas-error" class="error-msg"></p>
      </form>
    </div>`;

  document.getElementById('mermas-local').addEventListener('change', (e) => {
    state.mermasLocal = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('mermas-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('mermas-error');
      const inputs = Array.from(document.querySelectorAll('.merma-input')).filter(inp => inp.value !== '');
      try {
        for (const inp of inputs) {
          await api('/mermas', {
            method: 'POST',
            body: JSON.stringify({
              local_id: localId,
              ingrediente_key: inp.dataset.key,
              cantidad_informada: parseFloat(inp.value) || 0,
            }),
          });
        }
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  }
}

function showDetalleModal(pedido, nombreLocal) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal-box">
      <h3>Detalle del pedido — ${nombreLocal}</h3>
      <p class="placeholder" style="margin-bottom:1rem">${pedido.fecha} · ${pedido.estado}</p>
      <table>
        <thead><tr><th>Insumo</th><th>Cantidad</th><th>Unidad</th></tr></thead>
        <tbody>
          ${(pedido.items || []).map(i => `
            <tr><td>${i.ingrediente}</td><td>${i.cantidad}</td><td>${i.unidad}</td></tr>
          `).join('')}
        </tbody>
      </table>
      <div style="margin-top:1.25rem"><button type="button" class="btn">Cerrar</button></div>
    </div>`;
  overlay.querySelector('button').onclick = () => overlay.remove();
  document.body.appendChild(overlay);
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
        <thead><tr><th></th><th>Local</th><th>Fecha</th><th>Insumos</th><th>Estado</th><th>Orden de Compra</th><th>Acciones</th></tr></thead>
        <tbody>
          ${pedidos.map(p => `
            <tr>
              <td>${editable
                ? `<button class="btn-link" data-fav="${p.id}" data-val="${!p.favorito}" title="Favorito">${p.favorito ? '★' : '☆'}</button>`
                : (p.favorito ? '★' : '')}</td>
              <td>${nombreLocal(p.local_id)}</td>
              <td>${p.fecha}</td>
              <td><button class="btn-link" data-ver="${p.id}">${(p.items || []).length} insumo(s)</button></td>
              <td><span class="badge ${badgeClass[p.estado] || ''}">${p.estado}</span></td>
              <td>
                ${p.po_name ? p.po_name : (editable && p.estado === 'aprobado'
                  ? `<button class="btn-link" data-oc="${p.id}">Generar OC</button>`
                  : '—')}
              </td>
              <td>
                ${editable && p.estado === 'pendiente' ? `
                  <button class="btn btn-approve" data-id="${p.id}" data-estado="aprobado">Aprobar</button>
                  <button class="btn btn-reject" data-id="${p.id}" data-estado="rechazado">Rechazar</button>
                ` : ''}
                ${editable && !p.po_name ? `<button class="btn btn-reject" data-del="${p.id}">Eliminar</button>` : ''}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  el.querySelectorAll('button[data-oc]').forEach(btn => {
    btn.onclick = () => openOcModal(btn.dataset.oc);
  });

  el.querySelectorAll('button[data-ver]').forEach(btn => {
    const p = pedidos.find(x => x.id === btn.dataset.ver);
    btn.onclick = () => showDetalleModal(p, nombreLocal(p.local_id));
  });

  el.querySelectorAll('button[data-fav]').forEach(btn => {
    btn.onclick = async () => {
      try {
        await api(`/pedidos/${btn.dataset.fav}/favorito`, {
          method: 'PATCH',
          body: JSON.stringify({ favorito: btn.dataset.val === 'true' }),
        });
        renderView();
      } catch (err) {
        alert(err.message);
      }
    };
  });

  el.querySelectorAll('button[data-del]').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('¿Eliminar este pedido? Esta acción no se puede deshacer.')) return;
      try {
        await api(`/pedidos/${btn.dataset.del}`, { method: 'DELETE' });
        renderView();
      } catch (err) {
        alert(err.message);
      }
    };
  });

  if (editable) {
    const rowsEl = document.getElementById('items-rows');
    const addRow = (nombre = '', cantidad = '', unidad = '', key = '') => {
      const row = document.createElement('div');
      row.className = 'item-row';
      row.dataset.key = key;
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
        conCompra.forEach(i => addRow(i.nombre, i.sugerido, i.unidad, i.ingrediente_key));
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
        ingrediente_key: row.dataset.key || null,
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
