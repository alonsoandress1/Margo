"""Envio de avisos por correo para proveedores sin integracion a Odoo.

Usa la API HTTP de Resend (https://resend.com) en vez de SMTP directo:
Render (y varios proveedores cloud) bloquean las conexiones salientes
por SMTP en el plan gratuito, pero HTTPS siempre funciona. Sin
dependencias nuevas -- urllib de la libreria estandar, mismo criterio
que odoo_connector.py.

La API key vive solo en la variable de entorno RESEND_API_KEY (Render),
nunca en la base de datos ni en el chat.
"""
import json
import os
import urllib.error
import urllib.request


def enviar_aviso_pedido(destinatario: str, proveedor: str, local_nombre: str, items: list[dict]) -> None:
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
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend devolvió {e.code}: {detalle}") from e
