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
    tamano_empaque: float | None = None


class MovimientoIn(BaseModel):
    local_id: str
    ingrediente_key: str
    tipo: str  # ingreso | egreso | ajuste
    cantidad: float
    nota: str | None = None


class MovimientoOut(BaseModel):
    id: str
    local_id: str
    ingrediente_key: str
    tipo: str
    cantidad: float
    nota: str | None = None
    fecha: str
    created_by: str | None = None


class InventarioItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    par: float
    stock_bodega: float


class StockCocinaIn(BaseModel):
    local_id: str
    ingrediente_key: str
    fecha: str | None = None  # default: hoy
    cantidad_informada: float


class MermaItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    cantidad_informada: float | None = None
    fecha: str | None = None


class ProveedorOut(BaseModel):
    id: str
    nombre: str
    odoo_supplier_id: int
    activo: bool


class ProveedorIn(BaseModel):
    nombre: str
    odoo_supplier_id: int


class ProductoOut(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    proveedor_id: str
    odoo_id: int
    odoo_name: str
    ref: str | None = None
    precio: float = 0
    tamano_empaque: float | None = None  # None = a granel


class ProductoIn(BaseModel):
    nombre: str
    unidad: str
    odoo_id: int
    odoo_name: str
    ref: str | None = None
    precio: float = 0
    a_granel: bool = False
    tamano_empaque: float | None = None


class ProductoUpdateIn(BaseModel):
    ingrediente_key: str
    precio: float | None = None
    a_granel: bool = False
    tamano_empaque: float | None = None


class ParStockItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    par_cantidad: float
    odoo_name: str | None = None
    ref: str | None = None
    supplier_name: str | None = None
    precio: float = 0
    tamano_empaque: float | None = None  # None = a granel


class ParStockAddIn(BaseModel):
    local_id: str
    ingrediente_key: str  # debe existir ya en el catalogo de Proveedores
    categoria: str | None = None
    par_cantidad: float


class ParStockUpdateIn(BaseModel):
    local_id: str
    ingrediente_key: str
    par_cantidad: float


class RecetaLineaOut(BaseModel):
    id: str
    local_id: str
    plato_sku: str
    plato_nombre: str
    ingrediente: str
    cantidad: float
    unidad: str


class RecetaLineaIn(BaseModel):
    local_id: str
    plato_sku: str
    plato_nombre: str
    ingrediente: str
    cantidad: float
    unidad: str


class UsuarioAdminOut(BaseModel):
    id: str
    email: str
    nombre: str
    rol: str
    activo: bool
    locales: list[str] = []


class UsuarioCreateIn(BaseModel):
    email: str
    nombre: str
    rol: str
    password: str
    locales: list[str] = []  # solo aplica si rol == solicitante


class UsuarioUpdateIn(BaseModel):
    nombre: str | None = None
    rol: str | None = None
    activo: bool | None = None
    locales: list[str] | None = None
    password: str | None = None  # si viene, resetea la contraseña


class CambiarPasswordIn(BaseModel):
    password_actual: str
    password_nueva: str


class PedidoOut(BaseModel):
    id: str
    local_id: str
    fecha: str
    estado: str
    items: list[dict[str, Any]]
    favorito: bool = False
    creado_por: str | None = None
    revisado_por: str | None = None
    po_id: int | None = None
    po_name: str | None = None


class FavoritoIn(BaseModel):
    favorito: bool


class GenerarOCIn(BaseModel):
    email: str
    password: str


class GenerarOCOut(BaseModel):
    po_id: int
    po_name: str
    omitidos: list[str] = []


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
