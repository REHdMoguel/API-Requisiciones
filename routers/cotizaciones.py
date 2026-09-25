from fastapi import APIRouter, Depends, Header, HTTPException
from models.cotizacion import (
    AutorizarCotizacionRequest, RechazarCotizacionRequest,
    AutorizarResponse, CotizacionEstado,
    GenerarOCRequest, GenerarOCResponse,
    AprobarYGenerarOCRequest, AprobarYGenerarOCResponse,
)
from services import cotizacion_service
from services import oc_service
from config import settings
from typing import Optional

router = APIRouter(prefix="/cotizaciones", tags=["Cotizaciones"])


# ── Autenticacion simple por API Key ─────────────────────────────────────────

def verificar_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="API Key invalida.")
    return x_api_key


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{folio}/estado",
            response_model=CotizacionEstado,
            summary="Consultar estado de autorizacion de una cotizacion")
def estado(folio: str, _=Depends(verificar_api_key)):
    """
    Devuelve el estado actual de autorizacion de la cotizacion,
    incluyendo que nivel esta pendiente.
    """
    return cotizacion_service.obtener_estado(folio)


@router.get("/pendientes",
            summary="Listar cotizaciones pendientes de autorizacion")
def pendientes(nivel: Optional[int] = None, _=Depends(verificar_api_key)):
    """
    Lista cotizaciones que aun no estan completamente autorizadas.
    - nivel=1 : pendientes de primer autorizador
    - nivel=2 : primer nivel ok, esperando segundo autorizador
    - sin nivel: todas las pendientes
    """
    return cotizacion_service.listar_pendientes(nivel)


@router.post("/autorizar",
             response_model=AutorizarResponse,
             summary="Autorizar nivel 1 o 2 de una cotizacion")
def autorizar(req: AutorizarCotizacionRequest, _=Depends(verificar_api_key)):
    """
    Registra la autorizacion de un nivel de cotizacion.

    - nivel=1: escribe NIVEL_AUT_COT='S', FECHA_AUT_COT, DESCRIP_AUTORIZADO_COT
    - nivel=2: escribe NIVEL_AUT_COT2='S', FECHA_AUT_COT2, DESCRIP_AUTORIZADO_COT2
               y cambia ESTATUS='A' (cotizacion completamente autorizada)

    Validaciones aplicadas:
    - La cotizacion debe existir y ser de TIPO_DOCTO='C'
    - No debe estar cancelada (ESTATUS='C')
    - No se puede autorizar nivel 2 sin que exista nivel 1
    - No se puede re-autorizar un nivel ya aprobado
    """
    return cotizacion_service.autorizar(req)


@router.post("/rechazar",
             response_model=AutorizarResponse,
             summary="Rechazar una cotizacion")
def rechazar(req: RechazarCotizacionRequest, _=Depends(verificar_api_key)):
    """
    Cancela la cotizacion (ESTATUS='C') y registra el motivo en auditoria.
    """
    return cotizacion_service.rechazar(req)


@router.post("/generar-oc",
             response_model=GenerarOCResponse,
             summary="Generar Orden de Compra desde cotizacion autorizada")
def generar_oc(req: GenerarOCRequest, _=Depends(verificar_api_key)):
    """
    Genera una Orden de Compra en a Firebird ERP a partir de una cotización
    completamente autorizada (ESTATUS='A', ambos niveles 'S').

    Inserta en:
    - DOCTOS_CM + DOCTOS_CM_DET (Compras — tabla principal, folio OC#######)
    - DOCTOS_CP (Cuentas por Pagar — tabla secundaria)
    - IMPORTES_DOCTOS_CP (el trigger activa AFECTA_SALDOS_CP)
    - IMPORTES_DOCTOS_CP_IMPTOS (desglose IVA 16%)
    - VENCIMIENTOS_CARGOS_CP (100% al día de hoy)
    - DEMO_DOCTOS_COT_LIGAS (liga cotización -> OC)
    - FOLIOS_COMPRAS (actualiza el consecutivo)

    Validaciones:
    - La cotización debe tener ESTATUS='A'
    - No debe tener ya una OC generada (DEMO_DOCTOS_COT_LIGAS.FOLIO_OCM_DEST)
    """
    return oc_service.generar_oc(req)


@router.post("/aprobar-y-generar-oc",
             response_model=AprobarYGenerarOCResponse,
             summary="[Teams] Autoriza nivel 2 y genera OC en un solo paso")
def aprobar_y_generar_oc(req: AprobarYGenerarOCRequest, _=Depends(verificar_api_key)):
    """
    Endpoint combinado para el flujo de Teams/Approvals.
    Hace TODO en una sola llamada:
      1. Autoriza nivel 2 (si no esta ya autorizado)
      2. Genera la Orden de Compra

    Body de ejemplo:
        {
            "folio_cotizacion": "C00027814",
            "usuario": "JMUNOZ",
            "comentario": "Aprobado desde Teams"
        }
    """
    return oc_service.aprobar_y_generar_oc(req)


# ── Router multi-tenant ──────────────────────────────────────────────────────
# Mismos endpoints, con /{sucursal} para seleccionar BD.
# Usan db_for(sucursal) como dependencia extra.

router_mt = APIRouter(prefix="/cotizaciones/{sucursal}", tags=["Cotizaciones Multi-Tenant"])


def _activar_sucursal(sucursal: str):
    from database import db_for
    return db_for(sucursal)


@router_mt.get("/{folio}/estado", response_model=CotizacionEstado)
def estado_mt(folio: str, sucursal: str, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return cotizacion_service.obtener_estado(folio)


@router_mt.get("/pendientes")
def pendientes_mt(sucursal: str, nivel: Optional[int] = None, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return cotizacion_service.listar_pendientes(nivel)


@router_mt.post("/autorizar", response_model=AutorizarResponse)
def autorizar_mt(req: AutorizarCotizacionRequest, sucursal: str, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return cotizacion_service.autorizar(req)


@router_mt.post("/rechazar", response_model=AutorizarResponse)
def rechazar_mt(req: RechazarCotizacionRequest, sucursal: str, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return cotizacion_service.rechazar(req)


@router_mt.post("/generar-oc", response_model=GenerarOCResponse)
def generar_oc_mt(req: GenerarOCRequest, sucursal: str, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return oc_service.generar_oc(req)


@router_mt.post("/aprobar-y-generar-oc", response_model=AprobarYGenerarOCResponse)
def aprobar_y_generar_oc_mt(req: AprobarYGenerarOCRequest, sucursal: str, _=Depends(verificar_api_key)):
    _activar_sucursal(sucursal)
    return oc_service.aprobar_y_generar_oc(req)
