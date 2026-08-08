# -*- coding: utf-8 -*-
"""
Crea backend/.env de forma interactiva. Corre esto UNA vez, en tu propia
terminal (no en el chat). Los valores nunca se muestran en pantalla ni se
envian a ningun lado mas que al archivo .env local (que ya esta en
.gitignore, nunca se sube a GitHub).

Necesitas tener a mano, desde Supabase -> Settings -> API:
  - Project URL
  - service_role key (la secreta, NO la "anon public")

Uso: python -m backend.scripts.setup_env
"""
import getpass
import secrets
from pathlib import Path

env_path = Path(__file__).resolve().parents[1] / ".env"

if env_path.exists():
    resp = input(f"{env_path} ya existe. ¿Sobrescribir? (si/no): ").strip().lower()
    if resp not in ("si", "s", "yes", "y"):
        print("Cancelado.")
        raise SystemExit

print("\nDesde Supabase → Settings → API, copia y pega los siguientes valores.\n")

supabase_url = input("SUPABASE_URL (Project URL, ej. https://xxxxx.supabase.co): ").strip()
supabase_key = getpass.getpass("SUPABASE_SERVICE_KEY (service_role, no se muestra en pantalla): ").strip()

jwt_secret = secrets.token_hex(32)  # generado automáticamente, no hace falta pedirlo

contenido = (
    f"SUPABASE_URL={supabase_url}\n"
    f"SUPABASE_SERVICE_KEY={supabase_key}\n"
    f"JWT_SECRET={jwt_secret}\n"
    f"JWT_EXPIRE_MINUTES=480\n"
)
env_path.write_text(contenido, encoding="utf-8")

print(f"\n✓ Archivo creado: {env_path}")
print("  (JWT_SECRET se generó automáticamente — no necesitas guardarlo en ningún lado)")
