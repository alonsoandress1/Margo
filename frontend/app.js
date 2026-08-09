// Margo · Compras — frontend (vanilla JS, sin build step)
// El backend sirve estos archivos estáticos, así que la API está en el mismo origen.

const SECCIONES = [
  { id: 'pedidos',   label: 'Pedidos',              roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'inventario', label: 'Inventario',          roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'mermas',    label: 'Mermas',                roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'oc',        label: 'Órdenes de Compra',     roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'proveedores', label: 'Proveedores',         roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
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

// ---------- Modal: Cambiar contraseña ----------

document.getElementById('cambiar-password-btn').addEventListener('click', () => {
  document.getElementById('pw-actual').value = '';
  document.getElementById('pw-nueva').value = '';
  document.getElementById('pw-repetir').value = '';
  document.getElementById('pw-error').textContent = '';
  document.getElementById('pw-modal').hidden = false;
});

document.getElementById('pw-cancel').addEventListener('click', () => {
  document.getElementById('pw-modal').hidden = true;
});

document.getElementById('pw-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('pw-error');
  const btn = e.target.querySelector('button[type=submit]');
  const actual = document.getElementById('pw-actual').value;
  const nueva = document.getElementById('pw-nueva').value;
  const repetir = document.getElementById('pw-repetir').value;
  errorEl.textContent = '';

  if (nueva !== repetir) {
    errorEl.textContent = 'La contraseña nueva no coincide en ambos campos.';
    return;
  }
  if (nueva.length < 6) {
    errorEl.textContent = 'La contraseña nueva debe tener al menos 6 caracteres.';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Guardando…';
  try {
    await api('/auth/password', {
      method: 'PATCH',
      body: JSON.stringify({ password_actual: actual, password_nueva: nueva }),
    });
    document.getElementById('pw-modal').hidden = true;
    alert('Contraseña actualizada.');
  } catch (err) {
    errorEl.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Guardar';
  }
});

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
      body: JSON.stringify({ email: email || null, password: password || null }),
    });
    closeOcModal();
    const lineas = res.acciones.map(a =>
      a.tipo === 'odoo' ? `✓ OC creada en Odoo: ${a.po_name} (${a.proveedor})` : `✉ Aviso enviado por correo a ${a.proveedor}`
    );
    let msg = lineas.join('\n');
    if (res.omitidos && res.omitidos.length) {
      msg += `\n\nInsumos omitidos (sin proveedor registrado): ${res.omitidos.join(', ')}`;
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
    if (state.section === 'proveedores') return renderProveedores(el, s);
    if (state.section === 'recetas') return renderRecetas(el, s);
    if (state.section === 'usuarios') return renderUsuarios(el, s);
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

async function renderProveedores(el, s) {
  const editable = puedeEditar(s);
  const proveedores = await api('/proveedores');
  const config = editable ? await api('/configuracion/email').catch(() => null) : null;

  const provId = state.proveedorSel && proveedores.some(p => p.id === state.proveedorSel)
    ? state.proveedorSel : (proveedores[0] ? proveedores[0].id : null);
  state.proveedorSel = provId;
  const provSeleccionado = proveedores.find(p => p.id === provId);

  const productos = provId ? await api(`/proveedores/${provId}/productos`) : [];

  el.innerHTML = `
    <h2>Proveedores</h2>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Configuración de avisos por correo</h3>
        <p class="placeholder" style="margin-bottom:1rem">Para proveedores sin integración a Odoo, se envía un correo con el pedido a este destinatario. Asunto siempre: "Pedido {local}".</p>
        <form id="config-email-form">
          <input class="field" id="config-destinatario" type="email" placeholder="correo@margo.cl" style="width:100%;max-width:400px" value="${config ? config.destinatario : ''}" required>
          <button type="submit" class="btn btn-primary" style="margin-left:.5rem">Guardar</button>
          <p id="config-email-error" class="error-msg"></p>
        </form>
      </div>
      <div class="card">
        <h3>Agregar proveedor</h3>
        <form id="prov-form">
          <div class="item-row">
            <input class="field" id="prov-nombre" placeholder="Nombre del proveedor" style="flex:2" required>
            <input class="field" id="prov-odoo-id" type="number" placeholder="ID en Odoo (res.partner)" required>
          </div>
          <label style="font-size:.8rem;color:var(--t2);display:flex;align-items:center;gap:.4rem;margin-bottom:.75rem">
            <input type="checkbox" id="prov-usa-odoo"> Tiene integración con Odoo (genera OC real; si no, se avisa por correo)
          </label>
          <button type="submit" class="btn btn-primary">Agregar proveedor</button>
          <p id="prov-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      <label class="field-label">Proveedor</label>
      <select id="prov-sel" class="field" style="margin-bottom:1rem;width:100%;max-width:320px">
        ${proveedores.map(p => `<option value="${p.id}" ${p.id === provId ? 'selected' : ''}>${p.nombre}${p.usa_odoo ? ' (Odoo)' : ''}</option>`).join('')}
      </select>
      ${provSeleccionado ? `<p class="placeholder">${provSeleccionado.usa_odoo ? '✓ Genera Orden de Compra real en Odoo.' : 'Sin integración a Odoo — se avisa por correo al generar la OC.'}</p>` : ''}
      ${!proveedores.length ? '<p class="placeholder">Todavía no hay proveedores — agrega uno arriba.</p>' : ''}
    </div>
    ${provId ? `
    ${editable ? `
      <div class="card">
        <h3>Agregar producto de este proveedor</h3>
        <p class="placeholder" style="margin-bottom:1rem">Verifica el ID y nombre exactos en Odoo tú mismo — el sistema nunca crea productos nuevos, solo registra la referencia.</p>
        <form id="prod-form">
          <div class="item-row">
            <input class="field" id="prod-nombre" placeholder="Nombre del insumo" style="flex:2" required>
            <input class="field" id="prod-unidad" placeholder="Unidad (kg/un)" value="kg" required>
          </div>
          <div class="item-row">
            <input class="field" id="prod-odoo-id" type="number" placeholder="ID producto Odoo" required>
            <input class="field" id="prod-odoo-name" placeholder="Nombre en Odoo" style="flex:2" required>
            <input class="field" id="prod-ref" placeholder="Referencia (opcional)">
          </div>
          <div class="item-row">
            <input class="field" id="prod-precio" type="number" step="1" placeholder="Precio unitario">
          </div>
          <label style="font-size:.8rem;color:var(--t2);display:flex;align-items:center;gap:.4rem;margin-bottom:.75rem">
            <input type="checkbox" id="prod-granel"> Se compra a granel (sin formato/empaque fijo)
          </label>
          <input class="field" id="prod-empaque" type="number" step="0.01" placeholder="Formato / tamaño de empaque (kg)" style="max-width:260px;margin-bottom:.75rem">
          <br>
          <button type="submit" class="btn btn-primary">Agregar producto</button>
          <p id="prod-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      ${editable && productos.length ? `
      <div class="item-row" style="align-items:center;margin-bottom:.75rem">
        <button type="button" class="btn btn-reject" id="prod-del-selected" disabled>Eliminar seleccionados (<span id="prod-selected-count">0</span>)</button>
      </div>` : ''}
      <table>
        <thead><tr>${editable ? '<th><input type="checkbox" id="prod-check-all"></th>' : ''}<th>Insumo</th><th>Nombre Odoo</th><th>Ref</th><th>Precio</th><th>Formato</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${productos.map(p => `
            <tr>
              ${editable ? `<td><input type="checkbox" class="prod-check" data-id="${p.id}"></td>` : ''}
              <td>${p.nombre} (${p.unidad})</td>
              <td>${p.odoo_name}</td>
              <td>${p.ref || '—'}</td>
              <td>${editable ? `<input class="field prod-edit-precio" data-key="${p.ingrediente_key}" type="number" style="width:90px" value="${p.precio}">` : p.precio}</td>
              <td>
                ${editable
                  ? `<input class="field prod-edit-empaque" data-key="${p.ingrediente_key}" type="number" step="0.01" style="width:90px" placeholder="A granel" value="${p.tamano_empaque ?? ''}">`
                  : (p.tamano_empaque ? `${p.tamano_empaque} kg/paquete` : 'A granel')}
              </td>
              ${editable ? `<td>
                <button class="btn" data-guardar-prod="${p.ingrediente_key}">Guardar</button>
                <button class="btn btn-reject" data-del-prod="${p.id}">Eliminar</button>
              </td>` : ''}
            </tr>`).join('')}
          ${!productos.length ? `<tr><td colspan="${editable ? 7 : 5}" class="placeholder">Sin productos todavía.</td></tr>` : ''}
        </tbody>
      </table>
    </div>` : ''}`;

  document.getElementById('prov-sel')?.addEventListener('change', (e) => {
    state.proveedorSel = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('config-email-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('config-email-error');
      try {
        await api('/configuracion/email', {
          method: 'PATCH',
          body: JSON.stringify({ destinatario: document.getElementById('config-destinatario').value.trim() }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    document.getElementById('prov-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('prov-error');
      try {
        await api('/proveedores', {
          method: 'POST',
          body: JSON.stringify({
            nombre: document.getElementById('prov-nombre').value.trim(),
            odoo_supplier_id: parseInt(document.getElementById('prov-odoo-id').value, 10),
            usa_odoo: document.getElementById('prov-usa-odoo').checked,
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    document.getElementById('prod-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('prod-error');
      const granel = document.getElementById('prod-granel').checked;
      try {
        await api(`/proveedores/${provId}/productos`, {
          method: 'POST',
          body: JSON.stringify({
            nombre: document.getElementById('prod-nombre').value.trim(),
            unidad: document.getElementById('prod-unidad').value.trim(),
            odoo_id: parseInt(document.getElementById('prod-odoo-id').value, 10),
            odoo_name: document.getElementById('prod-odoo-name').value.trim(),
            ref: document.getElementById('prod-ref').value.trim() || null,
            precio: parseFloat(document.getElementById('prod-precio').value) || 0,
            a_granel: granel,
            tamano_empaque: granel ? null : (parseFloat(document.getElementById('prod-empaque').value) || null),
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-guardar-prod]').forEach(btn => {
      btn.onclick = async () => {
        const key = btn.dataset.guardarProd;
        const precio = el.querySelector(`.prod-edit-precio[data-key="${key}"]`).value;
        const empaqueVal = el.querySelector(`.prod-edit-empaque[data-key="${key}"]`).value;
        try {
          await api(`/proveedores/${provId}/productos`, {
            method: 'PATCH',
            body: JSON.stringify({
              ingrediente_key: key,
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

    el.querySelectorAll('button[data-del-prod]').forEach(btn => {
      btn.onclick = async () => {
        if (!confirm('¿Eliminar este producto del catálogo del proveedor?')) return;
        try {
          await api(`/proveedores/${provId}/productos/${btn.dataset.delProd}`, { method: 'DELETE' });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    const prodChecks = () => Array.from(el.querySelectorAll('.prod-check'));
    const updateProdSelCount = () => {
      const n = prodChecks().filter(c => c.checked).length;
      const btn = document.getElementById('prod-del-selected');
      if (btn) {
        btn.disabled = n === 0;
        document.getElementById('prod-selected-count').textContent = n;
      }
    };
    document.getElementById('prod-check-all')?.addEventListener('change', (e) => {
      prodChecks().forEach(c => { c.checked = e.target.checked; });
      updateProdSelCount();
    });
    prodChecks().forEach(c => c.addEventListener('change', updateProdSelCount));
    document.getElementById('prod-del-selected')?.addEventListener('click', async () => {
      const ids = prodChecks().filter(c => c.checked).map(c => c.dataset.id);
      if (!ids.length) return;
      if (!confirm(`¿Eliminar ${ids.length} producto(s) del catálogo del proveedor?`)) return;
      const resultados = await Promise.allSettled(
        ids.map(id => api(`/proveedores/${provId}/productos/${id}`, { method: 'DELETE' }))
      );
      const fallidos = resultados.filter(r => r.status === 'rejected');
      renderView();
      if (fallidos.length) {
        alert(`${ids.length - fallidos.length} eliminado(s). ${fallidos.length} no se pudieron eliminar (probablemente están en Par Stock de algún local):\n\n` +
          fallidos.map(r => r.reason.message).join('\n'));
      }
    });
  }
}

async function renderRecetas(el, s) {
  const locales = await api('/locales');
  if (!locales.length) {
    el.innerHTML = '<h2>Recetas</h2><div class="card"><p class="placeholder">No tienes locales asignados.</p></div>';
    return;
  }
  const editable = puedeEditar(s);
  const localId = state.recetasLocal && locales.some(l => l.id === state.recetasLocal) ? state.recetasLocal : locales[0].id;
  state.recetasLocal = localId;

  const todosPlatos = await api(`/platos?local_id=${localId}`);
  const lineas = await api(`/recetas?local_id=${localId}`);
  const porPlato = {};
  lineas.forEach(l => {
    (porPlato[l.plato_id] ??= { sku: l.plato_sku, nombre: l.plato_nombre, lineas: [] }).lineas.push(l);
  });
  const etiqueta = (p) => `${p.nombre} (${p.sku})`;

  el.innerHTML = `
    <h2>Recetas</h2>
    <label class="field-label">Local</label>
    <select id="rec-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${l.nombre}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Agregar insumo a una receta</h3>
        <p class="placeholder" style="margin-bottom:1rem">${todosPlatos.length} platos en el catálogo (importados del reporte de ventas).</p>
        <form id="rec-form">
          <input class="field" id="rec-plato-search" list="platos-datalist" placeholder="Buscar plato por nombre..." style="width:100%;margin-bottom:.75rem" required autocomplete="off">
          <datalist id="platos-datalist">
            ${todosPlatos.map(p => `<option value="${etiqueta(p)}">`).join('')}
          </datalist>
          <div class="item-row">
            <input class="field" id="rec-ingrediente" placeholder="Insumo" style="flex:2" required>
            <input class="field" id="rec-cantidad" type="number" step="0.01" placeholder="Cantidad" required>
            <input class="field" id="rec-unidad" placeholder="Unidad (g/kg/un)" required>
          </div>
          <button type="submit" class="btn btn-primary">Agregar</button>
          <p id="rec-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    ${Object.keys(porPlato).length ? Object.entries(porPlato).map(([platoId, p]) => `
      <div class="card">
        <h3>${p.nombre} <span class="placeholder">(${p.sku})</span></h3>
        <table>
          <thead><tr><th>Insumo</th><th>Cantidad</th><th>Unidad</th>${editable ? '<th></th>' : ''}</tr></thead>
          <tbody>
            ${p.lineas.map(l => `
              <tr>
                <td>${l.ingrediente}</td><td>${l.cantidad}</td><td>${l.unidad}</td>
                ${editable ? `<td><button class="btn btn-reject" data-del-linea="${l.id}">Eliminar</button></td>` : ''}
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`).join('') : '<div class="card"><p class="placeholder">Sin recetas cargadas para este local todavía.</p></div>'}`;

  document.getElementById('rec-local').addEventListener('change', (e) => {
    state.recetasLocal = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('rec-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('rec-error');
      const texto = document.getElementById('rec-plato-search').value.trim();
      const plato = todosPlatos.find(p => etiqueta(p) === texto);
      if (!plato) {
        errorEl.textContent = 'Selecciona un plato válido de la lista (no uno escrito a mano).';
        return;
      }
      try {
        await api('/recetas', {
          method: 'POST',
          body: JSON.stringify({
            plato_id: plato.id,
            ingrediente: document.getElementById('rec-ingrediente').value.trim(),
            cantidad: parseFloat(document.getElementById('rec-cantidad').value) || 0,
            unidad: document.getElementById('rec-unidad').value.trim(),
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-del-linea]').forEach(btn => {
      btn.onclick = async () => {
        if (!confirm('¿Eliminar esta línea de la receta?')) return;
        try {
          await api(`/recetas/${btn.dataset.delLinea}`, { method: 'DELETE' });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }
}

async function renderUsuarios(el, s) {
  const editable = puedeEditar(s);
  const locales = await api('/locales');
  const usuarios = await api('/usuarios');

  const nombreLocal = (id) => (locales.find(l => l.id === id) || {}).nombre || id;
  const badgeClass = { administrador: 'badge-aprobado', solicitante: 'badge-pendiente', observador: 'badge-editado' };

  el.innerHTML = `
    <h2>Usuarios</h2>
    ${editable ? `
      <div class="card">
        <h3>Crear usuario</h3>
        <form id="usr-form">
          <div class="item-row">
            <input class="field" id="usr-email" type="email" placeholder="Email" style="flex:2" required>
            <input class="field" id="usr-nombre" placeholder="Nombre completo" style="flex:2" required>
          </div>
          <div class="item-row">
            <select id="usr-rol" class="field">
              <option value="solicitante">Solicitante</option>
              <option value="administrador">Administrador</option>
              <option value="observador">Observador</option>
            </select>
            <input class="field" id="usr-password" type="password" placeholder="Contraseña" style="flex:2" required>
          </div>
          <div id="usr-locales-wrap" style="margin-bottom:.75rem">
            <label class="field-label">Locales asignados (solo aplica a Solicitante)</label>
            ${locales.map(l => `
              <label style="font-size:.8rem;color:var(--t2);margin-right:1rem">
                <input type="checkbox" class="usr-local-chk" value="${l.id}"> ${l.nombre}
              </label>`).join('')}
          </div>
          <button type="submit" class="btn btn-primary">Crear usuario</button>
          <p id="usr-error" class="error-msg"></p>
        </form>
      </div>` : ''}
    <div class="card">
      <table>
        <thead><tr><th>Nombre</th><th>Email</th><th>Rol</th><th>Locales</th><th>Estado</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${usuarios.map(u => `
            <tr>
              <td>${u.nombre}</td>
              <td>${u.email}</td>
              <td><span class="badge ${badgeClass[u.rol] || ''}">${u.rol}</span></td>
              <td>${u.locales.map(nombreLocal).join(', ') || '—'}</td>
              <td>${u.activo ? 'Activo' : 'Inactivo'}</td>
              ${editable ? `<td><button class="btn" data-toggle-activo="${u.id}" data-val="${!u.activo}">${u.activo ? 'Desactivar' : 'Activar'}</button></td>` : ''}
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  if (editable) {
    document.getElementById('usr-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('usr-error');
      const localesSel = Array.from(document.querySelectorAll('.usr-local-chk:checked')).map(c => c.value);
      try {
        await api('/usuarios', {
          method: 'POST',
          body: JSON.stringify({
            email: document.getElementById('usr-email').value.trim(),
            nombre: document.getElementById('usr-nombre').value.trim(),
            rol: document.getElementById('usr-rol').value,
            password: document.getElementById('usr-password').value,
            locales: localesSel,
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-toggle-activo]').forEach(btn => {
      btn.onclick = async () => {
        try {
          await api(`/usuarios/${btn.dataset.toggleActivo}`, {
            method: 'PATCH',
            body: JSON.stringify({ activo: btn.dataset.val === 'true' }),
          });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }
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
  const catalogo = editable ? await api('/productos') : [];
  const yaAgregados = new Set(items.map(i => i.ingrediente_key));
  const disponibles = catalogo.filter(p => !yaAgregados.has(p.ingrediente_key));

  el.innerHTML = `
    <h2>Par Stock</h2>
    <label class="field-label">Local</label>
    <select id="ps-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${l.nombre}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Agregar a Par Stock</h3>
        ${!disponibles.length ? '<p class="placeholder">No hay insumos del catálogo de Proveedores disponibles para agregar (o ya están todos agregados). Ve a la sección Proveedores para registrar más.</p>' : `
        <form id="ps-form">
          <div class="item-row">
            <select id="ps-insumo" class="field" style="flex:2" required>
              ${disponibles.map(p => `<option value="${p.ingrediente_key}">${p.nombre} (${p.unidad})</option>`).join('')}
            </select>
            <input class="field" id="ps-par" type="number" step="0.01" placeholder="Par Stock" required>
          </div>
          <button type="submit" class="btn btn-primary">Agregar</button>
          <p id="ps-error" class="error-msg"></p>
        </form>`}
      </div>` : ''}
    <div class="card">
      ${editable && items.length ? `
      <div class="item-row" style="align-items:center;margin-bottom:.75rem">
        <button type="button" class="btn btn-reject" id="ps-del-selected" disabled>Eliminar seleccionados (<span id="ps-selected-count">0</span>)</button>
      </div>` : ''}
      <table>
        <thead><tr>${editable ? '<th><input type="checkbox" id="ps-check-all"></th>' : ''}<th>Insumo</th><th>Par Stock</th><th>Nombre Odoo</th><th>Proveedor</th><th>Precio</th><th>Formato</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${items.map(i => `
            <tr>
              ${editable ? `<td><input type="checkbox" class="ps-check" data-key="${i.ingrediente_key}"></td>` : ''}
              <td>${i.nombre} (${i.unidad})</td>
              <td>${editable ? `<input class="field ps-edit-par" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:90px" value="${i.par_cantidad}">` : i.par_cantidad}</td>
              <td>${i.odoo_name || '—'}</td>
              <td>${i.supplier_name || '—'}</td>
              <td>${i.precio}</td>
              <td>
                ${editable
                  ? `<input class="field ps-edit-empaque" data-key="${i.ingrediente_key}" data-prov="${i.proveedor_id || ''}" type="number" step="0.01" style="width:90px" placeholder="A granel (kg/paquete)" value="${i.tamano_empaque ?? ''}">`
                  : (i.tamano_empaque ? `${i.tamano_empaque} kg/paquete` : 'A granel')}
              </td>
              ${editable ? `<td>
                <button class="btn" data-guardar-par="${i.ingrediente_key}">Guardar</button>
                <button class="btn btn-reject" data-del-par="${i.ingrediente_key}">Eliminar</button>
              </td>` : ''}
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  document.getElementById('ps-local').addEventListener('change', (e) => {
    state.parStockLocal = e.target.value;
    renderView();
  });

  if (editable) {
    document.getElementById('ps-form')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('ps-error');
      try {
        await api('/par-stock', {
          method: 'POST',
          body: JSON.stringify({
            local_id: localId,
            ingrediente_key: document.getElementById('ps-insumo').value,
            par_cantidad: parseFloat(document.getElementById('ps-par').value) || 0,
          }),
        });
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });

    el.querySelectorAll('button[data-guardar-par]').forEach(btn => {
      btn.onclick = async () => {
        const key = btn.dataset.guardarPar;
        const par = el.querySelector(`.ps-edit-par[data-key="${key}"]`).value;
        const empaqueInput = el.querySelector(`.ps-edit-empaque[data-key="${key}"]`);
        const provId = empaqueInput?.dataset.prov;
        const empaqueVal = empaqueInput?.value ?? '';
        try {
          await api('/par-stock', {
            method: 'PATCH',
            body: JSON.stringify({
              local_id: localId,
              ingrediente_key: key,
              par_cantidad: parseFloat(par) || 0,
            }),
          });
          if (provId) {
            await api(`/proveedores/${provId}/productos`, {
              method: 'PATCH',
              body: JSON.stringify({
                ingrediente_key: key,
                a_granel: empaqueVal === '',
                tamano_empaque: empaqueVal === '' ? null : parseFloat(empaqueVal),
              }),
            });
          }
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    el.querySelectorAll('button[data-del-par]').forEach(btn => {
      btn.onclick = async () => {
        if (!confirm('¿Eliminar este insumo de Par Stock?')) return;
        try {
          await api(`/par-stock?local_id=${localId}&ingrediente_key=${encodeURIComponent(btn.dataset.delPar)}`, { method: 'DELETE' });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    const psChecks = () => Array.from(el.querySelectorAll('.ps-check'));
    const updatePsSelCount = () => {
      const n = psChecks().filter(c => c.checked).length;
      const btn = document.getElementById('ps-del-selected');
      if (btn) {
        btn.disabled = n === 0;
        document.getElementById('ps-selected-count').textContent = n;
      }
    };
    document.getElementById('ps-check-all')?.addEventListener('change', (e) => {
      psChecks().forEach(c => { c.checked = e.target.checked; });
      updatePsSelCount();
    });
    psChecks().forEach(c => c.addEventListener('change', updatePsSelCount));
    document.getElementById('ps-del-selected')?.addEventListener('click', async () => {
      const keys = psChecks().filter(c => c.checked).map(c => c.dataset.key);
      if (!keys.length) return;
      if (!confirm(`¿Eliminar ${keys.length} insumo(s) de Par Stock?`)) return;
      const resultados = await Promise.allSettled(
        keys.map(key => api(`/par-stock?local_id=${localId}&ingrediente_key=${encodeURIComponent(key)}`, { method: 'DELETE' }))
      );
      const fallidos = resultados.filter(r => r.status === 'rejected');
      renderView();
      if (fallidos.length) {
        alert(`${keys.length - fallidos.length} eliminado(s). ${fallidos.length} no se pudieron eliminar:\n\n` +
          fallidos.map(r => r.reason.message).join('\n'));
      }
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
                ${p.acciones && p.acciones.length
                  ? p.acciones.map(a => a.tipo === 'odoo' ? a.po_name : `✉ ${a.proveedor}`).join(', ')
                  : (editable && p.estado === 'aprobado'
                    ? `<button class="btn-link" data-oc="${p.id}">Generar OC</button>`
                    : '—')}
              </td>
              <td>
                ${editable && p.estado === 'pendiente' ? `
                  <button class="btn btn-approve" data-id="${p.id}" data-estado="aprobado">Aprobar</button>
                  <button class="btn btn-reject" data-id="${p.id}" data-estado="rechazado">Rechazar</button>
                ` : ''}
                ${editable && (!p.acciones || !p.acciones.length) ? `<button class="btn btn-reject" data-del="${p.id}">Eliminar</button>` : ''}
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
