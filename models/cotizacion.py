from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# ── Peticiones entrantes ──────────────────────────────────────────────────────

class AutorizarCotizacionRequest(BaseModel):
    folio_cotizacion : str   = Field(..., description="Folio de la cotizacion, ej: C00027814")
    usuario          : str   = Field(..., description="Usuario que autoriza, ej: JMUNOZ")
    nivel            : int   = Field(..., ge=1, le=2, description="Nivel a autorizar: 1 o 2")
    comentario       : Optional[str] = Field(None, description="Comentario opcional del autorizador")

class RechazarCotizacionRequest(BaseModel):
    folio_cotizacion : str   = Field(..., description="Folio de la cotizacion")
    usuario          : str   = Field(..., description="Usuario que rechaza")
    motivo           : str   = Field(..., description="Motivo del rechazo")

# ── Respuestas ────────────────────────────────────────────────────────────────

class CotizacionEstado(BaseModel):
    docto_rq_id          : int
    folio                : str
    fecha                : Optional[str]
    estatus              : Optional[str]
    departamento         : Optional[str]
    proveedor_clave      : Optional[str]
    descripcion          : Optional[str]
    nivel_aut_cot        : Optional[str]
    fecha_aut_cot        : Optional[str]
    descrip_aut_cot      : Optional[str]
    nivel_aut_cot2       : Optional[str]
    fecha_aut_cot2       : Optional[str]
    descrip_aut_cot2     : Optional[str]
    nivel_pendiente      : Optional[int]   # 1, 2, o None si ya esta completa

class AutorizarResponse(BaseModel):
    ok                   : bool
    mensaje              : str
    folio                : str
    nivel_autorizado     : Optional[int]
    completamente_autorizada : bool
    estatus_nuevo        : Optional[str]

class ErrorResponse(BaseModel):
    ok      : bool = False
    mensaje : str
    detalle : Optional[str] = None


# ── Generacion de OC ──────────────────────────────────────────────────────────

class GenerarOCRequest(BaseModel):
    folio_cotizacion : str            = Field(..., description="Folio cotizacion completamente autorizada, ej: C00027814")
    usuario          : str            = Field(..., description="Usuario que genera la OC, ej: JMUNOZ")
    comentario       : Optional[str]  = Field(None, description="Comentario opcional")

class GenerarOCResponse(BaseModel):
    ok               : bool
    mensaje          : str
    folio_cotizacion : str
    folio_oc         : str
    docto_cp_id      : int
    importe          : float   # subtotal sin IVA
    impuesto         : float   # IVA 16%
    total            : float   # importe + impuesto


# ── Endpoint combinado: aprobar y generar OC ──────────────────────────────────

class AprobarYGenerarOCRequest(BaseModel):
    folio_cotizacion : str            = Field(..., description="Folio de la cotizacion, ej: C00027814")
    usuario          : str            = Field(..., description="Usuario que autoriza nivel 2 y genera la OC")
    comentario       : Optional[str]  = Field(None, description="Comentario opcional")

class AprobarYGenerarOCResponse(BaseModel):
    ok                  : bool
    mensaje             : str
    folio_cotizacion    : str
    folio_oc            : str
    docto_cp_id         : int
    importe             : float
    impuesto            : float
    total               : float
    autorizado_por      : str
    completamente_autorizada : bool
