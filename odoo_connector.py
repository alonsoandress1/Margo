#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
odoo_connector.py — Clientes para Odoo (dos modos)
Compatible con Odoo 14, 15, 16, 17 (Community y Enterprise).
Sin dependencias externas — usa stdlib únicamente.

  OdooClient    — API externa clásica (/xmlrpc/2/*). Requiere saber el
                  nombre exacto de la base de datos (db).
  OdooWebSession — autentica igual que un humano en el navegador
                  (POST a /web/login con usuario+contraseña). NO requiere
                  el nombre de la base de datos — Odoo la resuelve solo
                  según el dominio (dbfilter). Preferir este modo salvo
                  que se conozca el db name con certeza.
"""

import xmlrpc.client
import socket
import re
import json as _json
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


class OdooClient:
    """
    Cliente XML-RPC ligero para Odoo.

    Flujo típico:
        client = OdooClient(url, db, user, api_key)
        ok, msg = client.connect()
        if ok:
            products = client.get_products_by_ref(["SKU001", "SKU002"])
            prices   = client.get_supplier_prices([p['id'] for p in products.values()])
    """

    def __init__(self, url: str, db: str, user: str, password: str, timeout: int = 20):
        self.url      = url.rstrip('/')
        self.db       = db
        self.user     = user
        self.password = password
        self.timeout  = timeout
        self.uid: Optional[int] = None

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self) -> tuple[bool, str]:
        """Autenticar. Retorna (éxito, mensaje)."""
        prev_to = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self.timeout)
            common = xmlrpc.client.ServerProxy(
                f'{self.url}/xmlrpc/2/common', allow_none=True)
            uid = common.authenticate(self.db, self.user, self.password, {})
            if not uid:
                return False, "Credenciales incorrectas o base de datos no encontrada."
            self.uid = int(uid)
            try:
                info = common.version()
                ver  = info.get('server_version', '') or info.get('server_serie', '?')
                return True, f"Conectado — Odoo {ver} — usuario #{self.uid}"
            except Exception:
                return True, f"Conectado — usuario #{self.uid}"
        except ConnectionRefusedError:
            return False, "Conexión rechazada. Verifica la URL del servidor."
        except (OSError, TimeoutError) as e:
            return False, f"Error de red: {e}"
        except socket.timeout:
            return False, f"Tiempo de espera agotado ({self.timeout}s). Verifica la URL."
        except xmlrpc.client.Fault as e:
            return False, f"Fallo Odoo: {e.faultString}"
        except Exception as e:
            return False, str(e)
        finally:
            socket.setdefaulttimeout(prev_to)

    def _call(self, model: str, method: str, args: list, kw: dict | None = None):
        if not self.uid:
            raise RuntimeError("No autenticado — llama connect() primero.")
        prev_to = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self.timeout)
            proxy = xmlrpc.client.ServerProxy(
                f'{self.url}/xmlrpc/2/object', allow_none=True)
            return proxy.execute_kw(
                self.db, self.uid, self.password,
                model, method, args, kw or {})
        finally:
            socket.setdefaulttimeout(prev_to)

    # ── Productos ─────────────────────────────────────────────────────────────

    def search_products(self, query: str = '', limit: int = 60) -> list[dict]:
        """Busca productos de compra por nombre o referencia interna."""
        domain: list = [['purchase_ok', '=', True]]
        if query.strip():
            domain += [['|',
                        ['name', 'ilike', query],
                        ['default_code', 'ilike', query]]]
        recs = self._call('product.product', 'search_read', [domain], {
            'fields': ['id', 'name', 'default_code', 'uom_po_id', 'uom_id'],
            'limit': limit,
        })
        result = []
        for r in recs:
            uom = r.get('uom_po_id') or r.get('uom_id') or [None, '']
            result.append({
                'id':   r['id'],
                'name': r['name'],
                'ref':  r.get('default_code') or '',
                'uom':  uom[1] if len(uom) > 1 else '',
            })
        return result

    def get_products_by_ref(self, refs: list[str]) -> dict[str, dict]:
        """
        Retorna {default_code: {id, tmpl_id, name, uom, uom_id}}
        para los internal references proporcionados.
        """
        clean = [r for r in refs if r and r.strip()]
        if not clean:
            return {}
        recs = self._call('product.product', 'search_read',
            [[['default_code', 'in', clean]]], {
                'fields': ['id', 'name', 'default_code',
                           'uom_po_id', 'product_tmpl_id'],
            })
        out = {}
        for r in recs:
            code = r.get('default_code') or ''
            if not code:
                continue
            uom  = r.get('uom_po_id') or [None, '']
            tmpl = r.get('product_tmpl_id')
            out[code] = {
                'id':      r['id'],
                'tmpl_id': tmpl[0] if isinstance(tmpl, list) else tmpl,
                'name':    r['name'],
                'uom':     uom[1] if len(uom) > 1 else '',
                'uom_id':  uom[0] if uom else None,
            }
        return out

    # ── Precios de proveedor ──────────────────────────────────────────────────

    def get_supplier_prices(self, product_ids: list[int]) -> dict[int, list[dict]]:
        """
        Retorna precios de proveedor agrupados por product_id.
        {product_id: [{partner_id, partner_name, price, currency, min_qty, delay}]}
        """
        if not product_ids:
            return {}
        recs = self._call('product.supplierinfo', 'search_read',
            [[['product_id', 'in', [int(i) for i in product_ids]]]], {
                'fields': ['product_id', 'partner_id', 'price',
                           'currency_id', 'min_qty', 'delay'],
            })
        out: dict[int, list] = {}
        for r in recs:
            raw_pid = r.get('product_id')
            pid = raw_pid[0] if isinstance(raw_pid, list) else raw_pid
            if pid is None:
                continue
            partner = r.get('partner_id') or [0, '']
            cur     = r.get('currency_id') or [0, 'CLP']
            out.setdefault(int(pid), []).append({
                'partner_id':   int(partner[0] if isinstance(partner, list) else partner),
                'partner_name': partner[1] if isinstance(partner, list) else '',
                'price':        float(r.get('price') or 0),
                'currency':     cur[1] if isinstance(cur, list) else 'CLP',
                'min_qty':      float(r.get('min_qty') or 0),
                'delay':        int(r.get('delay') or 0),
            })
        return out

    # ── Órdenes de compra ─────────────────────────────────────────────────────

    def create_purchase_order(
        self,
        partner_id: int,
        lines: list[dict],
        notes: str = '',
    ) -> tuple[int, str]:
        """
        Crea una purchase.order en estado Draft y retorna (po_id, po_name).
        lines: [{product_id, name, product_qty, price_unit, product_uom (opt)}]
        """
        from datetime import datetime, timedelta
        default_planned = (
            datetime.now() + timedelta(days=2)
        ).strftime('%Y-%m-%d %H:%M:%S')

        order_lines = []
        for l in lines:
            lv: dict = {
                'product_id':   int(l['product_id']),
                'name':         str(l.get('name', '')),
                'product_qty':  float(l.get('product_qty', 1)),
                'price_unit':   float(l.get('price_unit', 0)),
                'date_planned': l.get('date_planned', default_planned),
            }
            if l.get('product_uom'):
                lv['product_uom'] = int(l['product_uom'])
            order_lines.append((0, 0, lv))

        vals: dict = {
            'partner_id': int(partner_id),
            'order_line': order_lines,
        }
        if notes:
            vals['notes'] = notes

        po_id = self._call('purchase.order', 'create', [vals])
        try:
            rec  = self._call('purchase.order', 'read',
                              [[int(po_id)]], {'fields': ['name']})
            name = rec[0]['name'] if rec else f'PO#{po_id}'
        except Exception:
            name = f'PO#{po_id}'
        return int(po_id), name


class OdooWebSession:
    """
    Cliente que autentica EXACTAMENTE como un humano en el navegador —
    usuario + contraseña, sin necesitar el nombre de la base de datos.
    Odoo la resuelve solo en el servidor según el dominio (dbfilter),
    igual que cuando alguien entra por /web/login sin ver ningún selector.

    Uso:
        session = OdooWebSession(url)
        ok, msg = session.connect(user, password)
        if ok:
            po_id = session.call_kw('purchase.order', 'create', [[vals]])

    Internamente usa las mismas rutas que el propio cliente web de Odoo
    (/web/login para autenticar, /web/dataset/call_kw para operar) — no es
    automatización de navegador (no hay browser real ni parseo de UI), son
    los mismos requests HTTP/JSON-RPC que el navegador manda por detrás.
    """

    def __init__(self, url: str, timeout: int = 20):
        self.url     = url.rstrip('/')
        self.timeout = timeout
        self.uid: Optional[int] = None
        self._cookiejar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookiejar))
        self._csrf_token: Optional[str] = None

    def _get_csrf_token(self) -> str:
        req = urllib.request.Request(f'{self.url}/web/login')
        with self._opener.open(req, timeout=self.timeout) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if not m:
            raise RuntimeError("No se encontró csrf_token en la página de login "
                                "— ¿la URL es correcta?")
        return m.group(1)

    def connect(self, user: str, password: str) -> tuple[bool, str]:
        """Autentica. Retorna (éxito, mensaje). No requiere db."""
        try:
            self._csrf_token = self._get_csrf_token()
            data = urllib.parse.urlencode({
                'csrf_token': self._csrf_token,
                'login':      user,
                'password':   password,
                'type':       'password',
                'redirect':   '',
            }).encode()
            req = urllib.request.Request(f'{self.url}/web/login', data=data)
            with self._opener.open(req, timeout=self.timeout) as resp:
                html = resp.read().decode('utf-8', errors='replace')

            if 'alert-danger' in html:
                m = re.search(r'alert-danger"[^>]*>\s*([^<]+)', html)
                motivo = m.group(1).strip() if m else "credenciales inválidas"
                return False, f"Login rechazado: {motivo}"

            info = self._call_raw('/web/session/get_session_info', {})
            uid = (info or {}).get('uid')
            if not uid:
                return False, "No se pudo confirmar la sesión tras el login."
            self.uid = int(uid)
            return True, f"Conectado — usuario #{self.uid} (sesión web, sin db explícita)"
        except urllib.error.URLError as e:
            return False, f"Error de red: {e}"
        except Exception as e:
            return False, str(e)

    def _call_raw(self, path: str, payload: dict):
        body = _json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': payload}).encode()
        headers = {'Content-Type': 'application/json'}
        if self._csrf_token:
            headers['X-CSRF-Token'] = self._csrf_token
        req = urllib.request.Request(f'{self.url}{path}', data=body, headers=headers)
        with self._opener.open(req, timeout=self.timeout) as resp:
            raw = resp.read().decode('utf-8')
        result = _json.loads(raw)
        if result.get('error'):
            err  = result['error']
            data = err.get('data', {})
            raise RuntimeError(data.get('message') or err.get('message') or str(err))
        return result.get('result')

    def call_kw(self, model: str, method: str, args: list, kwargs: dict | None = None):
        """Llama a cualquier método de modelo Odoo vía /web/dataset/call_kw
        (equivalente funcional a OdooClient._call, pero sobre la sesión web)."""
        if not self.uid:
            raise RuntimeError("No autenticado — llama connect() primero.")
        return self._call_raw('/web/dataset/call_kw', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def get_report_name_for_model(self, model: str) -> Optional[str]:
        """Busca el nombre tecnico (report_name) del reporte PDF configurado
        para un modelo, ej. 'purchase.order' -> 'purchase.report_purchasequotation'.
        Se busca en vez de asumirlo fijo porque puede variar segun version/
        personalizacion del Odoo del cliente."""
        recs = self.call_kw('ir.actions.report', 'search_read',
            [[['model', '=', model], ['report_type', '=', 'qweb-pdf']]],
            {'fields': ['report_name'], 'limit': 1})
        return recs[0]['report_name'] if recs else None

    def download_pdf_report(self, report_name: str, record_ids: list[int]) -> bytes:
        """Descarga el PDF de un reporte QWeb ya generado en Odoo (ej. la
        Orden de Compra recien creada), reusando la misma sesion autenticada
        -- mismo endpoint que usa el boton "Imprimir" en el navegador."""
        if not self.uid:
            raise RuntimeError("No autenticado — llama connect() primero.")
        ids_str = ",".join(str(int(i)) for i in record_ids)
        req = urllib.request.Request(f'{self.url}/report/pdf/{report_name}/{ids_str}')
        with self._opener.open(req, timeout=self.timeout) as resp:
            data = resp.read()
        if not data.startswith(b'%PDF'):
            raise RuntimeError("Odoo no devolvió un PDF valido para el reporte solicitado.")
        return data

    def create_purchase_order(self, partner_id: int, lines: list[dict],
                               notes: str = '') -> tuple[int, str]:
        """Igual que OdooClient.create_purchase_order pero sobre la sesión web."""
        from datetime import datetime, timedelta
        default_planned = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        order_lines = []
        for l in lines:
            lv: dict = {
                'product_id':   int(l['product_id']),
                'name':         str(l.get('name', '')),
                'product_qty':  float(l.get('product_qty', 1)),
                'price_unit':   float(l.get('price_unit', 0)),
                'date_planned': l.get('date_planned', default_planned),
            }
            if l.get('product_uom'):
                lv['product_uom'] = int(l['product_uom'])
            order_lines.append((0, 0, lv))
        vals: dict = {'partner_id': int(partner_id), 'order_line': order_lines}
        if notes:
            vals['notes'] = notes
        po_id = self.call_kw('purchase.order', 'create', [vals])
        try:
            rec  = self.call_kw('purchase.order', 'read', [[int(po_id)]], {'fields': ['name']})
            name = rec[0]['name'] if rec else f'PO#{po_id}'
        except Exception:
            name = f'PO#{po_id}'
        return int(po_id), name


# ── CLI de prueba: pide credenciales, prueba conexión, no guarda nada ─────────
#
# Uso: python odoo_connector.py
# Este es el mismo patrón que usará el sistema real (tarea #7): la contraseña
# se pide con getpass (no queda en pantalla, no se loguea), se usa solo para
# esta llamada y se descarta al terminar el script — nunca se escribe a disco.
#
# Por defecto usa OdooWebSession (sin necesitar el nombre de la base de
# datos). Solo pide "modo clásico" (OdooClient + db explícita) si el
# usuario lo pide a propósito.
if __name__ == '__main__':
    import getpass

    print("Prueba de conexión Odoo — las credenciales NO se guardan en ningún lado.\n")
    url = input("URL de Odoo (ej. https://margo.odoo.com): ").strip()

    modo = input(
        "¿Modo? [1] Como un usuario normal, sin base de datos (recomendado)  "
        "[2] Clásico, con base de datos explícita  → "
    ).strip()

    user = input("Usuario (email): ").strip()
    password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

    if modo == '2':
        db = input("Base de datos: ").strip()
        client = OdooClient(url, db, user, password)
        ok, msg = client.connect()
    else:
        session = OdooWebSession(url)
        ok, msg = session.connect(user, password)

    # A partir de aquí `password` ya no se usa más — sale de scope al terminar
    # el script, sin haber tocado disco ni logs en ningún momento.
    print()
    print(("✓ " if ok else "✗ ") + msg)
    input("\nPresiona Enter para cerrar...")
