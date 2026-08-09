from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import auth, configuracion, inventario, locales, mermas, parstock, pedidos, platos, proveedores, recetas, usuarios

app = FastAPI(title="Margo · Compras — API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # el frontend se sirve desde este mismo servicio
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(locales.router)
app.include_router(pedidos.router)
app.include_router(inventario.router)
app.include_router(mermas.router)
app.include_router(parstock.router)
app.include_router(proveedores.router)
app.include_router(platos.router)
app.include_router(recetas.router)
app.include_router(usuarios.router)
app.include_router(configuracion.router)


@app.get("/health")
def health():
    return {"status": "ok"}


_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
