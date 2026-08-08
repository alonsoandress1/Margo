# -*- coding: utf-8 -*-
"""
Crea un usuario en la plataforma (tabla `usuarios` en Supabase).
Uso principal: crear el primer Administrador para poder empezar a loguearse.

Requiere backend/.env con SUPABASE_URL y SUPABASE_SERVICE_KEY ya configurados.
La contraseña se pide por teclado (getpass) y solo se guarda su hash — nunca
en texto plano, ni en este script, ni en Supabase.

Uso: python -m backend.scripts.crear_usuario
"""
import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend.db import get_db
from backend.security import hash_password

ROLES = ("solicitante", "administrador", "observador")

email = input("Email: ").strip()
nombre = input("Nombre completo: ").strip()
rol = input(f"Rol ({'/'.join(ROLES)}): ").strip().lower()
if rol not in ROLES:
    print(f"Rol inválido. Debe ser uno de: {', '.join(ROLES)}")
    sys.exit(1)

password = getpass.getpass("Contraseña: ")
password2 = getpass.getpass("Repetir contraseña: ")
if password != password2:
    print("Las contraseñas no coinciden.")
    sys.exit(1)

db = get_db()
existe = db.table("usuarios").select("id").eq("email", email).execute()
if existe.data:
    print(f"Ya existe un usuario con el email {email}.")
    sys.exit(1)

db.table("usuarios").insert({
    "email": email,
    "nombre": nombre,
    "rol": rol,
    "password_hash": hash_password(password),
    "activo": True,
}).execute()

print(f"\n✓ Usuario creado: {nombre} <{email}> — rol: {rol}")
