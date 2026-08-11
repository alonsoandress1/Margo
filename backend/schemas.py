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
    """Bloque 'Control de Stock' -- Stock Informado va junto al desglose de
    Mermas por causa, igual que en la planilla real (no son cosas separadas).
    mermas_reutilizar solo aplica a insumos del tramo 'kg'."""
    local_id: str
    ingrediente_key: str
    fecha: str | None = None  # default: ayer
    cantidad_informada: float
    mermas_produccion: float | None = None
    mermas_defectuosos: float | None = None
    mermas_clientes: float | None = None
    mermas_cortesia: float | None = None
    mermas_reutilizar: float | None = None


class MermaItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    categoria: str | None = None
    tramo: str = "kg"  # 'kg' (tiene Reutilizar) o 'unidades' (no tiene) -- igual que el Excel
    cantidad_informada: float | None = None
    mermas_total: float | None = None  # SIEMPRE calculado (suma del desglose) -- solo lectura en la tabla resumen
    mermas_produccion: float | None = None
    mermas_defectuosos: float | None = None
    mermas_clientes: float | None = None
    mermas_cortesia: float | None = None
    mermas_reutilizar: float | None = None
    fecha: str | None = None
    stock_inicial: float = 0
    entregas: float = 0  # total del dia (bodega + produccion) -- SIEMPRE calculado, igual que en la planilla real
    entrega_bodega: float = 0  # solo la parte entregada por Bodega -- para prellenar el bloque "Entregas a Cocina"
    ventas: float = 0
    precio: float = 0


class EntregaIn(BaseModel):
    local_id: str
    ingrediente_key: str
    fecha: str
    cantidad: float


class ResumenDiferenciaItem(BaseModel):
    ingrediente_key: str
    nombre: str
    unidad: str
    diferencia_total: float
    precio: float
    total_dscto: float  # diferencia_total * precio, solo si diferencia_total es negativa (faltante) -- igual que el Excel


class ProteinaProduccionOut(BaseModel):
    receta_id: str
    orden: int
    materia_prima_nombre: str
    materia_prima_unidad: str
    producto_final_nombre: str | None = None
    producto_final_unidad: str | None = None
    cantidad_consumida: float | None = None
    cantidad_producida: float | None = None
    mermas: float | None = None


class ProteinaProduccionIn(BaseModel):
    local_id: str
    receta_id: str
    fecha: str
    cantidad_consumida: float | None = None
    cantidad_producida: float | None = None
    mermas: float | None = None


class PasteleriaOut(BaseModel):
    producto_key: str
    producto_nombre: str
    unidad: str
    cantidad_producida: float | None = None


class PasteleriaIn(BaseModel):
    local_id: str
    producto_key: str
    fecha: str
    cantidad_producida: float | None = None


class ChocolateOut(BaseModel):
    producto_key: str
    producto_nombre: str
    unidad: str
    cantidad_entregada: float | None = None
    cantidad_utilizada: float | None = None


class ChocolateIn(BaseModel):
    local_id: str
    producto_key: str
    fecha: str
    cantidad_entregada: float | None = None
    cantidad_utilizada: float | None = None


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


class DteLineaOut(BaseModel):
    id: int
    item_name: str
    qty: float
    codigo_tipo: str | None = None
    codigo_valor: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    sugerido: bool = False  # True si el product_id vino de nuestro mapeo aprendido, no de Odoo


class DteOut(BaseModel):
    id: int
    proveedor_rut: str
    proveedor_nombre: str
    folio: str
    fecha: str | None = None
    tiene_factura: bool = False


class DteDetalleOut(DteOut):
    lineas: list[DteLineaOut]


class DteMatchLineaIn(BaseModel):
    dte_id: int
    line_id: int
    codigo_tipo: str | None = None
    codigo_valor: str | None = None
    odoo_product_id: int
    odoo_product_name: str
    proveedor_rut: str
    proveedor_nombre: str


class DteProductoOut(BaseModel):
    id: int
    name: str
    default_code: str | None = None
    uom: str | None = None


class DteCrearFacturaOut(BaseModel):
    invoice_id: int
    invoice_name: str
