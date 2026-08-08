from typing import Any

from pydantic import BaseModel


class LocalOut(BaseModel):
    id: str
    nombre: str
    activo: bool


class PedidoIn(BaseModel):
    local_id: str
    items: list[dict[str, Any]]


class PedidoEstadoIn(BaseModel):
    estado: str  # aprobado | rechazado | editado
    items: list[dict[str, Any]] | None = None  # solo si estado == editado


class SugerenciaItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    par: float
    stock_bodega: float
    stock_cocina: float
    sugerido: float
    precio: float = 0
    proveedor: str | None = None


class PedidoOut(BaseModel):
    id: str
    local_id: str
    fecha: str
    estado: str
    items: list[dict[str, Any]]
    creado_por: str | None = None
    revisado_por: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: "UsuarioOut"


class UsuarioOut(BaseModel):
    id: str
    email: str
    nombre: str
    rol: str
    locales: list[str] = []


LoginResponse.model_rebuild()
