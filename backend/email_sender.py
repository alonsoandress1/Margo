"""Envio de avisos por correo para proveedores sin integracion a Odoo.

Usa la API HTTP de Resend (https://resend.com) en vez de SMTP directo:
Render (y varios proveedores cloud) bloquean las conexiones salientes
por SMTP en el plan gratuito, pero HTTPS siempre funciona. Sin
dependencias nuevas -- urllib de la libreria estandar, mismo criterio
que odoo_connector.py.

La API key vive solo en la variable de entorno RESEND_API_KEY (Render),
nunca en la base de datos ni en el chat.
"""
import base64
import json
import os
import urllib.error
import urllib.request


def _enviar(payload: dict) -> None:
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
            # el User-Agent por defecto de urllib ("Python-urllib/x.y") queda
            # bloqueado por las reglas anti-bot de Cloudflare frente a Resend
            "User-Agent": "MargoCompras/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend devolvió {e.code}: {detalle}") from e


def enviar_aviso_pedido(destinatario: str, proveedor: str, local_nombre: str, items: list[dict],
                         cc: list[str] | None = None) -> None:
    cuerpo_lineas = [f"Pedido para {proveedor} — local {local_nombre}", ""]
    for it in items:
        cuerpo_lineas.append(f"  - {it['ingrediente']}: {it['cantidad']} {it['unidad']}")
    cuerpo = "\n".join(cuerpo_lineas)

    payload = {
        "from": "Margo Compras <onboarding@resend.dev>",
        "to": [destinatario],
        "subject": f"Pedido {local_nombre}",
        "text": cuerpo,
    }
    if cc:
        payload["cc"] = cc
    _enviar(payload)


def enviar_oc_pdf(destinatario: str, proveedor: str, local_nombre: str, po_name: str,
                   pdf_bytes: bytes, cc: list[str] | None = None) -> None:
    """Envia la Orden de Compra ya creada en Odoo como PDF adjunto."""
    payload = {
        "from": "Margo Compras <onboarding@resend.dev>",
        "to": [destinatario],
        "subject": f"Pedido {local_nombre}",
        "text": f"Orden de Compra {po_name} generada en Odoo para {proveedor} — local {local_nombre}. Se adjunta el PDF.",
        "attachments": [{
            "filename": f"{po_name}.pdf",
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
        }],
    }
    if cc:
        payload["cc"] = cc
    _enviar(payload)
