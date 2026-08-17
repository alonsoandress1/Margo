// Margo · Compras — frontend (vanilla JS, sin build step)
// El backend sirve estos archivos estáticos, así que la API está en el mismo origen.

// Texto libre que un usuario escribe (ej. nombre de insumo en Pedidos/Recetas)
// se guarda tal cual y despues se interpola en innerHTML para otros roles --
// sin esto, cualquiera podia meter HTML/JS ahi y robar el token de sesion
// (localStorage) de quien abra esa pantalla despues.
function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

const GRUPOS_NAV = ['Operación diaria', 'Compras', 'Configuración'];

const SECCIONES = [
  { id: 'resumen',   label: 'Resumen',               grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: [] },
  { id: 'pedidos',   label: 'Pedidos',              grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'inventario', label: 'Inventario',          grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'mermas',    label: 'Mermas',                grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador', 'solicitante'] },
  { id: 'parstock',  label: 'Par Stock',             grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'recetas',   label: 'Recetas',               grupo: 'Operación diaria', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'proveedores', label: 'Proveedores',         grupo: 'Compras', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'facturas',  label: 'Recepción en Bodega',    grupo: 'Compras', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'facturas-dte', label: 'Facturas Odoo',         grupo: 'Compras', roles: ['administrador'], editRoles: ['administrador'] },
  { id: 'planilla-compras', label: 'Planilla de Compras', grupo: 'Compras', roles: ['administrador'], editRoles: ['administrador'] },
  { id: 'locales',   label: 'Locales',                grupo: 'Configuración', roles: ['administrador', 'solicitante', 'observador'], editRoles: ['administrador'] },
  { id: 'usuarios',  label: 'Usuarios',               grupo: 'Configuración', roles: ['administrador'], editRoles: ['administrador'] },
];

let state = {
  token: localStorage.getItem('token') || null,
  usuario: JSON.parse(localStorage.getItem('usuario') || 'null'),
  // Credenciales de Odoo de la persona conectada -- en sessionStorage
  // (nunca localStorage, nunca el backend): sobreviven a un F5 dentro de
  // la misma pestaña (para no pedirlas de nuevo en cada recarga) pero se
  // pierden solas al cerrar la pestaña o el navegador, y nunca tocan disco
  // de forma permanente ni la base de datos. Ver _guardarOdooSesion/
  // _limpiarOdooSesion.
  odooUsuario: sessionStorage.getItem('odooUsuario') || null,
  odooPassword: sessionStorage.getItem('odooPassword') || null,
  // Empresa de Odoo elegida para esta sesion -- solo se pregunta si el
  // usuario de Odoo tiene acceso a 2 o mas (ver GET /odoo/empresas).
  odooEmpresaId: sessionStorage.getItem('odooEmpresaId') || null,
  odooEmpresaNombre: sessionStorage.getItem('odooEmpresaNombre') || null,
  section: 'resumen',
  locales: [],
  facturasPendientes: null,
  planillaItems: null,
  planillaResumen: null,
  planillaFiltroFolio: '',
  dteCola: [],
  dteColaTimer: null,
  dteFiltroFolio: '',
  mermasDirty: false,
  navGrupoAbierto: 'Operación diaria',
};

window.addEventListener('beforeunload', (e) => {
  if (state.mermasDirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

function confirmarSalirMermas() {
  if (!state.mermasDirty) return true;
  const ok = confirm('Tienes cambios sin guardar en Mermas. ¿Salir de todas formas y perderlos?');
  if (ok) state.mermasDirty = false;
  return ok;
}

function seccion(id) { return SECCIONES.find(s => s.id === id); }
function puedeVer(s) { return state.usuario && s.roles.includes(state.usuario.rol); }
function puedeEditar(s) { return state.usuario && s.editRoles.includes(state.usuario.rol); }

const UNIDADES_CATALOGO = [
  { value: 'un', label: 'Und' },
  { value: 'kg', label: 'Kgs' },
  { value: 'porcion', label: 'Porción' },
];
const UNIDAD_LABEL = Object.fromEntries(UNIDADES_CATALOGO.map(u => [u.value, u.label]));
function formatUnidad(u) { return UNIDAD_LABEL[u] || escapeHtml(u); }
function unidadOptionsHtml(seleccionada) {
  return UNIDADES_CATALOGO.map(u => `<option value="${u.value}" ${u.value === seleccionada ? 'selected' : ''}>${u.label}</option>`).join('');
}

const DIAS_SEMANA = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

function fechaISOaLocal(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function lunesDeLaSemana(fechaISO) {
  const d = fechaISOaLocal(fechaISO);
  const diaSemana = (d.getDay() + 6) % 7; // 0=Lunes
  d.setDate(d.getDate() - diaSemana);
  return d;
}

function isoDeDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function etiquetaSemana(fechaISO) {
  const lunes = lunesDeLaSemana(fechaISO);
  const domingo = new Date(lunes);
  domingo.setDate(domingo.getDate() + 6);
  if (lunes.getMonth() === domingo.getMonth()) {
    return `Semana del ${lunes.getDate()} al ${domingo.getDate()} de ${MESES[lunes.getMonth()]}`;
  }
  return `Semana del ${lunes.getDate()} de ${MESES[lunes.getMonth()]} al ${domingo.getDate()} de ${MESES[domingo.getMonth()]}`;
}

function diasDeLaSemana(fechaISO) {
  const lunes = lunesDeLaSemana(fechaISO);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(lunes);
    d.setDate(d.getDate() + i);
    return { iso: isoDeDate(d), etiqueta: DIAS_SEMANA[i], numero: d.getDate() };
  });
}

// Credenciales de Odoo personales -- se piden una vez por sesion de pestaña
// (nunca se guardan en localStorage ni en el backend, ver definicion de
// state.odooUsuario/odooPassword mas arriba). Las 4 funciones api* de abajo
// comparten el mismo patron: si el backend responde 428 (faltan credenciales
// de Odoo, ver get_odoo_credentials en backend/deps.py), se pide el modal y
// se reintenta la misma llamada UNA sola vez. 401 sigue significando
// "sesion de la app expirada" y no se toca esa logica.

let _odooCredsPromise = null;

function _guardarOdooSesion() {
  sessionStorage.setItem('odooUsuario', state.odooUsuario || '');
  sessionStorage.setItem('odooPassword', state.odooPassword || '');
  if (state.odooEmpresaId) sessionStorage.setItem('odooEmpresaId', state.odooEmpresaId);
  if (state.odooEmpresaNombre) sessionStorage.setItem('odooEmpresaNombre', state.odooEmpresaNombre);
}

function _limpiarOdooSesion() {
  state.odooUsuario = null;
  state.odooPassword = null;
  state.odooEmpresaId = null;
  state.odooEmpresaNombre = null;
  sessionStorage.removeItem('odooUsuario');
  sessionStorage.removeItem('odooPassword');
  sessionStorage.removeItem('odooEmpresaId');
  sessionStorage.removeItem('odooEmpresaNombre');
}

function _odooHeaders() {
  if (!state.odooUsuario) return {};
  const headers = { 'X-Odoo-User': state.odooUsuario, 'X-Odoo-Password': state.odooPassword };
  if (state.odooEmpresaId) headers['X-Odoo-Company-Id'] = state.odooEmpresaId;
  return headers;
}

function pedirCredencialesOdoo(mensaje) {
  return new Promise((resolve, reject) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-box" style="width:380px">
        <h3 id="odoo-creds-title">Credenciales de Odoo</h3>
        <p class="placeholder" style="margin-bottom:1rem" id="odoo-creds-msg">${mensaje || 'Ingresa tu usuario y contraseña de Odoo para continuar.'}</p>
        <form id="odoo-creds-form">
          <div id="odoo-creds-login-fields">
            <label class="field-label">Usuario Odoo</label>
            <input type="text" id="odoo-creds-user" class="field" required autocomplete="username" style="width:100%;margin-bottom:0.75rem">
            <label class="field-label">Contraseña Odoo</label>
            <input type="password" id="odoo-creds-pass" class="field" required autocomplete="current-password" style="width:100%;margin-bottom:1rem">
          </div>
          <div id="odoo-creds-empresa-field" hidden>
            <label class="field-label">Empresa</label>
            <select id="odoo-creds-empresa" class="field" style="width:100%;margin-bottom:1rem"></select>
          </div>
          <p class="error-msg" id="odoo-creds-error"></p>
          <button type="submit" class="btn btn-primary" id="odoo-creds-submit">Entrar</button>
          <button type="button" class="btn" id="odoo-creds-cancel">Cancelar</button>
        </form>
      </div>`;
    document.body.appendChild(overlay);

    const loginFields = overlay.querySelector('#odoo-creds-login-fields');
    const empresaField = overlay.querySelector('#odoo-creds-empresa-field');
    const empresaSelect = overlay.querySelector('#odoo-creds-empresa');
    const submitBtn = overlay.querySelector('#odoo-creds-submit');
    const errorEl = overlay.querySelector('#odoo-creds-error');
    let paso = 'login';

    overlay.querySelector('#odoo-creds-cancel').onclick = () => {
      overlay.remove();
      reject(new Error('Ingreso a Odoo cancelado'));
    };

    overlay.querySelector('#odoo-creds-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      errorEl.textContent = '';

      if (paso === 'login') {
        const usuario = overlay.querySelector('#odoo-creds-user').value.trim();
        const password = overlay.querySelector('#odoo-creds-pass').value;
        if (!usuario || !password) return;

        submitBtn.disabled = true;
        submitBtn.textContent = 'Conectando…';
        let empresas = [];
        let credencialesMalas = false;
        try {
          const res = await fetch('/odoo/empresas', {
            headers: {
              ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
              'X-Odoo-User': usuario, 'X-Odoo-Password': password,
            },
          });
          if (res.ok) {
            empresas = await res.json();
          } else if (res.status === 428) {
            // Credenciales de Odoo rechazadas -- se avisa aca mismo en vez
            // de guardarlas igual y descubrirlo recien en el reintento de
            // la accion original.
            credencialesMalas = true;
            const body = await res.json().catch(() => ({}));
            errorEl.textContent = typeof body.detail === 'string' ? body.detail : 'Credenciales de Odoo incorrectas.';
          }
          // Otros codigos (500, etc.) se ignoran aca y se sigue de largo --
          // el reintento de la accion original ya valida en serio y muestra
          // su propio error si algo sigue mal.
        } catch (_) {
          // Error de red -- igual, se sigue de largo.
        }
        submitBtn.disabled = false;
        submitBtn.textContent = 'Entrar';

        if (credencialesMalas) return;

        state.odooUsuario = usuario;
        state.odooPassword = password;
        _guardarOdooSesion();

        if (empresas.length > 1) {
          loginFields.hidden = true;
          empresaField.hidden = false;
          empresaSelect.innerHTML = empresas.map(emp => `<option value="${emp.id}">${escapeHtml(emp.name)}</option>`).join('');
          overlay.querySelector('#odoo-creds-title').textContent = 'Elige la empresa';
          overlay.querySelector('#odoo-creds-msg').textContent =
            'Tu usuario de Odoo tiene acceso a varias empresas -- elige con cuál vas a trabajar en esta sesión.';
          paso = 'empresa';
          empresaSelect.focus();
          return;
        }

        if (empresas.length === 1) {
          state.odooEmpresaId = String(empresas[0].id);
          state.odooEmpresaNombre = empresas[0].name;
          _guardarOdooSesion();
          _actualizarUserInfo();
        }
        overlay.remove();
        resolve();
        return;
      }

      const elegida = empresaSelect.selectedOptions[0];
      state.odooEmpresaId = elegida.value;
      state.odooEmpresaNombre = elegida.textContent;
      _guardarOdooSesion();
      _actualizarUserInfo();
      overlay.remove();
      resolve();
    });

    overlay.querySelector('#odoo-creds-user').focus();
  });
}

async function elegirEmpresaOdoo() {
  if (!state.odooUsuario) return;
  let empresas = [];
  try {
    const res = await fetch('/odoo/empresas', {
      headers: {
        ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
        ..._odooHeaders(),
      },
    });
    if (res.ok) empresas = await res.json();
    else if (res.status === 428) { alert('Tu sesión de Odoo expiró -- vuelve a intentar la acción que estabas haciendo para reconectarte.'); return; }
  } catch (err) {
    alert('No se pudo consultar las empresas de Odoo: ' + err.message);
    return;
  }
  if (empresas.length < 2) {
    alert('Tu usuario de Odoo solo tiene acceso a una empresa -- no hay entre qué elegir.');
    return;
  }

  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-box" style="width:380px">
        <h3>Cambiar empresa</h3>
        <p class="placeholder" style="margin-bottom:1rem">Elige con cuál empresa de Odoo vas a trabajar ahora.</p>
        <form id="odoo-empresa-form">
          <select id="odoo-empresa-select" class="field" style="width:100%;margin-bottom:1rem">
            ${empresas.map(emp => `<option value="${emp.id}" ${String(emp.id) === state.odooEmpresaId ? 'selected' : ''}>${escapeHtml(emp.name)}</option>`).join('')}
          </select>
          <button type="submit" class="btn btn-primary">Cambiar</button>
          <button type="button" class="btn" id="odoo-empresa-cancel">Cancelar</button>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#odoo-empresa-cancel').onclick = () => { overlay.remove(); resolve(); };
    overlay.querySelector('#odoo-empresa-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const elegida = overlay.querySelector('#odoo-empresa-select').selectedOptions[0];
      state.odooEmpresaId = elegida.value;
      state.odooEmpresaNombre = elegida.textContent;
      _guardarOdooSesion();
      _actualizarUserInfo();
      overlay.remove();
      resolve();
    });
  });
}

function asegurarCredencialesOdoo(mensaje) {
  if (state.odooUsuario && state.odooPassword) return Promise.resolve();
  if (!_odooCredsPromise) {
    _odooCredsPromise = pedirCredencialesOdoo(mensaje).finally(() => { _odooCredsPromise = null; });
  }
  return _odooCredsPromise;
}

async function api(path, options = {}) {
  const doFetch = () => fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ..._odooHeaders(),
      ...(options.headers || {}),
    },
  });
  let res = await doFetch();
  if (res.status === 428) {
    const body = await res.json().catch(() => ({}));
    await asegurarCredencialesOdoo(body.detail);
    res = await doFetch();
    if (res.status === 428) { _limpiarOdooSesion(); }
  }
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let msg = `Error ${res.status}`;
    if (typeof body.detail === 'string') msg = body.detail;
    else if (Array.isArray(body.detail)) msg = body.detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

async function apiUpload(path, formData) {
  const doFetch = () => fetch(path, {
    method: 'POST',
    headers: { ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ..._odooHeaders() },
    body: formData,
  });
  let res = await doFetch();
  if (res.status === 428) {
    const body = await res.json().catch(() => ({}));
    await asegurarCredencialesOdoo(body.detail);
    res = await doFetch();
    if (res.status === 428) { _limpiarOdooSesion(); }
  }
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let msg = `Error ${res.status}`;
    if (typeof body.detail === 'string') msg = body.detail;
    else if (Array.isArray(body.detail)) msg = body.detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    throw new Error(msg);
  }
  return res.json();
}

async function apiDownload(path, filename) {
  const doFetch = () => fetch(path, {
    headers: { ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ..._odooHeaders() },
  });
  let res = await doFetch();
  if (res.status === 428) {
    const body = await res.json().catch(() => ({}));
    await asegurarCredencialesOdoo(body.detail);
    res = await doFetch();
    if (res.status === 428) { _limpiarOdooSesion(); }
  }
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Error ${res.status}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function apiViewBlob(path) {
  const doFetch = () => fetch(path, {
    headers: { ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ..._odooHeaders() },
  });
  let res = await doFetch();
  if (res.status === 428) {
    const body = await res.json().catch(() => ({}));
    await asegurarCredencialesOdoo(body.detail);
    res = await doFetch();
    if (res.status === 428) { _limpiarOdooSesion(); }
  }
  if (res.status === 401) {
    logout();
    throw new Error('Sesión expirada');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Error ${res.status}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank');
  // No se revoca la URL enseguida -- la pestaña nueva la sigue necesitando para mostrar el archivo.
}

// ---------- Auth ----------

function showLogin() {
  document.getElementById('login-view').hidden = false;
  document.getElementById('app-view').hidden = true;
}

function _actualizarUserInfo() {
  const el = document.getElementById('user-info');
  if (!el || !state.usuario) return;
  const base = `${state.usuario.nombre} · ${state.usuario.rol}`;
  if (!state.odooEmpresaNombre) {
    el.textContent = base;
    return;
  }
  el.textContent = `${base} · Odoo: ${state.odooEmpresaNombre} `;
  const cambiar = document.createElement('button');
  cambiar.type = 'button';
  cambiar.className = 'btn-link';
  cambiar.textContent = '(cambiar)';
  cambiar.onclick = () => elegirEmpresaOdoo();
  el.appendChild(cambiar);
}

function showApp() {
  document.getElementById('login-view').hidden = true;
  document.getElementById('app-view').hidden = false;
  _actualizarUserInfo();
  renderNav();
  renderView();
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('usuario');
  state.token = null;
  state.usuario = null;
  _limpiarOdooSesion();
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

// ---------- Generar OC ----------
// Usa la cuenta de servicio de Odoo configurada en el servidor -- ya no
// pide credenciales al usuario (mismo patrón que Ingreso de Facturas).

async function generarOC(pedidoId, btn) {
  if (!confirm('¿Generar la Orden de Compra / avisos de este pedido? Esto crea la OC real en Odoo (o envía el correo al proveedor) y no se puede deshacer desde aquí.')) return;
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Creando…';
  try {
    const res = await api(`/pedidos/${pedidoId}/generar-oc`, { method: 'POST' });
    const lineas = res.acciones.map(a => {
      const base = a.tipo === 'odoo' ? `✓ OC creada en Odoo: ${a.po_name} (${a.proveedor})` : `✉ Aviso enviado por correo a ${a.proveedor}`;
      return a.aviso ? `${base}\n  ⚠ ${a.aviso}` : base;
    });
    let msg = lineas.join('\n');
    if (res.omitidos && res.omitidos.length) {
      msg += `\n\nInsumos omitidos (sin proveedor registrado): ${res.omitidos.join(', ')}`;
    }
    alert(msg);
    renderView();
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.textContent = original;
  }
}

// ---------- Buscar facturas nuevas ----------

async function buscarFacturasNuevas(btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Buscando…';
  try {
    state.facturasPendientes = await api('/facturas/buscar', { method: 'POST' });
    renderView();
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
    btn.textContent = original;
  }
}

// ---------- Nav ----------

function renderNav() {
  const nav = document.getElementById('nav-list');
  nav.innerHTML = '';
  GRUPOS_NAV.forEach((grupo) => {
    const items = SECCIONES.filter(s => s.grupo === grupo && puedeVer(s));
    if (!items.length) return;
    const abierto = state.navGrupoAbierto === grupo;

    const h = document.createElement('button');
    h.type = 'button';
    h.className = 'nav-group-toggle' + (abierto ? ' open' : '');
    h.setAttribute('aria-expanded', abierto ? 'true' : 'false');
    h.innerHTML = `<span>${grupo}</span><span class="nav-group-caret">${abierto ? '▾' : '▸'}</span>`;
    h.onclick = () => {
      state.navGrupoAbierto = abierto ? null : grupo;
      renderNav();
    };
    nav.appendChild(h);

    if (abierto) {
      items.forEach((s) => {
        const a = document.createElement('a');
        a.textContent = s.label;
        a.className = 'nav-item' + (s.id === state.section ? ' active' : '');
        a.onclick = () => {
          if (state.section === 'mermas' && s.id !== 'mermas' && !confirmarSalirMermas()) return;
          state.section = s.id; renderNav(); renderView();
        };
        nav.appendChild(a);
      });
    }
  });
}

// ---------- Views ----------

async function renderView() {
  const el = document.getElementById('view-content');
  el.innerHTML = '<p class="placeholder">Cargando…</p>';
  const s = seccion(state.section);
  try {
    if (state.section === 'resumen') return renderResumen(el, s);
    if (state.section === 'pedidos') return renderPedidos(el, s);
    if (state.section === 'locales') return renderLocales(el, s);
    if (state.section === 'inventario') return renderInventario(el, s);
    if (state.section === 'mermas') return renderMermas(el, s);
    if (state.section === 'parstock') return renderParStock(el, s);
    if (state.section === 'proveedores') return renderProveedores(el, s);
    if (state.section === 'recetas') return renderRecetas(el, s);
    if (state.section === 'usuarios') return renderUsuarios(el, s);
    if (state.section === 'facturas') return renderFacturas(el, s);
    if (state.section === 'facturas-dte') return renderFacturasDte(el, s);
    if (state.section === 'planilla-compras') return renderPlanillaCompras(el, s);
    return renderPlaceholder(el, s);
  } catch (err) {
    el.innerHTML = `<p class="error-msg">${err.message}</p>`;
  }
}

async function renderResumen(el, s) {
  const esAdmin = state.usuario.rol === 'administrador';
  const locales = await api('/locales');

  const mermasPorLocal = await Promise.all(locales.map(l =>
    api(`/mermas?local_id=${l.id}`).then(items => ({ local: l.nombre, items })).catch(() => ({ local: l.nombre, items: [] }))
  ));

  const mermasResumen = mermasPorLocal
    .map(({ local, items }) => items.length
      ? { local, total: items.length, faltan: items.filter(i => i.cantidad_informada === null || i.cantidad_informada === undefined).length }
      : null)
    .filter(Boolean);

  let facturasPendientesCount = null;
  let planillaResumen = null;
  if (esAdmin) {
    const hoy = new Date();
    const primerDiaMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    const desde = primerDiaMes.toISOString().slice(0, 10);
    const hasta = hoy.toISOString().slice(0, 10);
    const [dte, planilla] = await Promise.all([
      api(`/facturas-dte?desde=${desde}&hasta=${hasta}`).catch(() => null),
      api(`/planilla-compras?anio=${hoy.getFullYear()}&mes=${hoy.getMonth() + 1}`).catch(() => null),
    ]);
    facturasPendientesCount = dte ? dte.length : null;
    planillaResumen = planilla ? planilla.resumen : null;
  }

  const claseCantidad = (n) => n > 0 ? 'resumen-valor-gold' : 'resumen-valor-good';

  el.innerHTML = `
    <h2>Resumen</h2>
    <p class="placeholder" style="margin-bottom:1.25rem">Lo que conviene revisar hoy, de un vistazo.</p>
    <div class="resumen-grid">
      <div class="resumen-card" data-ir="mermas" tabindex="0" role="button">
        <div class="resumen-card-label">Mermas de ayer</div>
        ${mermasResumen.length
          ? mermasResumen.map(m => `
              <div class="resumen-card-sub">${m.local}: ${m.faltan
                ? `<span class="resumen-valor-gold">${m.faltan} de ${m.total} sin cargar</span>`
                : `<span class="resumen-valor-good">completo</span>`}</div>`).join('')
          : '<div class="resumen-card-sub placeholder">Sin insumos de seguimiento configurados</div>'}
      </div>
      ${esAdmin ? `
      <div class="resumen-card" data-ir="facturas-dte" tabindex="0" role="button">
        <div class="resumen-card-label">Facturas Odoo pendientes (mes actual)</div>
        <div class="resumen-card-valor ${facturasPendientesCount === null ? '' : claseCantidad(facturasPendientesCount)}">
          ${facturasPendientesCount === null ? '—' : facturasPendientesCount}
        </div>
      </div>
      <div class="resumen-card" data-ir="planilla-compras" tabindex="0" role="button">
        <div class="resumen-card-label">% Costo Venta (este mes)</div>
        <div class="resumen-card-valor ${planillaResumen && planillaResumen.pct_costo_venta != null
          ? (planillaResumen.pct_costo_venta <= planillaResumen.meta_pct ? 'resumen-valor-good' : 'resumen-valor-danger')
          : ''}">
          ${planillaResumen && planillaResumen.pct_costo_venta != null ? (planillaResumen.pct_costo_venta * 100).toFixed(1) + '%' : '—'}
        </div>
        ${!planillaResumen || planillaResumen.pct_costo_venta == null ? '<div class="resumen-card-sub placeholder">Falta cargar la Venta del Período</div>' : ''}
      </div>` : ''}
    </div>`;

  el.querySelectorAll('[data-ir]').forEach(card => {
    card.onclick = () => { state.section = card.dataset.ir; renderNav(); renderView(); };
    card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); } };
  });
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
          ${locales.map(l => `<tr><td>${escapeHtml(l.nombre)}</td><td>${l.activo ? 'Activo' : 'Inactivo'}</td></tr>`).join('')}
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
        <p class="placeholder" style="margin-bottom:1rem">Para proveedores sin integración a Odoo, se envía un correo con el pedido a este destinatario. Para Doña Sofía (Odoo), se envía la OC en PDF. Asunto siempre: "Pedido {local}".</p>
        <form id="config-email-form">
          <div class="item-row">
            <input class="field" id="config-destinatario" type="email" placeholder="correo@margo.cl" style="flex:1" value="${config ? config.destinatario : ''}" required>
            <input class="field" id="config-cc" placeholder="Con copia (separados por coma, opcional)" style="flex:1" value="${config && config.cc ? config.cc : ''}">
          </div>
          <button type="submit" class="btn btn-primary">Guardar</button>
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
        ${proveedores.map(p => `<option value="${p.id}" ${p.id === provId ? 'selected' : ''}>${escapeHtml(p.nombre)}${p.usa_odoo ? ' (Odoo)' : ''}</option>`).join('')}
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
            <select class="field" id="prod-unidad" required>${unidadOptionsHtml('kg')}</select>
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
          <input class="field" id="prod-empaque" type="number" step="0.01" placeholder="Formato / cantidad por paquete (misma unidad de arriba)" style="max-width:260px;margin-bottom:.75rem">
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
              <td>${escapeHtml(p.nombre)} (${formatUnidad(p.unidad)})</td>
              <td>${escapeHtml(p.odoo_name)}</td>
              <td>${p.ref ? escapeHtml(p.ref) : '—'}</td>
              <td>${editable ? `<input class="field prod-edit-precio" data-key="${p.ingrediente_key}" type="number" style="width:90px" value="${p.precio}">` : p.precio}</td>
              <td>
                ${editable
                  ? `<input class="field prod-edit-empaque" data-key="${p.ingrediente_key}" type="number" step="0.01" style="width:90px" placeholder="A granel" value="${p.tamano_empaque ?? ''}">`
                  : (p.tamano_empaque ? `${p.tamano_empaque} ${formatUnidad(p.unidad)}/paquete` : 'A granel')}
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
          body: JSON.stringify({
            destinatario: document.getElementById('config-destinatario').value.trim(),
            cc: document.getElementById('config-cc').value.trim() || null,
          }),
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
  const etiqueta = (p) => `${escapeHtml(p.nombre)} (${escapeHtml(p.sku)})`;

  el.innerHTML = `
    <h2>Recetas</h2>
    <label class="field-label">Local</label>
    <select id="rec-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${escapeHtml(l.nombre)}</option>`).join('')}
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
        <h3>${escapeHtml(p.nombre)} <span class="placeholder">(${escapeHtml(p.sku)})</span></h3>
        <table>
          <thead><tr><th>Insumo</th><th>Cantidad</th><th>Unidad</th>${editable ? '<th></th>' : ''}</tr></thead>
          <tbody>
            ${p.lineas.map(l => `
              <tr>
                <td>${escapeHtml(l.ingrediente)}</td><td>${l.cantidad}</td><td>${escapeHtml(l.unidad)}</td>
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

  const nombreLocal = (id) => escapeHtml((locales.find(l => l.id === id) || {}).nombre || id);
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
                <input type="checkbox" class="usr-local-chk" value="${l.id}"> ${escapeHtml(l.nombre)}
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
              <td>${escapeHtml(u.nombre)}</td>
              <td>${escapeHtml(u.email)}</td>
              <td><span class="badge ${badgeClass[u.rol] || ''}">${u.rol}</span></td>
              <td>${u.locales.map(nombreLocal).join(', ') || '—'}</td>
              <td>${u.activo ? 'Activo' : 'Inactivo'}</td>
              ${editable ? `<td>
                <button class="btn" data-editar="${u.id}">Editar</button>
                <button class="btn" data-toggle-activo="${u.id}" data-val="${!u.activo}">${u.activo ? 'Desactivar' : 'Activar'}</button>
                ${u.id !== state.usuario.id ? `<button class="btn btn-reject" data-eliminar="${u.id}" data-nombre="${escapeHtml(u.nombre)}">Eliminar</button>` : ''}
              </td>` : ''}
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

    el.querySelectorAll('button[data-editar]').forEach(btn => {
      btn.onclick = () => showEditarUsuarioModal(usuarios.find(u => u.id === btn.dataset.editar), locales);
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

    el.querySelectorAll('button[data-eliminar]').forEach(btn => {
      btn.onclick = async () => {
        if (!confirm(`¿Eliminar a ${btn.dataset.nombre}? Esta acción no se puede deshacer.`)) return;
        try {
          await api(`/usuarios/${btn.dataset.eliminar}`, { method: 'DELETE' });
          renderView();
        } catch (err) {
          alert(err.message);
        }
      };
    });
  }
}

function showEditarUsuarioModal(usuario, locales) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal-box" style="width:420px">
      <h3>Editar usuario</h3>
      <form id="edit-usr-form">
        <label class="field-label">Nombre</label>
        <input class="field" id="edit-usr-nombre" style="width:100%;margin-bottom:.75rem" required value="${escapeHtml(usuario.nombre)}">
        <label class="field-label">Rol</label>
        <select id="edit-usr-rol" class="field" style="width:100%;margin-bottom:.75rem">
          <option value="solicitante" ${usuario.rol === 'solicitante' ? 'selected' : ''}>Solicitante</option>
          <option value="administrador" ${usuario.rol === 'administrador' ? 'selected' : ''}>Administrador</option>
          <option value="observador" ${usuario.rol === 'observador' ? 'selected' : ''}>Observador</option>
        </select>
        <div style="margin-bottom:.75rem">
          <label class="field-label">Locales asignados (solo aplica a Solicitante)</label>
          ${locales.map(l => `
            <label style="font-size:.8rem;color:var(--t2);margin-right:1rem">
              <input type="checkbox" class="edit-usr-local-chk" value="${l.id}" ${usuario.locales.includes(l.id) ? 'checked' : ''}> ${escapeHtml(l.nombre)}
            </label>`).join('')}
        </div>
        <label class="field-label">Nueva contraseña</label>
        <input class="field" id="edit-usr-password" type="password" placeholder="Dejar en blanco para no cambiarla" style="width:100%;margin-bottom:1rem">
        <button type="submit" class="btn btn-primary">Guardar</button>
        <button type="button" class="btn" id="edit-usr-cancel">Cancelar</button>
        <p id="edit-usr-error" class="error-msg"></p>
      </form>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#edit-usr-cancel').onclick = () => overlay.remove();
  overlay.querySelector('#edit-usr-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = overlay.querySelector('#edit-usr-error');
    const password = overlay.querySelector('#edit-usr-password').value;
    const body = {
      nombre: overlay.querySelector('#edit-usr-nombre').value.trim(),
      rol: overlay.querySelector('#edit-usr-rol').value,
      locales: Array.from(overlay.querySelectorAll('.edit-usr-local-chk:checked')).map(c => c.value),
    };
    if (password) body.password = password;
    try {
      await api(`/usuarios/${usuario.id}`, { method: 'PATCH', body: JSON.stringify(body) });
      overlay.remove();
      renderView();
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });
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
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${escapeHtml(l.nombre)}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Agregar a Par Stock</h3>
        ${!disponibles.length ? '<p class="placeholder">No hay insumos del catálogo de Proveedores disponibles para agregar (o ya están todos agregados). Ve a la sección Proveedores para registrar más.</p>' : `
        <form id="ps-form">
          <div class="item-row">
            <select id="ps-insumo" class="field" style="flex:2" required>
              ${disponibles.map(p => `<option value="${p.ingrediente_key}">${escapeHtml(p.nombre)} (${formatUnidad(p.unidad)})</option>`).join('')}
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
        <thead><tr>${editable ? '<th><input type="checkbox" id="ps-check-all"></th>' : ''}<th>Insumo</th><th>Par Stock</th><th>Nombre Odoo</th><th>Proveedor</th><th>Formato</th>${editable ? '<th>Acciones</th>' : ''}</tr></thead>
        <tbody>
          ${items.map(i => `
            <tr>
              ${editable ? `<td><input type="checkbox" class="ps-check" data-key="${i.ingrediente_key}"></td>` : ''}
              <td>${escapeHtml(i.nombre)} (${formatUnidad(i.unidad)})</td>
              <td>${editable ? `<input class="field ps-edit-par" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:90px" value="${i.par_cantidad}">` : i.par_cantidad}</td>
              <td>${i.odoo_name ? escapeHtml(i.odoo_name) : '—'}</td>
              <td>${i.supplier_name ? escapeHtml(i.supplier_name) : '—'}</td>
              <td>
                ${editable
                  ? `<input class="field ps-edit-empaque" data-key="${i.ingrediente_key}" data-prov="${i.proveedor_id || ''}" type="number" step="0.01" style="width:90px" placeholder="A granel (${formatUnidad(i.unidad)}/paquete)" value="${i.tamano_empaque ?? ''}">`
                  : (i.tamano_empaque ? `${i.tamano_empaque} ${formatUnidad(i.unidad)}/paquete` : 'A granel')}
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

  const [items, stockPendiente] = await Promise.all([
    api(`/inventario?local_id=${localId}`),
    editable ? api('/inventario/stock-pendiente').catch(() => []) : Promise.resolve([]),
  ]);

  el.innerHTML = `
    <h2>Inventario de Bodega</h2>
    <label class="field-label">Local</label>
    <select id="inv-local" class="field" style="margin-bottom:1.25rem;width:100%;max-width:280px">
      ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${escapeHtml(l.nombre)}</option>`).join('')}
    </select>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Registrar movimiento</h3>
        <p class="placeholder" style="margin-bottom:.75rem">Para egresos (mermas, pérdidas) y ajustes (corrección tras un conteo físico) -- los ingresos por factura ahora se suman solos desde Facturas Odoo.</p>
        <form id="mov-form">
          <div class="item-row">
            <select id="mov-insumo" class="field" style="flex:2" required>
              ${items.map(i => `<option value="${i.ingrediente_key}">${escapeHtml(i.nombre)} (${formatUnidad(i.unidad)})</option>`).join('')}
            </select>
            <select id="mov-tipo" class="field">
              <option value="egreso">Egreso</option>
              <option value="ajuste">Ajuste</option>
            </select>
            <input id="mov-cantidad" class="field" type="number" step="0.01" placeholder="Cantidad" required>
          </div>
          <input id="mov-nota" class="field" style="width:100%;margin-bottom:.75rem" placeholder="Nota (opcional)">
          <button type="submit" class="btn btn-primary">Registrar</button>
          <p id="mov-error" class="error-msg"></p>
        </form>
      </div>
      <div style="margin-bottom:1rem">
        <button type="button" class="btn" id="inv-stock-inicial-btn">Cargar stock inicial por proveedor</button>
      </div>
      ${stockPendiente.length ? `
      <div class="card" style="margin-bottom:1.25rem">
        <h3>Stock pendiente de sumar (${stockPendiente.length})</h3>
        <p class="placeholder" style="margin-bottom:.75rem">Productos de facturas de Facturas Odoo que todavía no tienen insumo asociado (o el local todavía no tiene mapeo a su empresa de Odoo) -- una vez que agregues el mapeo que falta, tocá "Actualizar" para sumarlos al stock.</p>
        <table>
          <thead><tr><th>Producto</th><th>Cantidad</th><th>Proveedor</th><th>Factura</th><th>Motivo</th></tr></thead>
          <tbody>
            ${stockPendiente.map(p => `
              <tr>
                <td>${escapeHtml(p.producto_nombre)}</td>
                <td>${p.cantidad}</td>
                <td>${p.proveedor_nombre ? escapeHtml(p.proveedor_nombre) : '—'}</td>
                <td>${p.invoice_name ? escapeHtml(p.invoice_name) : '—'}</td>
                <td>${p.motivo === 'sin_local' ? 'Local sin mapeo a Odoo' : 'Producto sin insumo asociado'}</td>
              </tr>`).join('')}
          </tbody>
        </table>
        <button type="button" class="btn btn-primary" id="inv-stock-pendiente-actualizar" style="margin-top:.75rem">Actualizar</button>
        <p id="inv-stock-pendiente-error" class="error-msg"></p>
      </div>` : ''}` : ''}
    <div class="card">
      <table>
        <thead><tr><th>Insumo</th><th>Unidad</th><th>Par Stock</th><th>Stock Bodega actual</th></tr></thead>
        <tbody>
          ${items.map(i => `
            <tr>
              <td>${escapeHtml(i.nombre)}</td>
              <td>${formatUnidad(i.unidad)}</td>
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

    document.getElementById('inv-stock-inicial-btn').addEventListener('click', () => {
      showStockInicialModal(localId, items);
    });

    document.getElementById('inv-stock-pendiente-actualizar')?.addEventListener('click', async (e) => {
      const btn = e.target;
      const errorEl = document.getElementById('inv-stock-pendiente-error');
      btn.disabled = true;
      btn.textContent = 'Actualizando…';
      try {
        const res = await api('/inventario/stock-pendiente/reprocesar', { method: 'POST' });
        if (res.resueltos === 0) {
          errorEl.textContent = 'Todavía no hay ningún mapeo nuevo que resuelva lo pendiente.';
          btn.disabled = false;
          btn.textContent = 'Actualizar';
        } else {
          renderView();
        }
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Actualizar';
        errorEl.textContent = err.message;
      }
    });
  }
}

async function showStockInicialModal(localId, itemsLocal) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:640px"><p class="placeholder">Cargando…</p></div>';
  document.body.appendChild(overlay);

  const proveedores = await api('/proveedores');

  async function renderPaso(proveedorId) {
    const box = overlay.querySelector('.modal-box');
    if (!proveedorId) {
      box.innerHTML = `
        <h3>Cargar stock inicial por proveedor</h3>
        <p class="placeholder" style="margin-bottom:1rem">Elige el proveedor -- se muestran solo sus insumos que ya tienen Par Stock definido en este local.</p>
        <label class="field-label">Proveedor</label>
        <select id="stock-inicial-proveedor" class="field" style="width:100%;margin-bottom:1rem">
          <option value="">Elige un proveedor…</option>
          ${proveedores.map(p => `<option value="${p.id}">${escapeHtml(p.nombre)}</option>`).join('')}
        </select>
        <button type="button" class="btn" id="stock-inicial-cancelar">Cancelar</button>`;
      box.querySelector('#stock-inicial-cancelar').onclick = () => overlay.remove();
      box.querySelector('#stock-inicial-proveedor').addEventListener('change', (e) => {
        if (e.target.value) renderPaso(e.target.value);
      });
      return;
    }

    box.innerHTML = '<p class="placeholder">Buscando insumos del proveedor…</p>';
    const productos = await api(`/proveedores/${proveedorId}/productos`);
    const keysProveedor = new Set(productos.map(p => p.ingrediente_key));
    const filas = itemsLocal.filter(i => keysProveedor.has(i.ingrediente_key));

    if (!filas.length) {
      box.innerHTML = `
        <h3>Cargar stock inicial por proveedor</h3>
        <p class="placeholder" style="margin-bottom:1rem">Ninguno de los insumos de este proveedor tiene Par Stock definido en este local todavía -- primero hay que agregarlos en Par Stock.</p>
        <button type="button" class="btn" id="stock-inicial-cerrar">Cerrar</button>`;
      box.querySelector('#stock-inicial-cerrar').onclick = () => overlay.remove();
      return;
    }

    box.innerHTML = `
      <h3>Cargar stock inicial por proveedor</h3>
      <p class="placeholder" style="margin-bottom:1rem">Ingresa la cantidad contada de cada insumo -- se guarda como un "Ajuste" (se suma al stock actual, que hoy es el que se ve acá). Deja en blanco los que no quieras tocar.</p>
      <div style="max-height:360px;overflow-y:auto">
        <table>
          <thead><tr><th>Insumo</th><th>Unidad</th><th>Stock actual</th><th>Cantidad inicial</th></tr></thead>
          <tbody>
            ${filas.map(i => `
              <tr>
                <td>${escapeHtml(i.nombre)}</td>
                <td>${formatUnidad(i.unidad)}</td>
                <td>${i.stock_bodega}</td>
                <td><input type="number" step="0.01" class="field stock-inicial-input" data-key="${i.ingrediente_key}" style="width:110px"></td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
      <p class="error-msg" id="stock-inicial-error"></p>
      <div style="margin-top:1rem">
        <button type="button" class="btn btn-primary" id="stock-inicial-guardar">Guardar</button>
        <button type="button" class="btn" id="stock-inicial-cancelar">Cancelar</button>
      </div>`;

    box.querySelector('#stock-inicial-cancelar').onclick = () => overlay.remove();
    box.querySelector('#stock-inicial-guardar').addEventListener('click', async () => {
      const errorEl = box.querySelector('#stock-inicial-error');
      errorEl.textContent = '';
      const inputs = Array.from(box.querySelectorAll('.stock-inicial-input'))
        .filter(inp => inp.value.trim() !== '');
      if (!inputs.length) { errorEl.textContent = 'Ingresa al menos una cantidad.'; return; }
      const btn = box.querySelector('#stock-inicial-guardar');
      btn.disabled = true;
      btn.textContent = 'Guardando…';
      try {
        for (const inp of inputs) {
          await api('/inventario/movimiento', {
            method: 'POST',
            body: JSON.stringify({
              local_id: localId, ingrediente_key: inp.dataset.key, tipo: 'ajuste',
              cantidad: parseFloat(inp.value) || 0, nota: 'Stock inicial',
            }),
          });
        }
        overlay.remove();
        renderView();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Guardar';
        errorEl.textContent = err.message;
      }
    });
  }

  await renderPaso(null);
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

  const ayerIso = (() => { const d = new Date(); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); })();
  const fecha = state.mermasFecha || ayerIso;
  state.mermasFecha = fecha;
  const items = await api(`/mermas?local_id=${localId}&fecha=${fecha}`);
  const proteinas = await api(`/mermas/proteinas?local_id=${localId}&fecha=${fecha}`);
  const pasteleria = await api(`/mermas/pasteleria?local_id=${localId}&fecha=${fecha}`);
  const chocolates = await api(`/mermas/chocolates?local_id=${localId}&fecha=${fecha}`);
  const resumenSemana = await api(`/mermas/resumen-semana?local_id=${localId}&fecha=${fecha}`);

  const diasSemana = diasDeLaSemana(fecha);

  el.innerHTML = `
    <h2>Mermas — Stock de Cocina</h2>
    <div class="item-row" style="max-width:560px">
      <div style="flex:1">
        <label class="field-label">Local</label>
        <select id="mermas-local" class="field" style="width:100%">
          ${locales.map(l => `<option value="${l.id}" ${l.id === localId ? 'selected' : ''}>${escapeHtml(l.nombre)}</option>`).join('')}
        </select>
      </div>
      <div style="flex:1">
        <label class="field-label">Ir a fecha</label>
        <input type="date" id="mermas-fecha" class="field" style="width:100%" value="${fecha}">
      </div>
      <div style="display:flex;align-items:flex-end;gap:.5rem">
        <button type="button" id="mermas-exportar" class="btn">Exportar Excel</button>
        <button type="button" id="mermas-reporte-pdf-ver" class="btn">Ver Reporte de Ventas</button>
        <button type="button" id="mermas-reporte-pdf" class="btn">Descargar PDF</button>
      </div>
    </div>
    <h3 style="margin:1rem 0 .5rem">${etiquetaSemana(fecha)}</h3>
    <div class="item-row" style="gap:.4rem;margin-bottom:.75rem">
      ${diasSemana.map(d => `
        <button type="button" class="btn ${d.iso === fecha ? 'btn-primary' : ''}" data-dia-semana="${d.iso}">${d.etiqueta} ${d.numero}</button>
      `).join('')}
    </div>
    <p class="placeholder" style="margin:.5rem 0 1.25rem">Ventas y Entregas se calculan solas (ventas viene de la descarga automática diaria) -- por defecto se muestra AYER, que es el día que ya tiene esos datos completos.</p>
    <p id="export-error" class="error-msg"></p>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    <div class="card">
      <h3>Resumen de Diferencias -- ${etiquetaSemana(fecha)}</h3>
      <p class="placeholder" style="margin-bottom:1rem">Diferencia acumulada Lunes a Viernes por insumo, y el $ estimado en faltantes (solo cuando la diferencia es negativa) -- igual que la hoja resumen de la planilla real.</p>
      <table>
        <thead><tr><th>Insumo</th><th>Diferencia total</th><th>Precio</th><th>Total $ faltante</th></tr></thead>
        <tbody>
          ${resumenSemana.length ? resumenSemana.map(r => `
            <tr>
              <td>${escapeHtml(r.nombre)}</td>
              <td style="${r.diferencia_total < 0 ? 'color:var(--danger,#e07a7a)' : ''}">${r.diferencia_total.toFixed(2)} ${formatUnidad(r.unidad)}</td>
              <td>${r.precio ? '$' + r.precio.toLocaleString('es-CL') : '—'}</td>
              <td>${r.total_dscto ? '$' + Math.abs(r.total_dscto).toLocaleString('es-CL') : '—'}</td>
            </tr>`).join('') : `<tr><td colspan="4" class="placeholder">Sin datos de Stock Informado esta semana todavía.</td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="card">
      <table>
        <thead><tr>
          <th>Insumo</th><th>Unidad</th><th>Stock Inicial</th><th>Entregas</th><th>Ventas</th>
          <th>Mermas</th><th>Stock Real</th><th>Stock Informado</th><th>Diferencia</th>
        </tr></thead>
        <tbody>
          ${items.map(i => {
            const stockReal = i.stock_inicial + i.entregas - i.ventas - (i.mermas_total || 0);
            const tieneInformado = i.cantidad_informada !== null && i.cantidad_informada !== undefined;
            const diferencia = tieneInformado ? i.cantidad_informada - stockReal : null;
            return `
            <tr>
              <td>${escapeHtml(i.nombre)}</td>
              <td>${formatUnidad(i.unidad)}</td>
              <td>${i.stock_inicial}</td>
              <td>${i.entregas}</td>
              <td>${i.ventas}</td>
              <td>${i.mermas_total ?? '—'}</td>
              <td>${stockReal.toFixed(2)}</td>
              <td>${tieneInformado ? i.cantidad_informada : '—'}</td>
              <td>${diferencia !== null ? diferencia.toFixed(2) : '—'}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3>Control de Stock</h3>
      <p class="placeholder" style="margin-bottom:1rem">Stock Informado (conteo físico de Cocina) y Mermas por causa, lado a lado -- igual que en la planilla. Esto alimenta las columnas Mermas y Stock Informado de la tabla de arriba.</p>
      <div id="stock-form">
        <table>
          <thead><tr>
            <th>Insumo</th><th>Unidad</th><th>Stock Informado</th>
            <th>Producción</th><th>Defectuosos</th><th>Clientes</th><th>Cortesía</th><th>Reutilizar</th>
          </tr></thead>
          <tbody>
            ${items.filter(i => i.tramo === 'kg').map(i => `
              <tr data-stock-row-key="${i.ingrediente_key}">
                <td>${escapeHtml(i.nombre)}</td>
                <td>${formatUnidad(i.unidad)}</td>
                <td>${editable ? `<input class="field stock-informado-input" type="number" step="0.01" style="width:90px" value="${i.cantidad_informada ?? ''}">` : (i.cantidad_informada ?? '—')}</td>
                <td>${editable ? `<input class="field stock-produccion-input" type="number" step="0.01" style="width:80px" value="${i.mermas_produccion ?? ''}">` : (i.mermas_produccion ?? '—')}</td>
                <td>${editable ? `<input class="field stock-defectuosos-input" type="number" step="0.01" style="width:80px" value="${i.mermas_defectuosos ?? ''}">` : (i.mermas_defectuosos ?? '—')}</td>
                <td>${editable ? `<input class="field stock-clientes-input" type="number" step="0.01" style="width:80px" value="${i.mermas_clientes ?? ''}">` : (i.mermas_clientes ?? '—')}</td>
                <td>${editable ? `<input class="field stock-cortesia-input" type="number" step="0.01" style="width:80px" value="${i.mermas_cortesia ?? ''}">` : (i.mermas_cortesia ?? '—')}</td>
                <td>${editable ? `<input class="field stock-reutilizar-input" type="number" step="0.01" style="width:80px" value="${i.mermas_reutilizar ?? ''}">` : (i.mermas_reutilizar ?? '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
        <table style="margin-top:1.5rem">
          <thead><tr>
            <th>Insumo</th><th>Unidad</th><th>Stock Informado</th>
            <th>Producción</th><th>Defectuosos</th><th>Clientes</th><th>Cortesía</th>
          </tr></thead>
          <tbody>
            ${items.filter(i => i.tramo === 'unidades').map(i => `
              <tr data-stock-row-key="${i.ingrediente_key}">
                <td>${escapeHtml(i.nombre)}</td>
                <td>${formatUnidad(i.unidad)}</td>
                <td>${editable ? `<input class="field stock-informado-input" type="number" step="0.01" style="width:90px" value="${i.cantidad_informada ?? ''}">` : (i.cantidad_informada ?? '—')}</td>
                <td>${editable ? `<input class="field stock-produccion-input" type="number" step="0.01" style="width:80px" value="${i.mermas_produccion ?? ''}">` : (i.mermas_produccion ?? '—')}</td>
                <td>${editable ? `<input class="field stock-defectuosos-input" type="number" step="0.01" style="width:80px" value="${i.mermas_defectuosos ?? ''}">` : (i.mermas_defectuosos ?? '—')}</td>
                <td>${editable ? `<input class="field stock-clientes-input" type="number" step="0.01" style="width:80px" value="${i.mermas_clientes ?? ''}">` : (i.mermas_clientes ?? '—')}</td>
                <td>${editable ? `<input class="field stock-cortesia-input" type="number" step="0.01" style="width:80px" value="${i.mermas_cortesia ?? ''}">` : (i.mermas_cortesia ?? '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>Entregas a Cocina / Salida de Bodega</h3>
      <p class="placeholder" style="margin-bottom:1rem">Lo que Bodega le entrega a Cocina este día, insumo por insumo. Esto es lo que alimenta la columna Entregas de la tabla de arriba (junto con lo producido en Cocina, si aplica).</p>
      <div id="entregas-form">
        <table>
          <thead><tr><th>Insumo</th><th>Unidad</th><th>Cantidad</th></tr></thead>
          <tbody>
            ${items.map(i => `
              <tr data-entrega-row-key="${i.ingrediente_key}">
                <td>${escapeHtml(i.nombre)}</td>
                <td>${formatUnidad(i.unidad)}</td>
                <td>
                  ${editable
                    ? `<input class="field entrega-cantidad-input" data-key="${i.ingrediente_key}" type="number" step="0.01" style="width:90px" value="${i.entrega_bodega || ''}">`
                    : (i.entrega_bodega || '—')}
                </td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>Entregas de proteínas para producciones de cocina</h3>
      <p class="placeholder" style="margin-bottom:1rem">Lista fija -- son siempre los mismos traspasos de materia prima a producto elaborado. Solo se cargan las cantidades del día.</p>
      <div id="proteinas-form">
        <table>
          <thead><tr><th>Materia prima</th><th>Cantidad</th><th>Producto final</th><th>Cantidad producida</th><th>Mermas</th></tr></thead>
          <tbody>
            ${proteinas.map(p => `
              <tr data-receta-id="${p.receta_id}">
                <td>${escapeHtml(p.materia_prima_nombre)} <span class="placeholder">(${formatUnidad(p.materia_prima_unidad)})</span></td>
                <td>${editable ? `<input class="field prot-consumida-input" type="number" step="0.01" style="width:90px" value="${p.cantidad_consumida ?? ''}">` : (p.cantidad_consumida ?? '—')}</td>
                <td>${p.producto_final_nombre ? `${escapeHtml(p.producto_final_nombre)} <span class="placeholder">(${formatUnidad(p.producto_final_unidad || '')})</span>` : '—'}</td>
                <td>${editable && p.producto_final_nombre ? `<input class="field prot-producida-input" type="number" step="0.01" style="width:90px" value="${p.cantidad_producida ?? ''}">` : (p.cantidad_producida ?? '—')}</td>
                <td>${editable ? `<input class="field prot-mermas-input" type="number" step="0.01" style="width:90px" value="${p.mermas ?? ''}">` : (p.mermas ?? '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>Registro Producciones Pastelería</h3>
      <p class="placeholder" style="margin-bottom:1rem">Lista fija de productos de pastelería. Cuántas unidades se hicieron este día.</p>
      <div id="pasteleria-form">
        <table>
          <thead><tr><th>Producto</th><th>Unidad</th><th>Cantidad producida</th></tr></thead>
          <tbody>
            ${pasteleria.map(p => `
              <tr data-producto-key="${p.producto_key}">
                <td>${escapeHtml(p.producto_nombre)}</td>
                <td>${formatUnidad(p.unidad)}</td>
                <td>${editable ? `<input class="field past-cantidad-input" type="number" step="0.01" style="width:90px" value="${p.cantidad_producida ?? ''}">` : (p.cantidad_producida ?? '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>Registro de Chocolates</h3>
      <p class="placeholder" style="margin-bottom:1rem">Lista fija de chocolates/coberturas. Cantidad entregada por Bodega y cantidad utilizada ese día.</p>
      <div id="chocolates-form">
        <table>
          <thead><tr><th>Producto</th><th>Unidad</th><th>Cantidad Entregada</th><th>Cant. Utilizada</th></tr></thead>
          <tbody>
            ${chocolates.map(c => `
              <tr data-producto-key="${c.producto_key}">
                <td>${escapeHtml(c.producto_nombre)}</td>
                <td>${formatUnidad(c.unidad)}</td>
                <td>${editable ? `<input class="field choc-entregada-input" type="number" step="0.01" style="width:90px" value="${c.cantidad_entregada ?? ''}">` : (c.cantidad_entregada ?? '—')}</td>
                <td>${editable ? `<input class="field choc-utilizada-input" type="number" step="0.01" style="width:90px" value="${c.cantidad_utilizada ?? ''}">` : (c.cantidad_utilizada ?? '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>
    ${editable ? `
    <div class="card">
      <button type="button" id="mermas-guardar-todo" class="btn btn-primary">Guardar (${fecha})</button>
      <p id="guardar-error" class="error-msg"></p>
    </div>` : ''}`;

  state.mermasDirty = false;
  if (editable) {
    el.oninput = (e) => {
      if (e.target.matches('#stock-form input, #entregas-form input, #proteinas-form input, #pasteleria-form input, #chocolates-form input')) {
        state.mermasDirty = true;
      }
    };
  }

  document.getElementById('mermas-local').addEventListener('change', (e) => {
    if (!confirmarSalirMermas()) { e.target.value = localId; return; }
    state.mermasLocal = e.target.value;
    renderView();
  });

  document.getElementById('mermas-fecha').addEventListener('change', (e) => {
    if (!confirmarSalirMermas()) { e.target.value = fecha; return; }
    state.mermasFecha = e.target.value;
    renderView();
  });

  el.querySelectorAll('[data-dia-semana]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!confirmarSalirMermas()) return;
      state.mermasFecha = btn.dataset.diaSemana;
      renderView();
    });
  });

  document.getElementById('mermas-exportar').addEventListener('click', async () => {
    const errorEl = document.getElementById('export-error');
    errorEl.textContent = '';
    try {
      await apiDownload(`/mermas/exportar?local_id=${localId}&fecha=${fecha}`, `Inventario Cocina ${fecha}.xlsx`);
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('mermas-reporte-pdf').addEventListener('click', async () => {
    const errorEl = document.getElementById('export-error');
    errorEl.textContent = '';
    try {
      await apiDownload(`/mermas/reporte-ventas-pdf?local_id=${localId}&fecha=${fecha}`, `Reporte Ventas ${fecha}.pdf`);
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('mermas-reporte-pdf-ver').addEventListener('click', async () => {
    const errorEl = document.getElementById('export-error');
    errorEl.textContent = '';
    try {
      await apiViewBlob(`/mermas/reporte-ventas-pdf?local_id=${localId}&fecha=${fecha}`);
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  async function guardarControlStock() {
    const filas = Array.from(document.querySelectorAll('tr[data-stock-row-key]'));
    for (const fila of filas) {
      const key = fila.dataset.stockRowKey;
      const informadoVal = fila.querySelector('.stock-informado-input').value;
      const produccionVal = fila.querySelector('.stock-produccion-input').value;
      const defectuososVal = fila.querySelector('.stock-defectuosos-input').value;
      const clientesVal = fila.querySelector('.stock-clientes-input').value;
      const cortesiaVal = fila.querySelector('.stock-cortesia-input').value;
      const reutilizarVal = fila.querySelector('.stock-reutilizar-input')?.value ?? '';
      if ([informadoVal, produccionVal, defectuososVal, clientesVal, cortesiaVal, reutilizarVal].every(v => v === '')) continue;
      const original = items.find(i => i.ingrediente_key === key);
      await api('/mermas', {
        method: 'POST',
        body: JSON.stringify({
          local_id: localId,
          ingrediente_key: key,
          fecha,
          cantidad_informada: informadoVal !== '' ? parseFloat(informadoVal) : (original?.cantidad_informada ?? 0),
          mermas_produccion: produccionVal !== '' ? parseFloat(produccionVal) : (original?.mermas_produccion ?? null),
          mermas_defectuosos: defectuososVal !== '' ? parseFloat(defectuososVal) : (original?.mermas_defectuosos ?? null),
          mermas_clientes: clientesVal !== '' ? parseFloat(clientesVal) : (original?.mermas_clientes ?? null),
          mermas_cortesia: cortesiaVal !== '' ? parseFloat(cortesiaVal) : (original?.mermas_cortesia ?? null),
          mermas_reutilizar: reutilizarVal !== '' ? parseFloat(reutilizarVal) : (original?.mermas_reutilizar ?? null),
        }),
      });
    }
  }

  async function guardarEntregas() {
    const filas = Array.from(document.querySelectorAll('tr[data-entrega-row-key]'));
    for (const fila of filas) {
      const key = fila.dataset.entregaRowKey;
      const val = fila.querySelector('.entrega-cantidad-input').value;
      if (val === '') continue;
      await api('/mermas/entregas', {
        method: 'POST',
        body: JSON.stringify({ local_id: localId, ingrediente_key: key, fecha, cantidad: parseFloat(val) }),
      });
    }
  }

  async function guardarProteinas() {
    const filas = Array.from(document.querySelectorAll('tr[data-receta-id]'));
    for (const fila of filas) {
      const consumidaVal = fila.querySelector('.prot-consumida-input')?.value ?? '';
      const producidaVal = fila.querySelector('.prot-producida-input')?.value ?? '';
      const mermasVal = fila.querySelector('.prot-mermas-input')?.value ?? '';
      if (consumidaVal === '' && producidaVal === '' && mermasVal === '') continue;
      await api('/mermas/proteinas', {
        method: 'POST',
        body: JSON.stringify({
          local_id: localId, receta_id: fila.dataset.recetaId, fecha,
          cantidad_consumida: consumidaVal !== '' ? parseFloat(consumidaVal) : null,
          cantidad_producida: producidaVal !== '' ? parseFloat(producidaVal) : null,
          mermas: mermasVal !== '' ? parseFloat(mermasVal) : null,
        }),
      });
    }
  }

  async function guardarPasteleria() {
    const filas = Array.from(document.querySelectorAll('#pasteleria-form tr[data-producto-key]'));
    for (const fila of filas) {
      const val = fila.querySelector('.past-cantidad-input')?.value ?? '';
      if (val === '') continue;
      await api('/mermas/pasteleria', {
        method: 'POST',
        body: JSON.stringify({ local_id: localId, producto_key: fila.dataset.productoKey, fecha, cantidad_producida: parseFloat(val) }),
      });
    }
  }

  async function guardarChocolates() {
    const filas = Array.from(document.querySelectorAll('#chocolates-form tr[data-producto-key]'));
    for (const fila of filas) {
      const entregadaVal = fila.querySelector('.choc-entregada-input')?.value ?? '';
      const utilizadaVal = fila.querySelector('.choc-utilizada-input')?.value ?? '';
      if (entregadaVal === '' && utilizadaVal === '') continue;
      await api('/mermas/chocolates', {
        method: 'POST',
        body: JSON.stringify({
          local_id: localId, producto_key: fila.dataset.productoKey, fecha,
          cantidad_entregada: entregadaVal !== '' ? parseFloat(entregadaVal) : null,
          cantidad_utilizada: utilizadaVal !== '' ? parseFloat(utilizadaVal) : null,
        }),
      });
    }
  }

  if (editable) {
    document.getElementById('mermas-guardar-todo').addEventListener('click', async () => {
      const errorEl = document.getElementById('guardar-error');
      errorEl.textContent = '';
      try {
        await guardarControlStock();
        await guardarEntregas();
        await guardarProteinas();
        await guardarPasteleria();
        await guardarChocolates();
        state.mermasDirty = false;
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
    <div class="modal-box" style="width:520px">
      <h3>Detalle del pedido — ${nombreLocal}</h3>
      <p class="placeholder" style="margin-bottom:1rem">${pedido.fecha} · ${pedido.estado}</p>
      <table>
        <thead><tr><th>Insumo</th><th>Cantidad</th><th>Unidad</th></tr></thead>
        <tbody>
          ${(pedido.items || []).map(i => `
            <tr><td>${escapeHtml(i.ingrediente)}</td><td>${i.cantidad}</td><td>${formatUnidad(i.unidad)}</td></tr>
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
  const nombreLocal = (id) => escapeHtml((locales.find(l => l.id === id) || {}).nombre || id);

  el.innerHTML = `
    <h2>Pedidos</h2>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `
      <div class="card">
        <h3>Nuevo pedido</h3>
        <form id="pedido-form">
          <label class="field-label">Local</label>
          <select id="pedido-local" required class="field" style="margin-bottom:1rem;width:100%;max-width:280px">
            ${locales.map(l => `<option value="${l.id}">${escapeHtml(l.nombre)}</option>`).join('')}
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
                  ? p.acciones.map(a => a.tipo === 'odoo' ? escapeHtml(a.po_name) : `✉ ${escapeHtml(a.proveedor)}`).join(', ')
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
    btn.onclick = () => generarOC(btn.dataset.oc, btn);
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
        <input placeholder="Insumo" class="item-nombre field" style="flex:2" value="${escapeHtml(nombre)}">
        <input placeholder="Cantidad" type="number" step="0.01" class="item-cantidad field" value="${escapeHtml(String(cantidad))}">
        <input placeholder="Unidad (g/kg/un)" class="item-unidad field" value="${escapeHtml(unidad)}">`;
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
        conCompra.forEach(i => addRow(i.nombre, i.sugerido, formatUnidad(i.unidad), i.ingrediente_key));
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

async function renderFacturas(el, s) {
  const editable = puedeEditar(s);
  const [historial, locales] = await Promise.all([api('/facturas'), api('/locales')]);
  const nombreLocal = (id) => (locales.find(l => l.id === id) || {}).nombre || '—';
  const pendientes = state.facturasPendientes;

  el.innerHTML = `
    <h2>Facturas de Proveedor</h2>
    <p class="placeholder" style="margin-bottom:1.25rem">Al aceptar una factura, sus insumos reconocidos se registran como ingreso real a Bodega -- no se puede procesar la misma factura dos veces.</p>
    ${!editable ? '<div class="readonly-note">Modo solo lectura para tu rol.</div>' : ''}
    ${editable ? `<div class="card"><button type="button" id="btn-buscar-facturas" class="btn btn-primary">Buscar facturas nuevas</button></div>` : ''}

    ${pendientes === null ? '' : (!pendientes.length
      ? '<div class="card"><p class="placeholder">No hay facturas nuevas -- todo al día.</p></div>'
      : pendientes.map(f => `
        <div class="card" data-factura="${f.odoo_invoice_id}">
          <h3>${escapeHtml(f.odoo_invoice_name)} — ${escapeHtml(f.proveedor)}</h3>
          <p class="placeholder" style="margin-bottom:1rem">${f.fecha || '—'} · Total: ${f.total}</p>
          <label class="field-label">Local</label>
          <select class="field factura-local-sel" data-invoice="${f.odoo_invoice_id}" style="max-width:280px;margin-bottom:1rem">
            <option value="">-- selecciona un local --</option>
            ${locales.map(l => `<option value="${l.id}">${escapeHtml(l.nombre)}</option>`).join('')}
          </select>
          <table>
            <thead><tr><th>Insumo</th><th>Cantidad</th><th>Estado</th></tr></thead>
            <tbody>
              ${f.lineas.map(l => `
                <tr>
                  <td>${escapeHtml(l.nombre)}</td>
                  <td>${l.cantidad}</td>
                  <td>${l.reconocido ? '✓ En catálogo' : '⚠ No reconocido -- no se ingresará'}</td>
                </tr>`).join('')}
              ${!f.lineas.length ? '<tr><td colspan="3" class="placeholder">Sin líneas de producto.</td></tr>' : ''}
            </tbody>
          </table>
          ${editable ? `<button type="button" class="btn btn-primary" data-aceptar-factura="${f.odoo_invoice_id}" style="margin-top:1rem">Aceptar e ingresar a Bodega</button>` : ''}
        </div>`).join(''))}

    <div class="card">
      <h3>Historial</h3>
      <table>
        <thead><tr><th>Factura</th><th>Proveedor</th><th>Local</th><th>Procesada</th></tr></thead>
        <tbody>
          ${historial.map(h => `
            <tr>
              <td>${escapeHtml(h.odoo_invoice_name)}</td>
              <td>${escapeHtml(h.proveedor)}</td>
              <td>${h.local_id ? nombreLocal(h.local_id) : '—'}</td>
              <td>${(h.procesada_en || '').slice(0, 10)}</td>
            </tr>`).join('')}
          ${!historial.length ? '<tr><td colspan="4" class="placeholder">Todavía no se ha procesado ninguna factura.</td></tr>' : ''}
        </tbody>
      </table>
    </div>`;

  document.getElementById('btn-buscar-facturas')?.addEventListener('click', (e) => buscarFacturasNuevas(e.target));

  if (editable && pendientes) {
    el.querySelectorAll('button[data-aceptar-factura]').forEach(btn => {
      btn.onclick = async () => {
        const invoiceId = parseInt(btn.dataset.aceptarFactura, 10);
        const factura = pendientes.find(f => f.odoo_invoice_id === invoiceId);
        const localId = el.querySelector(`.factura-local-sel[data-invoice="${invoiceId}"]`).value;
        if (!localId) { alert('Selecciona un local antes de aceptar.'); return; }
        if (!confirm(`¿Aceptar ${factura.odoo_invoice_name}? Se registrará el ingreso a Bodega de los insumos reconocidos.`)) return;
        btn.disabled = true;
        btn.textContent = 'Aceptando…';
        try {
          await api('/facturas/aceptar', {
            method: 'POST',
            body: JSON.stringify({
              odoo_invoice_id: factura.odoo_invoice_id, odoo_invoice_name: factura.odoo_invoice_name,
              proveedor: factura.proveedor, local_id: localId,
              lineas: factura.lineas,
            }),
          });
          state.facturasPendientes = pendientes.filter(f => f.odoo_invoice_id !== invoiceId);
          renderView();
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
          btn.textContent = 'Aceptar e ingresar a Bodega';
        }
      };
    });
  }
}

function _textoContadorDte() {
  if (!state.dteLista) return '';
  const n = state.dteLista.length;
  return `(${n} pendiente${n === 1 ? '' : 's'})`;
}

function _actualizarContadorDte() {
  const el = document.getElementById('dte-contador-pendientes');
  if (el) el.textContent = _textoContadorDte();
}

async function renderFacturasDte(el, s) {
  const hoy = new Date().toISOString().slice(0, 10);
  const hace7dias = (() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toISOString().slice(0, 10); })();
  const desde = state.dteDesde || hace7dias;
  const hasta = state.dteHasta || hoy;
  state.dteDesde = desde;
  state.dteHasta = hasta;

  el.innerHTML = `
    <h2>Facturas Odoo <span id="dte-contador-pendientes" class="placeholder" style="font-size:1rem">${_textoContadorDte()}</span></h2>
    <p class="placeholder" style="margin-bottom:1.25rem">Documentos que Odoo ya recibió del SII pero todavía no tienen una factura borrador creada. Revisa los productos de cada línea y crea la factura -- nunca se crea un producto nuevo, solo se conecta con uno que ya existe.</p>
    <div class="item-row" style="max-width:520px;margin-bottom:1rem">
      <div style="flex:1">
        <label class="field-label">Desde</label>
        <input type="date" id="dte-desde" class="field" style="width:100%" value="${desde}">
      </div>
      <div style="flex:1">
        <label class="field-label">Hasta</label>
        <input type="date" id="dte-hasta" class="field" style="width:100%" value="${hasta}">
      </div>
      <div style="display:flex;align-items:flex-end">
        <button type="button" id="dte-buscar" class="btn btn-primary">Buscar</button>
      </div>
    </div>
    ${state.dteLista !== null ? `
      <div style="max-width:320px;margin-bottom:1rem">
        <label class="field-label">Buscar por N° de factura</label>
        <input type="text" id="dte-filtro-folio" class="field" style="width:100%" placeholder="Ej. 95817" value="${state.dteFiltroFolio || ''}">
      </div>` : ''}
    <div style="margin-bottom:1rem">
      <button type="button" class="btn" id="dte-proveedores-ocultos">Proveedores ocultos</button>
    </div>
    <p id="dte-error" class="error-msg"></p>
    <div id="dte-cola-panel"></div>
    <div id="dte-resultados">${renderDteResultados(state.dteLista, state.dteFiltroFolio)}</div>`;

  document.getElementById('dte-filtro-folio')?.addEventListener('input', (e) => {
    state.dteFiltroFolio = e.target.value;
    document.getElementById('dte-resultados').innerHTML = renderDteResultados(state.dteLista, state.dteFiltroFolio);
    bindDteResultadosBotones();
  });

  document.getElementById('dte-desde').addEventListener('change', (e) => { state.dteDesde = e.target.value; });
  document.getElementById('dte-hasta').addEventListener('change', (e) => { state.dteHasta = e.target.value; });

  document.getElementById('dte-proveedores-ocultos').addEventListener('click', () => showProveedoresOcultosModal());

  document.getElementById('dte-buscar').addEventListener('click', async () => {
    const errorEl = document.getElementById('dte-error');
    errorEl.textContent = '';
    try {
      state.dteLista = await api(`/facturas-dte?desde=${state.dteDesde}&hasta=${state.dteHasta}`);
      state.dteFiltroFolio = '';
      renderView();
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  bindDteResultadosBotones();

  await actualizarColaPanel();
  iniciarPollingCola();
}

function renderDteResultados(dtes, filtroFolio) {
  if (dtes === null || dtes === undefined) return '<div class="card"><p class="placeholder">Buscá para ver los documentos pendientes del rango de fechas.</p></div>';
  if (!dtes.length) return '<div class="card"><p class="placeholder">No hay documentos pendientes en ese rango -- todo al día.</p></div>';
  const filtrados = filtroFolio ? dtes.filter(d => d.folio.toLowerCase().includes(filtroFolio.trim().toLowerCase())) : dtes;
  if (!filtrados.length) return '<div class="card"><p class="placeholder">Ningún folio coincide con la búsqueda.</p></div>';
  return Object.entries(filtrados.reduce((acc, d) => { (acc[d.proveedor_nombre] ||= []).push(d); return acc; }, {})).map(([proveedor, lista]) => `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <h3>${escapeHtml(proveedor)}</h3>
          <button type="button" class="btn" data-ocultar-proveedor="${encodeURIComponent(lista[0].proveedor_rut)}" data-ocultar-proveedor-nombre="${encodeURIComponent(proveedor)}">Ocultar proveedor</button>
        </div>
        <table>
          <thead><tr><th>Folio</th><th>Fecha</th><th>Monto</th><th></th></tr></thead>
          <tbody>
            ${lista.map(d => `
              <tr>
                <td>${escapeHtml(d.folio)}</td>
                <td>${d.fecha || '—'}</td>
                <td>$${Math.round(d.monto_total || 0).toLocaleString('es-CL')}</td>
                <td>
                  <button type="button" class="btn" data-revisar-dte="${d.id}">Revisar</button>
                  <button type="button" class="btn" data-marcar-manual-dte="${d.id}" title="Ya se ingresó esta factura a mano directo en Odoo -- la saca de esta lista sin tocar nada en Odoo">Ingresada Manualmente</button>
                </td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`).join('');
}

function bindDteResultadosBotones() {
  document.querySelectorAll('[data-revisar-dte]').forEach(btn => {
    btn.addEventListener('click', () => showDteModal(parseInt(btn.dataset.revisarDte, 10)));
  });
  document.querySelectorAll('[data-ocultar-proveedor]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const proveedorRut = decodeURIComponent(btn.dataset.ocultarProveedor);
      const proveedorNombre = decodeURIComponent(btn.dataset.ocultarProveedorNombre);
      if (!confirm(`¿Ocultar todas las facturas pendientes de "${proveedorNombre}"? Podés volver a mostrarlas desde "Proveedores ocultos".`)) return;
      const errorEl = document.getElementById('dte-error');
      errorEl.textContent = '';
      try {
        await api('/facturas-dte/proveedores/ocultar', {
          method: 'POST',
          body: JSON.stringify({ proveedor_rut: proveedorRut, proveedor_nombre: proveedorNombre }),
        });
        state.dteLista = state.dteLista.filter(d => d.proveedor_rut !== proveedorRut);
        document.getElementById('dte-resultados').innerHTML = renderDteResultados(state.dteLista, state.dteFiltroFolio);
        bindDteResultadosBotones();
        _actualizarContadorDte();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  });
  document.querySelectorAll('[data-marcar-manual-dte]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const dteId = parseInt(btn.dataset.marcarManualDte, 10);
      if (!confirm('¿Ya ingresaste esta factura a mano directo en Odoo? Va a salir de esta lista -- no se toca nada en Odoo.')) return;
      const errorEl = document.getElementById('dte-error');
      errorEl.textContent = '';
      try {
        await api(`/facturas-dte/${dteId}/marcar-manual`, { method: 'POST' });
        state.dteLista = state.dteLista.filter(d => d.id !== dteId);
        document.getElementById('dte-resultados').innerHTML = renderDteResultados(state.dteLista, state.dteFiltroFolio);
        bindDteResultadosBotones();
        _actualizarContadorDte();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  });
}

async function showProveedoresOcultosModal() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:560px"><p class="placeholder">Cargando…</p></div>';
  document.body.appendChild(overlay);

  try {
    const ocultos = await api('/facturas-dte/proveedores/ocultos');
    overlay.querySelector('.modal-box').innerHTML = `
      <h3>Proveedores ocultos</h3>
      <p class="placeholder" style="margin-bottom:1rem">Sus facturas pendientes no aparecen en la lista de Facturas Odoo. No se toca nada en Odoo -- podés volver a mostrarlos cuando quieras.</p>
      ${ocultos.length ? `
        <table>
          <thead><tr><th>Proveedor</th><th></th></tr></thead>
          <tbody>
            ${ocultos.map(p => `
              <tr>
                <td>${escapeHtml(p.proveedor_nombre)}</td>
                <td><button type="button" class="btn" data-mostrar-proveedor="${encodeURIComponent(p.proveedor_rut)}">Mostrar</button></td>
              </tr>`).join('')}
          </tbody>
        </table>` : '<p class="placeholder">No hay proveedores ocultos.</p>'}
      <div style="margin-top:1.25rem">
        <button type="button" class="btn" id="dte-ocultos-cerrar">Cerrar</button>
      </div>`;
    overlay.querySelector('#dte-ocultos-cerrar').onclick = () => overlay.remove();
    overlay.querySelectorAll('[data-mostrar-proveedor]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const proveedorRut = decodeURIComponent(btn.dataset.mostrarProveedor);
        try {
          await api(`/facturas-dte/proveedores/ocultos/${encodeURIComponent(proveedorRut)}`, { method: 'DELETE' });
          overlay.remove();
          if (state.dteLista !== null) {
            state.dteLista = await api(`/facturas-dte?desde=${state.dteDesde}&hasta=${state.dteHasta}`);
            renderView();
          }
        } catch (err) {
          alert(err.message);
        }
      });
    });
  } catch (err) {
    overlay.querySelector('.modal-box').innerHTML = `<p class="error-msg">${err.message}</p><button type="button" class="btn" id="dte-ocultos-cerrar-error">Cerrar</button>`;
    overlay.querySelector('#dte-ocultos-cerrar-error').onclick = () => overlay.remove();
  }
}

// Impuestos de compra que se usan siempre (pedido explícito del usuario --
// "por lo general usamos los mismos de siempre") -- se muestran como chips
// de un clic directo en la fila de cada línea, sin tener que abrir ni
// scrollear nada. "nombre" es el real de Odoo (account.tax, lo que
// realmente se guarda); "corto" es solo para que el chip ocupe poco
// espacio horizontal -- con 10+ líneas por factura, etiquetas largas
// obligaban a scrollear mucho verticalmente.
const IMPUESTOS_RAPIDOS = [
  { nombre: 'IVA 19% Compra', corto: 'IVA 19%' },
  { nombre: 'Vinos (Compras)', corto: 'Vinos' },
  { nombre: 'Licores 31.5% (Compras)', corto: 'Licores 31,5%' },
  { nombre: 'Beb. Analc. 10% (Compras)', corto: 'Analc. 10%' },
  { nombre: 'Beb. Analc 18% (Compras)', corto: 'Analc. 18%' },
  { nombre: 'Impuesto a la Carne 5%', corto: 'Carne 5%' },
  { nombre: 'Impuesto a la harina 12%', corto: 'Harina 12%' },
];
const IMPUESTOS_RAPIDOS_NOMBRES = IMPUESTOS_RAPIDOS.map(i => i.nombre);

const ETIQUETA_ESTADO_COLA = { pendiente: 'En cola…', procesando: 'Creando…', completado: '✓ Creada', error: '✗ Error' };

async function actualizarColaPanel() {
  const panel = document.getElementById('dte-cola-panel');
  if (!panel) return;
  try {
    state.dteCola = await api('/facturas-dte/cola/estado');
  } catch (err) {
    return; // no interrumpir el resto de la pantalla si falla el polling
  }
  const recientes = state.dteCola.slice(0, 8);
  if (!recientes.length) { panel.innerHTML = ''; return; }
  const activos = state.dteCola.filter(c => c.estado === 'pendiente' || c.estado === 'procesando').length;
  panel.innerHTML = `
    <div class="card" style="margin-bottom:1rem">
      <div class="item-row" style="justify-content:space-between;align-items:center;margin-bottom:.5rem">
        <h3 style="margin:0">Cola de creación${activos ? ` — ${activos} en curso` : ''}</h3>
        <button type="button" class="btn" id="dte-cola-limpiar-todas" title="Solo vacía esta lista -- no afecta las facturas en Odoo">Limpiar todas</button>
      </div>
      <table>
        <thead><tr><th>Proveedor</th><th>Folio</th><th>Estado</th><th></th></tr></thead>
        <tbody>
          ${recientes.map(c => `
            <tr>
              <td>${escapeHtml(c.proveedor_nombre)}</td>
              <td>${escapeHtml(c.folio)}</td>
              <td>${ETIQUETA_ESTADO_COLA[c.estado] || c.estado}${c.estado === 'completado' ? ` — ${escapeHtml(c.invoice_name)}` : ''}${c.estado === 'error' ? ` — ${escapeHtml(c.error_mensaje)}` : ''}</td>
              <td>
                ${c.estado === 'completado' ? `<button type="button" class="btn" data-comparar-dte="${c.dte_id}">Comparar</button> ` : ''}
                ${c.estado === 'error' && (c.error_mensaje || '').includes('Ya existe una factura en Odoo')
                  ? `<button type="button" class="btn btn-primary" data-vincular-cola="${c.id}" data-vincular-dte="${c.dte_id}" title="Busca la factura que ya existe en Odoo para este folio+proveedor y la vincula -- si corresponde, tambien la agrega a Planilla de Compras">Vincular factura existente</button> `
                  : ''}
                <button type="button" class="btn" data-eliminar-cola="${c.id}" title="Solo quita esta fila de la lista -- no afecta la factura en Odoo">Limpiar</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  panel.querySelectorAll('[data-eliminar-cola]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/facturas-dte/cola/${btn.dataset.eliminarCola}`, { method: 'DELETE' });
        actualizarColaPanel();
      } catch (err) {
        alert(err.message);
      }
    });
  });

  panel.querySelectorAll('[data-comparar-dte]').forEach(btn => {
    btn.addEventListener('click', () => showCompararModal(parseInt(btn.dataset.compararDte, 10)));
  });

  panel.querySelectorAll('[data-vincular-cola]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const dteId = parseInt(btn.dataset.vincularDte, 10);
      if (!confirm('¿Vincular la factura que ya existe en Odoo para este folio? Si corresponde, también se agrega a Planilla de Compras.')) return;
      btn.disabled = true;
      try {
        await api(`/facturas-dte/${dteId}/marcar-manual`, { method: 'POST' });
        await api(`/facturas-dte/cola/${btn.dataset.vincularCola}`, { method: 'DELETE' });
        if (state.dteLista) {
          state.dteLista = state.dteLista.filter(d => d.id !== dteId);
          const resultadosEl = document.getElementById('dte-resultados');
          if (resultadosEl) {
            resultadosEl.innerHTML = renderDteResultados(state.dteLista, state.dteFiltroFolio);
            bindDteResultadosBotones();
          }
          _actualizarContadorDte();
        }
        actualizarColaPanel();
      } catch (err) {
        btn.disabled = false;
        alert(err.message);
      }
    });
  });

  document.getElementById('dte-cola-limpiar-todas').addEventListener('click', async () => {
    if (activos && !confirm(`Todavía hay ${activos} factura(s) en curso -- limpiar la lista no las cancela, solo deja de mostrarlas acá. ¿Limpiar de todas formas?`)) return;
    try {
      await api('/facturas-dte/cola', { method: 'DELETE' });
      actualizarColaPanel();
    } catch (err) {
      alert(err.message);
    }
  });
}

function iniciarPollingCola() {
  if (state.dteColaTimer) clearTimeout(state.dteColaTimer);
  state.dteColaTimer = setTimeout(async () => {
    if (state.section !== 'facturas-dte') return;
    await actualizarColaPanel();
    iniciarPollingCola();
  }, 3000);
}

async function showDteModal(dteId) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:1300px;max-width:96vw"><p class="placeholder">Cargando…</p></div>';
  document.body.appendChild(overlay);

  async function recargar() {
    const [dte, todosImpuestos] = await Promise.all([
      api(`/facturas-dte/${dteId}`),
      api('/facturas-dte/impuestos/buscar'),
    ]);
    // "sugerido" = todavia no se escribio en Odoo, solo es una propuesta de
    // nuestro mapeo -- hay que confirmarla (boton "Confirmar / cambiar")
    // antes de que cuente como matcheada de verdad.
    const todasMatcheadas = dte.lineas.every(l => l.product_id && !l.sugerido);
    overlay.querySelector('.modal-box').innerHTML = `
      <h3>${escapeHtml(dte.proveedor_nombre)} — Folio ${escapeHtml(dte.folio)}</h3>
      <p class="placeholder" style="margin-bottom:1rem">${dte.fecha || '—'}</p>
      <div style="overflow-x:auto">
      <table>
        <thead><tr><th>Detalle factura</th><th>Cantidad</th><th>Cant. real</th><th>Precio artículo</th><th>Desc. %</th><th>Precio artículo c/desc.</th><th>Impuestos</th><th>Producto en Odoo</th><th></th></tr></thead>
        <tbody>
          ${dte.lineas.map(l => `
            <tr data-linea="${l.id}">
              <td>${escapeHtml(l.item_name)}${l.es_manual ? ' <span class="placeholder" title="Agregada a mano -- no vino como línea propia en el DTE">(manual)</span>' : ''}</td>
              <td>${l.qty}</td>
              <td>${l.product_id && l.codigo_tipo ? `
                <input type="number" class="field dte-factor-inline" data-linea-factor-inline="${l.id}" min="0.0001" step="any" style="width:70px" value="${l.factor_conversion || 1}" title="¿Cuántas unidades reales vienen en cada una declarada? (ej. si '1 azúcar' son en realidad 10 kg, coloca 10). Se guarda para este proveedor + este código, se aplica solo en toda factura futura igual.">
                <span class="placeholder" data-factor-estado="${l.id}" style="font-size:.7rem"></span>`
                : '<span class="placeholder">—</span>'}</td>
              <td>${_fmtMonto(l.qty * l.item_price)}</td>
              <td>${l.product_id ? `
                <input type="number" class="field dte-descuento-inline" data-linea-descuento-inline="${l.id}" min="0" max="100" step="any" style="width:70px" value="${l.descuento_pct || 0}">
                <span class="placeholder" data-descuento-estado="${l.id}" style="font-size:.75rem">${l.descuento_sugerido ? 'según la última vez -- confirma' : ''}</span>`
                : '<span class="placeholder">—</span>'}</td>
              <td data-precio-desc="${l.id}">${_fmtMonto(l.qty * l.item_price * (1 - (l.descuento_pct || 0) / 100))}</td>
              <td style="max-width:300px">${l.product_id ? `
                <div data-impuestos-chips="${l.id}" data-seleccionados="${encodeURIComponent(JSON.stringify(l.impuesto_nombres || []))}" style="display:flex;flex-wrap:wrap;gap:.2rem">
                  ${IMPUESTOS_RAPIDOS.map(({ nombre, corto }) => {
                    const activo = (l.impuesto_nombres || []).includes(nombre);
                    return `<button type="button" class="btn ${activo ? 'btn-primary' : ''}" style="font-size:.72rem;padding:.1rem .35rem;white-space:nowrap" title="${nombre}" data-impuesto-chip="${l.id}" data-impuesto-nombre="${nombre.replace(/"/g, '&quot;')}">${corto}</button>`;
                  }).join('')}
                  ${(l.impuesto_nombres || []).filter(n => !IMPUESTOS_RAPIDOS_NOMBRES.includes(n)).map(nombre => `<button type="button" class="btn btn-primary" style="font-size:.72rem;padding:.1rem .35rem;white-space:nowrap" data-impuesto-chip="${l.id}" data-impuesto-nombre="${escapeHtml(nombre)}">${escapeHtml(nombre)}</button>`).join('')}
                </div>
                <p data-impuesto-estado="${l.id}" style="margin-top:.1rem;font-size:.7rem"></p>`
                : '<span class="placeholder">—</span>'}</td>
              <td>${l.product_id
                ? `${escapeHtml(l.product_name)}${l.sugerido ? ' <span class="placeholder" title="Sugerido automáticamente por el mapeo guardado -- confirma con un clic">(sugerido)</span>' : ' ✓'}`
                : '<span class="placeholder">Sin producto</span>'}</td>
              <td>${l.es_manual
                ? `<button type="button" class="btn" data-quitar-manual="${l.id}">Quitar</button>`
                : !l.product_id
                  ? `<button type="button" class="btn" data-buscar-linea="${l.id}">Buscar producto</button>`
                  : l.sugerido
                    ? `<button type="button" class="btn btn-primary" data-confirmar-sugerido="${l.id}">Confirmar</button> <button type="button" class="btn" data-buscar-linea="${l.id}">Cambiar</button>`
                    : `<button type="button" class="btn" data-buscar-linea="${l.id}">Cambiar</button>`}
                ${l.product_id ? ` <button type="button" class="btn" data-otros-impuestos-linea="${l.id}" title="Buscar un impuesto que no esté entre los de uso frecuente">Otros impuestos</button>` : ''}</td>
            </tr>
            <tr data-buscador="${l.id}" style="display:none"><td colspan="9">
              <div class="item-row">
                <input type="text" class="field dte-buscar-input" data-linea-buscar="${l.id}" placeholder="Buscar por nombre o código..." style="flex:1">
                <button type="button" class="btn" data-ejecutar-busqueda="${l.id}">Buscar</button>
              </div>
              <div data-resultados="${l.id}" style="margin-top:.5rem"></div>
            </td></tr>
            ${l.product_id ? `
            <tr data-impuestos-fila="${l.id}" style="display:none"><td colspan="9">
              <p class="placeholder" style="margin-bottom:.5rem">Buscar un impuesto de <strong>${escapeHtml(l.product_name)}</strong> que no esté entre los de uso frecuente (máx. 3 en total, aplica y guarda al elegirlo).</p>
              <div class="item-row">
                <input type="text" class="field dte-impuesto-buscar-otro" data-linea-buscar-impuesto="${l.id}" placeholder="Buscar otro impuesto..." style="flex:1;max-width:260px">
                <button type="button" class="btn" data-impuesto-buscar-otro-btn="${l.id}">Buscar</button>
              </div>
              <div data-impuesto-otro-resultados="${l.id}" style="margin-top:.3rem"></div>
            </td></tr>` : ''}`).join('')}
        </tbody>
      </table>
      </div>
      <div style="margin-top:.75rem">
        <button type="button" class="btn" id="dte-manual-toggle">+ Agregar línea manual</button>
        <div id="dte-manual-form" style="display:none;margin-top:.5rem">
          <p class="placeholder" style="margin-bottom:.5rem">Para un producto que el proveedor declaró en el Neto/Total pero no vino como línea propia en esta factura (ej. flete, envase).</p>
          <div class="item-row">
            <input type="text" class="field" id="dte-manual-buscar-input" placeholder="Buscar producto por nombre o código..." style="flex:1">
            <button type="button" class="btn" id="dte-manual-buscar-btn">Buscar</button>
          </div>
          <div id="dte-manual-resultados" style="margin-top:.5rem"></div>
          <div id="dte-manual-detalle" style="display:none;margin-top:.5rem">
            <p class="placeholder">Producto: <strong id="dte-manual-producto-nombre"></strong></p>
            <div class="item-row">
              <input type="number" class="field" id="dte-manual-qty" placeholder="Cantidad" min="0.0001" step="any" style="max-width:140px">
              <input type="number" class="field" id="dte-manual-precio" placeholder="Precio unitario" min="0" step="any" style="max-width:160px">
              <button type="button" class="btn btn-primary" id="dte-manual-guardar">Agregar línea</button>
            </div>
          </div>
          <p class="error-msg" id="dte-manual-error"></p>
        </div>
      </div>
      <div id="dte-resumen" style="margin-top:1rem"><p class="placeholder">Calculando…</p></div>
      <p id="dte-modal-error" class="error-msg"></p>
      <div style="margin-top:1.25rem;display:flex;gap:.5rem">
        <button type="button" class="btn" id="dte-modal-cerrar">Cerrar</button>
        <button type="button" class="btn btn-primary" id="dte-modal-crear" ${todasMatcheadas ? '' : 'disabled'}>Crear Factura en Odoo</button>
      </div>`;

    overlay.querySelector('#dte-modal-cerrar').onclick = () => overlay.remove();

    let manualProductoElegido = null;
    overlay.querySelector('#dte-manual-toggle').onclick = () => {
      const form = overlay.querySelector('#dte-manual-form');
      form.style.display = form.style.display === 'none' ? 'block' : 'none';
    };
    overlay.querySelector('#dte-manual-buscar-btn').onclick = async () => {
      const q = overlay.querySelector('#dte-manual-buscar-input').value.trim();
      const resultadosEl = overlay.querySelector('#dte-manual-resultados');
      if (!q) return;
      resultadosEl.innerHTML = '<span class="placeholder">Buscando…</span>';
      try {
        const productos = await api(`/facturas-dte/productos/buscar?q=${encodeURIComponent(q)}`);
        resultadosEl.innerHTML = productos.length
          ? productos.map(p => `<button type="button" class="btn" style="margin:.2rem" data-elegir-manual="${p.id}" data-nombre="${escapeHtml(p.name)}">${escapeHtml(p.name)}${p.default_code ? ' (' + escapeHtml(p.default_code) + ')' : ''}</button>`).join('')
          : '<span class="placeholder">Sin resultados.</span>';
        resultadosEl.querySelectorAll('[data-elegir-manual]').forEach(pbtn => {
          pbtn.onclick = () => {
            manualProductoElegido = { id: parseInt(pbtn.dataset.elegirManual, 10), nombre: pbtn.dataset.nombre };
            overlay.querySelector('#dte-manual-producto-nombre').textContent = manualProductoElegido.nombre;
            overlay.querySelector('#dte-manual-detalle').style.display = 'block';
          };
        });
      } catch (err) {
        resultadosEl.innerHTML = `<span class="error-msg">${err.message}</span>`;
      }
    };
    overlay.querySelector('#dte-manual-guardar').onclick = async () => {
      const errorEl = overlay.querySelector('#dte-manual-error');
      errorEl.textContent = '';
      if (!manualProductoElegido) { errorEl.textContent = 'Elegí un producto primero.'; return; }
      const qty = parseFloat(overlay.querySelector('#dte-manual-qty').value);
      const precio = parseFloat(overlay.querySelector('#dte-manual-precio').value);
      if (isNaN(qty) || qty <= 0) { errorEl.textContent = 'Ingresa una cantidad mayor que 0.'; return; }
      if (isNaN(precio) || precio < 0) { errorEl.textContent = 'Ingresa un precio unitario válido.'; return; }
      try {
        await api(`/facturas-dte/${dteId}/lineas-manuales`, {
          method: 'POST',
          body: JSON.stringify({
            odoo_product_id: manualProductoElegido.id, odoo_product_name: manualProductoElegido.nombre,
            qty, precio_unitario: precio, descuento_pct: 0, proveedor_rut: dte.proveedor_rut,
          }),
        });
        recargar();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    };

    overlay.querySelectorAll('[data-quitar-manual]').forEach(btn => {
      btn.onclick = async () => {
        const errorEl = overlay.querySelector('#dte-modal-error');
        errorEl.textContent = '';
        if (!confirm('¿Quitar esta línea agregada a mano?')) return;
        try {
          await api(`/facturas-dte/lineas-manuales/${Math.abs(parseInt(btn.dataset.quitarManual, 10))}`, { method: 'DELETE' });
          recargar();
        } catch (err) {
          errorEl.textContent = err.message;
        }
      };
    });

    async function cargarResumen() {
      const resumenEl = overlay.querySelector('#dte-resumen');
      try {
        const r = await api(`/facturas-dte/${dteId}/simular`);
        const diff = (a, b) => Math.abs(a - b) > 9;
        // r.impuestos_dte = TODOS los impuestos que declara el DTE (Total -
        // Neto), no solo el IVA -- si hay mas de un impuesto distinto (ej.
        // IVA + ILA) no hay como saber del lado del DTE cuanto es de cada
        // uno, se muestra "—" en esa fila.
        const unSoloImpuesto = r.impuestos.length === 1;
        resumenEl.innerHTML = `
          <table>
            <thead><tr><th></th><th>Neto</th>${r.impuestos.map(i => `<th>${escapeHtml(i.nombre)}</th>`).join('')}<th>Total</th></tr></thead>
            <tbody>
              <tr>
                <td>Calculado (con lo confirmado hoy)</td>
                <td>${_fmtMonto(r.neto)}</td>
                ${r.impuestos.map(i => `<td>${_fmtMonto(i.monto)}</td>`).join('')}
                <td>${_fmtMonto(r.total)}</td>
              </tr>
              <tr>
                <td>Declarado en el DTE</td>
                <td class="${diff(r.neto, r.neto_dte) ? 'error-msg' : ''}">${_fmtMonto(r.neto_dte)}</td>
                ${r.impuestos.map(i => unSoloImpuesto
                  ? `<td class="${diff(i.monto, r.impuestos_dte) ? 'error-msg' : ''}">${_fmtMonto(r.impuestos_dte)}</td>`
                  : `<td><span class="placeholder">—</span></td>`).join('')}
                <td class="${diff(r.total, r.total_dte) ? 'error-msg' : ''}">${_fmtMonto(r.total_dte)}</td>
              </tr>
            </tbody>
          </table>
          ${!unSoloImpuesto && r.impuestos.length ? `<p class="placeholder" style="margin-top:.4rem">El DTE declara ${_fmtMonto(r.impuestos_dte)} de impuestos en total, sin desglose por tipo -- no se puede comparar cada uno por separado.</p>` : ''}
          ${r.lineas_sin_producto ? `<p class="placeholder" style="margin-top:.4rem">${r.lineas_sin_producto} línea(s) sin producto asignado no se incluyen en este cálculo.</p>` : ''}`;
      } catch (err) {
        resumenEl.innerHTML = `<p class="error-msg">${err.message}</p>`;
      }
    }
    cargarResumen();

    overlay.querySelectorAll('.dte-descuento-inline').forEach(input => {
      const lineaId = input.dataset.lineaDescuentoInline;
      const linea = dte.lineas.find(x => String(x.id) === String(lineaId));
      const precioCell = overlay.querySelector(`[data-precio-desc="${lineaId}"]`);
      const estadoEl = overlay.querySelector(`[data-descuento-estado="${lineaId}"]`);

      input.addEventListener('input', () => {
        const valor = parseFloat(input.value);
        const pct = isNaN(valor) ? 0 : valor;
        precioCell.textContent = _fmtMonto(linea.qty * linea.item_price * (1 - pct / 100));
      });

      input.addEventListener('change', async () => {
        const valor = parseFloat(input.value);
        if (isNaN(valor) || valor < 0 || valor > 100) {
          estadoEl.textContent = '0-100';
          estadoEl.className = 'error-msg';
          return;
        }
        if (valor === (linea.descuento_pct || 0)) return;  // sin cambios, no guardar de nuevo
        estadoEl.textContent = 'Guardando…';
        estadoEl.className = 'placeholder';
        const endpoint = linea.es_manual
          ? `/facturas-dte/lineas-manuales/${Math.abs(linea.id)}/descuento`
          : `/facturas-dte/lineas/${lineaId}/descuento`;
        const cuerpo = linea.es_manual
          ? { descuento_pct: valor }
          : { descuento_pct: valor, proveedor_rut: dte.proveedor_rut, odoo_product_id: linea.product_id };
        try {
          await api(endpoint, { method: 'PUT', body: JSON.stringify(cuerpo) });
          linea.descuento_pct = valor;
          estadoEl.textContent = '✓ guardado';
          estadoEl.className = 'placeholder';
          setTimeout(() => { if (estadoEl.textContent === '✓ guardado') estadoEl.textContent = ''; }, 1500);
          cargarResumen();
        } catch (err) {
          estadoEl.textContent = err.message;
          estadoEl.className = 'error-msg';
        }
      });
    });

    overlay.querySelectorAll('[data-buscar-linea]').forEach(btn => {
      btn.onclick = () => {
        const fila = overlay.querySelector(`tr[data-buscador="${btn.dataset.buscarLinea}"]`);
        fila.style.display = fila.style.display === 'none' ? 'table-row' : 'none';
      };
    });

    overlay.querySelectorAll('.dte-factor-inline').forEach(input => {
      const lineaId = input.dataset.lineaFactorInline;
      const linea = dte.lineas.find(x => String(x.id) === String(lineaId));
      const estadoEl = overlay.querySelector(`[data-factor-estado="${lineaId}"]`);

      input.addEventListener('change', async () => {
        const factor = parseFloat(input.value);
        if (!factor || factor <= 0) {
          estadoEl.textContent = 'Debe ser mayor que 0.';
          estadoEl.className = 'error-msg';
          return;
        }
        if (factor === (linea.factor_conversion || 1)) return;  // sin cambios, no guardar de nuevo
        estadoEl.textContent = 'Guardando…';
        estadoEl.className = 'placeholder';
        try {
          await api('/facturas-dte/mapeo/factor', {
            method: 'PUT',
            body: JSON.stringify({
              proveedor_rut: dte.proveedor_rut, codigo_tipo: linea.codigo_tipo, codigo_valor: linea.codigo_valor,
              factor_conversion: factor,
            }),
          });
          linea.factor_conversion = factor;
          estadoEl.textContent = '✓ guardado';
          estadoEl.className = 'placeholder';
          setTimeout(() => { if (estadoEl.textContent === '✓ guardado') estadoEl.textContent = ''; }, 1500);
        } catch (err) {
          estadoEl.textContent = err.message;
          estadoEl.className = 'error-msg';
        }
      });
    });

    function renderImpuestoChips(lineaId) {
      const cont = overlay.querySelector(`[data-impuestos-chips="${lineaId}"]`);
      cont.querySelectorAll('[data-impuesto-chip]').forEach(chip => {
        chip.onclick = () => toggleImpuestoLinea(lineaId, chip.dataset.impuestoNombre);
      });
    }

    async function toggleImpuestoLinea(lineaId, nombre) {
      const linea = dte.lineas.find(x => String(x.id) === String(lineaId));
      const cont = overlay.querySelector(`[data-impuestos-chips="${lineaId}"]`);
      const estadoEl = overlay.querySelector(`[data-impuesto-estado="${lineaId}"]`);
      const seleccionados = JSON.parse(decodeURIComponent(cont.dataset.seleccionados || '%5B%5D'));
      let nuevos;
      if (seleccionados.includes(nombre)) {
        nuevos = seleccionados.filter(n => n !== nombre);
      } else {
        if (seleccionados.length >= 3) {
          estadoEl.textContent = 'Máximo 3 impuestos por producto.';
          estadoEl.className = 'error-msg';
          return;
        }
        nuevos = [...seleccionados, nombre];
      }
      estadoEl.textContent = 'Guardando…';
      estadoEl.className = 'placeholder';
      try {
        await api(`/facturas-dte/productos/${linea.product_id}/impuestos`, {
          method: 'PUT',
          body: JSON.stringify({ odoo_product_name: linea.product_name, impuesto_nombres: nuevos }),
        });
        linea.impuesto_nombres = nuevos;
        cont.dataset.seleccionados = encodeURIComponent(JSON.stringify(nuevos));
        const extras = nuevos.filter(n => !IMPUESTOS_RAPIDOS_NOMBRES.includes(n));
        const rapidosHtml = IMPUESTOS_RAPIDOS.map(({ nombre, corto }) => {
          const activo = nuevos.includes(nombre);
          return `<button type="button" class="btn ${activo ? 'btn-primary' : ''}" style="font-size:.72rem;padding:.1rem .35rem;white-space:nowrap" title="${nombre}" data-impuesto-chip="${lineaId}" data-impuesto-nombre="${nombre.replace(/"/g, '&quot;')}">${corto}</button>`;
        }).join('');
        const extrasHtml = extras.map(n => `<button type="button" class="btn btn-primary" style="font-size:.72rem;padding:.1rem .35rem;white-space:nowrap" data-impuesto-chip="${lineaId}" data-impuesto-nombre="${escapeHtml(n)}">${escapeHtml(n)}</button>`).join('');
        cont.innerHTML = rapidosHtml + extrasHtml;
        renderImpuestoChips(lineaId);
        estadoEl.textContent = '';
        cargarResumen();
      } catch (err) {
        estadoEl.textContent = err.message;
        estadoEl.className = 'error-msg';
      }
    }

    overlay.querySelectorAll('[data-impuestos-chips]').forEach(cont => {
      renderImpuestoChips(cont.dataset.impuestosChips);
    });

    overlay.querySelectorAll('[data-otros-impuestos-linea]').forEach(btn => {
      btn.onclick = () => {
        const lineaId = btn.dataset.otrosImpuestosLinea;
        const fila = overlay.querySelector(`tr[data-impuestos-fila="${lineaId}"]`);
        const visible = fila.style.display !== 'none';
        overlay.querySelectorAll('[data-impuestos-fila]').forEach(f => { f.style.display = 'none'; });
        if (visible) return;
        fila.style.display = 'table-row';
        overlay.querySelector(`[data-impuesto-buscar-otro-btn="${lineaId}"]`).onclick = () => {
          const q = overlay.querySelector(`.dte-impuesto-buscar-otro[data-linea-buscar-impuesto="${lineaId}"]`).value.trim().toLowerCase();
          const resEl = overlay.querySelector(`[data-impuesto-otro-resultados="${lineaId}"]`);
          if (!q) return;
          const encontrados = todosImpuestos.filter(t => t.name.toLowerCase().includes(q));
          resEl.innerHTML = encontrados.length
            ? encontrados.map(t => `<button type="button" class="btn" style="margin:.15rem" data-impuesto-otro-elegir="${lineaId}" data-impuesto-otro-nombre="${escapeHtml(t.name)}">${escapeHtml(t.name)} (${t.amount}%)</button>`).join('')
            : '<span class="placeholder">Sin resultados.</span>';
          resEl.querySelectorAll('[data-impuesto-otro-elegir]').forEach(rbtn => {
            rbtn.onclick = () => toggleImpuestoLinea(lineaId, rbtn.dataset.impuestoOtroNombre);
          });
        };
      };
    });

    overlay.querySelectorAll('[data-confirmar-sugerido]').forEach(btn => {
      btn.onclick = async () => {
        const lineaId = btn.dataset.confirmarSugerido;
        const linea = dte.lineas.find(x => String(x.id) === String(lineaId));
        const errorEl = overlay.querySelector('#dte-modal-error');
        errorEl.textContent = '';
        try {
          await api('/facturas-dte/lineas/match', {
            method: 'POST',
            body: JSON.stringify({
              dte_id: dteId, line_id: parseInt(lineaId, 10),
              codigo_tipo: linea?.codigo_tipo || null, codigo_valor: linea?.codigo_valor || null,
              odoo_product_id: linea.product_id, odoo_product_name: linea.product_name,
              proveedor_rut: dte.proveedor_rut, proveedor_nombre: dte.proveedor_nombre,
            }),
          });
          recargar();
        } catch (err) {
          errorEl.textContent = err.message;
        }
      };
    });

    overlay.querySelectorAll('[data-ejecutar-busqueda]').forEach(btn => {
      btn.onclick = async () => {
        const lineaId = btn.dataset.ejecutarBusqueda;
        const q = overlay.querySelector(`.dte-buscar-input[data-linea-buscar="${lineaId}"]`).value.trim();
        const resultadosEl = overlay.querySelector(`[data-resultados="${lineaId}"]`);
        if (!q) return;
        resultadosEl.innerHTML = '<span class="placeholder">Buscando…</span>';
        try {
          const productos = await api(`/facturas-dte/productos/buscar?q=${encodeURIComponent(q)}`);
          resultadosEl.innerHTML = productos.length
            ? productos.map(p => `<button type="button" class="btn" style="margin:.2rem" data-elegir-producto="${p.id}" data-nombre="${escapeHtml(p.name)}">${escapeHtml(p.name)}${p.default_code ? ' (' + escapeHtml(p.default_code) + ')' : ''}</button>`).join('')
            : '<span class="placeholder">Sin resultados.</span>';
          resultadosEl.querySelectorAll('[data-elegir-producto]').forEach(pbtn => {
            pbtn.onclick = async () => {
              const fila = overlay.querySelector(`tr[data-linea="${lineaId}"]`);
              const linea = dte.lineas.find(x => String(x.id) === String(lineaId));
              const errorEl = overlay.querySelector('#dte-modal-error');
              errorEl.textContent = '';
              try {
                await api('/facturas-dte/lineas/match', {
                  method: 'POST',
                  body: JSON.stringify({
                    dte_id: dteId, line_id: parseInt(lineaId, 10),
                    codigo_tipo: linea?.codigo_tipo || null, codigo_valor: linea?.codigo_valor || null,
                    odoo_product_id: parseInt(pbtn.dataset.elegirProducto, 10), odoo_product_name: pbtn.dataset.nombre,
                    proveedor_rut: dte.proveedor_rut, proveedor_nombre: dte.proveedor_nombre,
                  }),
                });
                recargar();
              } catch (err) {
                errorEl.textContent = err.message;
              }
            };
          });
        } catch (err) {
          resultadosEl.innerHTML = `<span class="error-msg">${err.message}</span>`;
        }
      };
    });

    overlay.querySelector('#dte-modal-crear')?.addEventListener('click', async () => {
      const errorEl = overlay.querySelector('#dte-modal-error');
      if (!confirm('¿Crear la factura en Odoo como borrador? No se postea sola, queda para que contabilidad la revise.')) return;
      errorEl.textContent = '';
      try {
        await api(`/facturas-dte/${dteId}/crear-factura`, { method: 'POST' });
        overlay.remove();
        state.dteLista = (state.dteLista || []).filter(d => d.id !== dteId);
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  }

  try {
    await recargar();
  } catch (err) {
    overlay.querySelector('.modal-box').innerHTML = `<p class="error-msg">${err.message}</p><button type="button" class="btn" id="dte-modal-cerrar-error">Cerrar</button>`;
    overlay.querySelector('#dte-modal-cerrar-error').onclick = () => overlay.remove();
  }
}

function _fmtMonto(n) {
  return n == null ? '—' : '$' + Math.round(n).toLocaleString('es-CL');
}

async function showCompararModal(dteId) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:960px"><p class="placeholder">Cargando…</p></div>';
  document.body.appendChild(overlay);

  try {
    const c = await api(`/facturas-dte/${dteId}/comparar`);
    const diffMonto = (a, b) => Math.abs(a - b) > 9;
    overlay.querySelector('.modal-box').innerHTML = `
      <h3>Comparación — ${escapeHtml(c.invoice_name)}</h3>
      <p class="placeholder" style="margin-bottom:1rem">Lo que declaró el proveedor en su factura electrónica (DTE) vs. lo que quedó realmente creado en Odoo.</p>
      <table style="margin-bottom:1rem">
        <thead><tr><th></th><th>Neto</th><th>Impuestos</th><th>Total</th></tr></thead>
        <tbody>
          <tr><td>DTE del proveedor</td><td>${_fmtMonto(c.neto_dte)}</td><td>${_fmtMonto(c.impuestos_dte)}</td><td>${_fmtMonto(c.total_dte)}</td></tr>
          <tr>
            <td>Creado en Odoo</td>
            <td class="${diffMonto(c.neto_dte, c.neto_odoo) ? 'error-msg' : ''}">${_fmtMonto(c.neto_odoo)}</td>
            <td class="${diffMonto(c.impuestos_dte, c.impuestos_odoo) ? 'error-msg' : ''}">${_fmtMonto(c.impuestos_odoo)}</td>
            <td class="${diffMonto(c.total_dte, c.total_odoo) ? 'error-msg' : ''}">${_fmtMonto(c.total_odoo)}</td>
          </tr>
        </tbody>
      </table>
      <table>
        <thead><tr>
          <th colspan="3">Declarado en el DTE</th><th colspan="4">Creado en Odoo</th>
        </tr><tr>
          <th>Ítem</th><th>Cant.</th><th>Precio unit.</th>
          <th>Producto</th><th>Cant.</th><th>Precio unit.</th><th>Impuestos</th>
        </tr></thead>
        <tbody>
          ${c.lineas.map(l => `
            <tr>
              <td>${escapeHtml(l.item_name)}</td>
              <td>${l.qty_dte}</td>
              <td>${_fmtMonto(l.precio_dte)}</td>
              <td>${l.producto_nombre ? escapeHtml(l.producto_nombre) : '<span class="placeholder">—</span>'}</td>
              <td>${l.qty_odoo ?? '<span class="placeholder">—</span>'}</td>
              <td>${l.precio_odoo != null ? _fmtMonto(l.precio_odoo) : '<span class="placeholder">—</span>'}</td>
              <td>${l.impuestos_odoo.length ? l.impuestos_odoo.map(escapeHtml).join(', ') : '<span class="placeholder">por defecto</span>'}</td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div style="margin-top:1.25rem"><button type="button" class="btn" id="comparar-modal-cerrar">Cerrar</button></div>`;
    overlay.querySelector('#comparar-modal-cerrar').onclick = () => overlay.remove();
  } catch (err) {
    overlay.querySelector('.modal-box').innerHTML = `<p class="error-msg">${err.message}</p><button type="button" class="btn" id="comparar-modal-cerrar-error">Cerrar</button>`;
    overlay.querySelector('#comparar-modal-cerrar-error').onclick = () => overlay.remove();
  }
}

const TIPOS_PLANILLA_COMPRAS = [
  { id: 'AL', label: 'AL — Alimentos' },
  { id: 'BA', label: 'BA — Barra' },
  { id: 'GF', label: 'GF — Gastos Fijos' },
  { id: 'OT', label: 'OT — Otros' },
  { id: 'AS', label: 'AS — Aseo' },
];

async function renderPlanillaCompras(el, s) {
  const hoy = new Date();
  if (!state.planillaMes) state.planillaMes = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}`;
  const items = state.planillaItems || [];
  const resumen = state.planillaResumen || {};
  const filtro = (state.planillaFiltroFolio || '').trim().toLowerCase();
  const itemsFiltrados = filtro ? items.filter(it => (it.num_factura || '').toLowerCase().includes(filtro)) : items;

  // Los totales (por Tipo y % Costo Venta) siempre son del mes completo --
  // el filtro es solo para ubicar una factura puntual mas rapido en la
  // tabla, no para recalcular el resumen.
  const totalesPorTipo = TIPOS_PLANILLA_COMPRAS.reduce((acc, t) => { acc[t.id] = 0; return acc; }, {});
  let totalGeneral = 0;
  let sinTipo = 0;
  items.forEach(it => {
    totalGeneral += it.total;
    if (it.tipo && totalesPorTipo[it.tipo] !== undefined) totalesPorTipo[it.tipo] += it.total;
    else sinTipo++;
  });

  const metaPct = resumen.meta_pct != null ? resumen.meta_pct : 0.33;
  const pctTexto = resumen.pct_costo_venta != null ? (resumen.pct_costo_venta * 100).toFixed(1) + '%' : '—';
  const pctBien = resumen.pct_costo_venta != null && resumen.pct_costo_venta <= metaPct;

  el.innerHTML = `
    <h2>Planilla de Compras</h2>
    <p class="placeholder" style="margin-bottom:1.25rem">Facturas de proveedor ya ingresadas en Odoo este mes (Doña Delfina) -- así sabemos cuáles están y cuáles faltan. El Tipo es por proveedor, se guarda solo acá.</p>
    <div class="item-row" style="max-width:420px;margin-bottom:1rem">
      <div style="flex:1">
        <label class="field-label">Mes</label>
        <input type="month" id="pc-mes" class="field" style="width:100%" value="${state.planillaMes}">
      </div>
      <div style="display:flex;align-items:flex-end">
        <button type="button" id="pc-buscar" class="btn btn-primary">Buscar</button>
      </div>
      <div style="display:flex;align-items:flex-end">
        <button type="button" id="pc-catalogo" class="btn">Categorías de proveedores</button>
      </div>
      ${state.planillaItems !== null ? `
      <div style="display:flex;align-items:flex-end">
        <button type="button" id="pc-exportar" class="btn">Exportar Excel</button>
      </div>
      <div style="display:flex;align-items:flex-end">
        <button type="button" id="pc-faltantes" class="btn" title="Compara contra las facturas de Facturas Odoo que ya tienen factura real en Odoo, para encontrar las que quedan omitidas de esta planilla">Verificar facturas faltantes</button>
      </div>` : ''}
    </div>
    <p id="pc-error" class="error-msg"></p>
    ${state.planillaItems !== null ? `
      <div class="card" style="margin-bottom:1rem">
        <h3>% Costo Venta</h3>
        <div class="item-row" style="max-width:420px;margin-bottom:.75rem">
          <div style="flex:1">
            <label class="field-label">Venta del período ($, con IVA)</label>
            <input type="number" id="pc-venta-periodo" class="field" style="width:100%" value="${resumen.venta_periodo ?? ''}" placeholder="Ingresa la venta del mes">
          </div>
          <div style="display:flex;align-items:flex-end">
            <button type="button" id="pc-traer-tcpos" class="btn">Traer de TCPOS</button>
          </div>
          <div style="display:flex;align-items:flex-end">
            <button type="button" id="pc-guardar-venta" class="btn btn-primary">Guardar</button>
          </div>
        </div>
        <p id="pc-tcpos-info" class="placeholder" style="margin-bottom:.5rem"></p>
        <p>
          Costo Venta (Alimentos + Barra): <strong>$${Math.round(resumen.costo_venta || 0).toLocaleString('es-CL')}</strong>
          &nbsp;·&nbsp; Venta Neta: <strong>${resumen.venta_neta != null ? '$' + Math.round(resumen.venta_neta).toLocaleString('es-CL') : '—'}</strong>
          &nbsp;·&nbsp; % Costo Venta: <strong style="color:${resumen.pct_costo_venta == null ? 'inherit' : (pctBien ? '#1a7f37' : '#c0392b')}">${pctTexto}</strong>
          ${resumen.pct_costo_venta != null ? `<span class="placeholder">(meta ${(metaPct * 100).toFixed(0)}% o menos -- ${pctBien ? 'BIEN' : 'MAL'})</span>` : ''}
        </p>
      </div>` : ''}
    ${state.planillaItems === null ? '<div class="card"><p class="placeholder">Buscá para ver las facturas del mes.</p></div>' : ''}
    ${state.planillaItems && !items.length ? '<div class="card"><p class="placeholder">No hay facturas ingresadas en Odoo para ese mes.</p></div>' : ''}
    ${items.length ? `
      <div style="max-width:280px;margin-bottom:1rem">
        <label class="field-label">Buscar por N° de factura</label>
        <input type="text" id="pc-filtro-folio" class="field" style="width:100%" placeholder="Ej. 10199" value="${state.planillaFiltroFolio || ''}">
      </div>
      <div id="pc-tabla-card">${_renderPlanillaTablaCard(itemsFiltrados, totalesPorTipo, totalGeneral, sinTipo, filtro, state.planillaFiltroFolio)}</div>` : ''}`;

  document.getElementById('pc-mes').addEventListener('change', (e) => { state.planillaMes = e.target.value; });

  document.getElementById('pc-buscar').addEventListener('click', async () => {
    const errorEl = document.getElementById('pc-error');
    errorEl.textContent = '';
    const [anio, mes] = state.planillaMes.split('-').map(Number);
    try {
      const res = await api(`/planilla-compras?anio=${anio}&mes=${mes}`);
      state.planillaItems = res.items;
      state.planillaResumen = res.resumen;
      renderView();
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('pc-catalogo').addEventListener('click', showCatalogoProveedoresTipo);

  document.getElementById('pc-exportar')?.addEventListener('click', async () => {
    const errorEl = document.getElementById('pc-error');
    errorEl.textContent = '';
    const [anio, mes] = state.planillaMes.split('-').map(Number);
    try {
      await apiDownload(`/planilla-compras/exportar?anio=${anio}&mes=${mes}`, `Planilla de Compras ${state.planillaMes}.xlsx`);
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('pc-faltantes')?.addEventListener('click', () => {
    const [anio, mes] = state.planillaMes.split('-').map(Number);
    showPlanillaFaltantesModal(anio, mes);
  });

  document.getElementById('pc-traer-tcpos')?.addEventListener('click', async () => {
    const errorEl = document.getElementById('pc-error');
    const infoEl = document.getElementById('pc-tcpos-info');
    errorEl.textContent = '';
    infoEl.textContent = 'Consultando TCPOS…';
    const [anio, mes] = state.planillaMes.split('-').map(Number);
    try {
      const res = await api(`/planilla-compras/venta-periodo/tcpos?anio=${anio}&mes=${mes}`);
      document.getElementById('pc-venta-periodo').value = res.venta_periodo;
      infoEl.textContent = `TCPOS (Cash to deposit): $${Math.round(res.venta_periodo).toLocaleString('es-CL')} -- del ${res.desde} al ${res.hasta}. Revisa y hace clic en Guardar.`;
    } catch (err) {
      infoEl.textContent = '';
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('pc-guardar-venta')?.addEventListener('click', async () => {
    const errorEl = document.getElementById('pc-error');
    errorEl.textContent = '';
    const valor = parseFloat(document.getElementById('pc-venta-periodo').value);
    if (!valor) { errorEl.textContent = 'Ingresa un monto de venta válido.'; return; }
    const [anio, mes] = state.planillaMes.split('-').map(Number);
    try {
      await api('/planilla-compras/venta-periodo', {
        method: 'PUT',
        body: JSON.stringify({ anio, mes, venta_periodo: valor }),
      });
      const res = await api(`/planilla-compras?anio=${anio}&mes=${mes}`);
      state.planillaItems = res.items;
      state.planillaResumen = res.resumen;
      renderView();
    } catch (err) {
      errorEl.textContent = err.message;
    }
  });

  document.getElementById('pc-filtro-folio')?.addEventListener('input', (e) => {
    state.planillaFiltroFolio = e.target.value;
    const nuevoFiltro = state.planillaFiltroFolio.trim().toLowerCase();
    const nuevosItemsFiltrados = nuevoFiltro
      ? items.filter(it => (it.num_factura || '').toLowerCase().includes(nuevoFiltro))
      : items;
    document.getElementById('pc-tabla-card').innerHTML =
      _renderPlanillaTablaCard(nuevosItemsFiltrados, totalesPorTipo, totalGeneral, sinTipo, nuevoFiltro, state.planillaFiltroFolio);
    bindPlanillaTipoSelects();
  });

  bindPlanillaTipoSelects();
}

function bindPlanillaTipoSelects() {
  document.querySelectorAll('[data-tipo-proveedor]').forEach(sel => {
    sel.addEventListener('change', async () => {
      const errorEl = document.getElementById('pc-error');
      errorEl.textContent = '';
      const proveedorId = parseInt(sel.dataset.tipoProveedor, 10);
      if (!sel.value) return;
      try {
        await api('/planilla-compras/proveedores', {
          method: 'PUT',
          body: JSON.stringify({ odoo_partner_id: proveedorId, proveedor_nombre: sel.dataset.nombreProveedor, tipo: sel.value }),
        });
        state.planillaItems = state.planillaItems.map(it => it.proveedor_id === proveedorId ? { ...it, tipo: sel.value } : it);
        renderView();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    });
  });
}

function _renderPlanillaTablaCard(itemsFiltrados, totalesPorTipo, totalGeneral, sinTipo, filtro, filtroTexto) {
  return `
    <div class="card">
      ${sinTipo ? `<p class="error-msg" style="margin-bottom:.75rem">${sinTipo} factura(s) de proveedores sin Tipo asignado -- clasifícalos en "Categorías de proveedores".</p>` : ''}
      ${filtro && !itemsFiltrados.length ? `<p class="placeholder" style="margin-bottom:.75rem">Ningún N° de factura coincide con "${escapeHtml(filtroTexto)}".</p>` : ''}
      <table>
        <thead><tr><th>Fecha</th><th>Proveedor</th><th>N° Factura</th><th>Subtotal</th><th>IVA</th><th>Total</th><th>Tipo</th></tr></thead>
        <tbody>
          ${itemsFiltrados.map(it => `
            <tr>
              <td>${it.fecha || '—'}</td>
              <td>${escapeHtml(it.proveedor_nombre)}</td>
              <td>${it.num_factura ? escapeHtml(it.num_factura) : '—'}</td>
              <td>$${Math.round(it.subtotal).toLocaleString('es-CL')}</td>
              <td>$${Math.round(it.iva).toLocaleString('es-CL')}</td>
              <td>$${Math.round(it.total).toLocaleString('es-CL')}</td>
              <td>
                <select class="field" data-tipo-proveedor="${it.proveedor_id}" data-nombre-proveedor="${escapeHtml(it.proveedor_nombre || '')}">
                  <option value="">— Sin asignar —</option>
                  ${TIPOS_PLANILLA_COMPRAS.map(t => `<option value="${t.id}" ${it.tipo === t.id ? 'selected' : ''}>${t.label}</option>`).join('')}
                </select>
              </td>
            </tr>`).join('')}
        </tbody>
        <tfoot>
          ${TIPOS_PLANILLA_COMPRAS.map(t => `<tr><td colspan="5" style="text-align:right">${t.label}</td><td colspan="2">$${Math.round(totalesPorTipo[t.id]).toLocaleString('es-CL')}</td></tr>`).join('')}
          <tr><td colspan="5" style="text-align:right"><strong>Total</strong></td><td colspan="2"><strong>$${Math.round(totalGeneral).toLocaleString('es-CL')}</strong></td></tr>
        </tfoot>
      </table>
    </div>`;
}

async function showPlanillaFaltantesModal(anio, mes) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:760px"><p class="placeholder">Buscando…</p></div>';
  document.body.appendChild(overlay);

  async function cargar() {
    try {
      const faltantes = await api(`/planilla-compras/faltantes?anio=${anio}&mes=${mes}`);
      overlay.querySelector('.modal-box').innerHTML = `
        <h3>Facturas faltantes en Planilla de Compras</h3>
        <p class="placeholder" style="margin-bottom:1rem">Facturas de Facturas Odoo que ya tienen una factura real en Odoo pero no aparecen en esta planilla (normalmente porque no tienen Orden de Compra detrás, ej. ingresadas a mano). Solo informativo -- no se agrega nada hasta que apretás "Agregar".</p>
        ${faltantes.length ? `
          <table>
            <thead><tr><th>Proveedor</th><th>Folio</th><th>Fecha</th><th>Total</th><th></th></tr></thead>
            <tbody>
              ${faltantes.map(f => `
                <tr>
                  <td>${escapeHtml(f.proveedor_nombre)}</td>
                  <td>${escapeHtml(f.folio)}</td>
                  <td>${f.fecha || '—'}</td>
                  <td>${_fmtMonto(f.total)}</td>
                  <td><button type="button" class="btn btn-primary" data-agregar-faltante="${f.factura_id}">Agregar</button></td>
                </tr>`).join('')}
            </tbody>
          </table>` : '<p class="placeholder">No hay ninguna -- Planilla de Compras ya incluye todas las facturas de Facturas Odoo de este mes.</p>'}
        <p id="pc-faltantes-error" class="error-msg"></p>
        <div style="margin-top:1.25rem"><button type="button" class="btn" id="pc-faltantes-cerrar">Cerrar</button></div>`;
      overlay.querySelector('#pc-faltantes-cerrar').onclick = () => overlay.remove();
      overlay.querySelectorAll('[data-agregar-faltante]').forEach(btn => {
        btn.onclick = async () => {
          const errorEl = overlay.querySelector('#pc-faltantes-error');
          errorEl.textContent = '';
          try {
            await api(`/planilla-compras/faltantes/${btn.dataset.agregarFaltante}/agregar`, { method: 'POST' });
            if (state.planillaMes === `${anio}-${String(mes).padStart(2, '0')}`) {
              const res = await api(`/planilla-compras?anio=${anio}&mes=${mes}`);
              state.planillaItems = res.items;
              state.planillaResumen = res.resumen;
            }
            await cargar();
            renderView();
          } catch (err) {
            errorEl.textContent = err.message;
          }
        };
      });
    } catch (err) {
      overlay.querySelector('.modal-box').innerHTML = `<p class="error-msg">${err.message}</p><button type="button" class="btn" id="pc-faltantes-cerrar-error">Cerrar</button>`;
      overlay.querySelector('#pc-faltantes-cerrar-error').onclick = () => overlay.remove();
    }
  }
  await cargar();
}

async function showCatalogoProveedoresTipo() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = '<div class="modal-box" style="width:560px"><p class="placeholder">Cargando…</p></div>';
  document.body.appendChild(overlay);

  try {
    const proveedores = await api('/planilla-compras/proveedores');
    overlay.querySelector('.modal-box').innerHTML = `
      <h3>Categorías de proveedores</h3>
      <p class="placeholder" style="margin-bottom:1rem">Cada proveedor tiene un Tipo fijo (ej. Paltas Royal = Alimentos). Se asigna la primera vez desde la Planilla de Compras y queda guardado acá.</p>
      ${proveedores.length ? `
        <table>
          <thead><tr><th>Proveedor</th><th>Tipo</th></tr></thead>
          <tbody>
            ${proveedores.map(p => `<tr><td>${escapeHtml(p.proveedor_nombre)}</td><td>${TIPOS_PLANILLA_COMPRAS.find(t => t.id === p.tipo)?.label || p.tipo}</td></tr>`).join('')}
          </tbody>
        </table>` : '<p class="placeholder">Todavía no hay proveedores clasificados.</p>'}
      <div style="margin-top:1.25rem">
        <button type="button" class="btn" id="pc-catalogo-cerrar">Cerrar</button>
      </div>`;
    overlay.querySelector('#pc-catalogo-cerrar').onclick = () => overlay.remove();
  } catch (err) {
    overlay.querySelector('.modal-box').innerHTML = `<p class="error-msg">${err.message}</p><button type="button" class="btn" id="pc-catalogo-cerrar-error">Cerrar</button>`;
    overlay.querySelector('#pc-catalogo-cerrar-error').onclick = () => overlay.remove();
  }
}

// ---------- Init ----------

if (state.token && state.usuario) {
  showApp();
} else {
  showLogin();
}
