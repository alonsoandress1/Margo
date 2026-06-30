#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
odoo_connector.py — Cliente XML-RPC para Odoo
Compatible con Odoo 14, 15, 16, 17 (Community y Enterprise).
Sin dependencias externas — usa xmlrpc.client de la stdlib.
"""

import xmlrpc.client
import socket
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
