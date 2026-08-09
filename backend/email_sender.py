"""Envio de avisos por correo para proveedores sin integracion a Odoo.

Usa smtplib de la libreria estandar -- sin dependencias nuevas, mismo
criterio que el resto del proyecto (ver odoo_connector.py). Las
credenciales SMTP viven solo en variables de entorno (Render), nunca
en la base de datos ni en el chat.
"""
import os
import smtplib
from email.mime.text import MIMEText


def enviar_aviso_pedido(destinatario: str, proveedor: str, local_nombre: str, items: list[dict]) -> None:
    cuerpo_lineas = [f"Pedido para {proveedor} — local {local_nombre}", ""]
    for it in items:
        cuerpo_lineas.append(f"  - {it['ingrediente']}: {it['cantidad']} {it['unidad']}")
    cuerpo = "\n".join(cuerpo_lineas)

    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = f"Pedido {local_nombre}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = destinatario

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [destinatario], msg.as_string())
