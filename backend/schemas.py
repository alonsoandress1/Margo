from typing import Any, Literal

from pydantic import BaseModel

UnidadCatalogo = Literal["un", "kg", "porcion"]


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
    fecha: str | None = None  # default: ayer
    cantidad_informada: float
    mermas_total: float | None = None
    entrega: float | None = None  # solo si el insumo se entrega directo de Bodega (no producido en Cocina)


class MermaItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    cantidad_informada: float | None = None
    mermas_total: float | None = None
    fecha: str | None = None
    stock_inicial: float = 0
    entregas: float = 0
    entregas_editable: bool = True  # false si las Entregas del dia vienen de Produccion de Cocina
    ventas: float = 0
    precio: float = 0


class ProduccionIn(BaseModel):
    local_id: str
    fecha: str
    materia_prima_nombre: str | None = None
    materia_prima_cantidad: float | None = None
    producto_key: str
    producto_nombre: str
    cantidad_producida: float
    mermas: float | None = None


class ProduccionOut(BaseModel):
    id: str
    local_id: str
    fecha: str
    materia_prima_nombre: str | None = None
    materia_prima_cantidad: float | None = None
    producto_key: str
    producto_nombre: str
    cantidad_producida: float
    mermas: float | None = None


class ProveedorOut(BaseModel):
    id: str
    nombre: str
    odoo_supplier_id: int
    usa_odoo: bool
    activo: bool


class ProveedorIn(BaseModel):
    nombre: str
    odoo_supplier_id: int
    usa_odoo: bool = False


class ProductoOut(BaseModel):
    id: str
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
    unidad: UnidadCatalogo
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


class ConfiguracionEmailOut(BaseModel):
    destinatario: str
    cc: str | None = None  # direcciones adicionales separadas por coma


class ConfiguracionEmailIn(BaseModel):
    destinatario: str
    cc: str | None = None


class AccionCompra(BaseModel):
    proveedor: str
    tipo: str  # odoo | email
    po_id: int | None = None
    po_name: str | None = None
    aviso: str | None = None  # ej. advertencia si el PDF de la OC no se pudo enviar


class ParStockItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    par_cantidad: float
    odoo_name: str | None = None
    ref: str | None = None
    supplier_name: str | None = None
    proveedor_id: str | None = None
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


class PlatoOut(BaseModel):
    id: str
    local_id: str
    sku: str
    nombre: str


class PlatoIn(BaseModel):
    local_id: str
    sku: str
    nombre: str


class RecetaLineaOut(BaseModel):
    id: str
    plato_id: str
    plato_sku: str
    plato_nombre: str
    ingrediente_key: str | None = None
    ingrediente: str
    cantidad: float
    unidad: str


class RecetaLineaIn(BaseModel):
    plato_id: str
    ingrediente_key: str | None = None
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
    acciones: list[AccionCompra] = []


class FavoritoIn(BaseModel):
    favorito: bool


class GenerarOCIn(BaseModel):
    email: str | None = None
    password: str | None = None


class GenerarOCOut(BaseModel):
    acciones: list[AccionCompra]
    omitidos: list[str] = []


class FacturasBuscarIn(BaseModel):
    email: str
    password: str


class FacturaLineaPreview(BaseModel):
    ingrediente_key: str | None = None
    nombre: str
    cantidad: float
    reconocido: bool


class FacturaPreview(BaseModel):
    odoo_invoice_id: int
    odoo_invoice_name: str
    proveedor: str
    fecha: str | None = None
    total: float = 0
    lineas: list[FacturaLineaPreview] = []


class FacturaAceptarIn(BaseModel):
    odoo_invoice_id: int
    odoo_invoice_name: str
    proveedor: str
    local_id: str
    lineas: list[FacturaLineaPreview]


class FacturaTrackingOut(BaseModel):
    id: str
    odoo_invoice_id: int
    odoo_invoice_name: str
    proveedor: str
    local_id: str | None = None
    pedido_id: str | None = None
    items: list[dict] = []
    procesada_en: str


class PlanillaHojasOut(BaseModel):
    hojas: list[str]


class PlanillaVentaPreview(BaseModel):
    codigo: str
    nombre: str
    cantidad: float
    plato_id: str | None = None
    reconocido: bool


class PlanillaInsumoPreview(BaseModel):
    nombre: str
    ingrediente_key: str | None = None
    stock_informado: float | None = None
    mermas_desglose: dict[str, float] = {}
    entrega_cantidad: float = 0
    reconocido: bool


class PlanillaPreviewOut(BaseModel):
    ventas: list[PlanillaVentaPreview]
    insumos: list[PlanillaInsumoPreview]


class PlanillaConfirmarIn(BaseModel):
    local_id: str
    fecha: str  # YYYY-MM-DD
    ventas: list[PlanillaVentaPreview]
    insumos: list[PlanillaInsumoPreview]


class PlanillaConfirmarOut(BaseModel):
    ventas_guardadas: int
    insumos_guardados: int
    entregas_registradas: int


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
