from database import get_db
from models.cotizacion import (
    AutorizarCotizacionRequest, RechazarCotizacionRequest,
    AutorizarResponse, CotizacionEstado,
)
from fastapi import HTTPException
from utils import normalizar_folio
import logging

log = logging.getLogger(__name__)


# ── Helpers internos ──────────────────────────────────────────────────────────

def _row_as_dict(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return {d[0]: v for d, v in zip(cur.description, row)}


def _obtener_cotizacion(cur, folio: str) -> dict:
    folio = normalizar_folio(folio)
    cur.execute("""
        SELECT
            r.DOCTO_RQ_ID, TRIM(r.FOLIO)      AS FOLIO,
            r.FECHA,       r.ESTATUS,
            r.NIVEL_AUT_COT,  r.FECHA_AUT_COT,  r.DESCRIP_AUTORIZADO_COT,
            r.NIVEL_AUT_COT2, r.FECHA_AUT_COT2, r.DESCRIP_AUTORIZADO_COT2,
            r.NIVEL_AUT_COT3,
            r.PROVEEDOR_ID,   TRIM(r.CLAVE_PROV) AS CLAVE_PROV,
            r.DEPARTAMENTO_ID, r.DESCRIPCION,
            r.USUARIO_ULT_MODIF, r.FECHA_HORA_ULT_MODIF
        FROM DEMO_DOCTOS_RQ r
        WHERE TRIM(r.FOLIO) = ? AND r.TIPO_DOCTO = 'C'
    """, [folio])
    row = _row_as_dict(cur)
    if not row:
        raise HTTPException(status_code=404,
                            detail=f"Cotizacion '{folio}' no encontrada.")
    return row


# ── Servicio principal ────────────────────────────────────────────────────────

def obtener_estado(folio: str) -> CotizacionEstado:
    with get_db() as conn:
        cur = conn.cursor()
        cot = _obtener_cotizacion(cur, folio)

        # Nombre de departamento
        depto = None
        if cot["DEPARTAMENTO_ID"]:
            cur.execute("SELECT NOMBRE FROM DEMO_DEPARTAMENTOS WHERE DEPARTAMENTO_ID=?",
                        [cot["DEPARTAMENTO_ID"]])
            d = cur.fetchone()
            depto = d[0] if d else None

        # Nivel pendiente
        if cot["NIVEL_AUT_COT"] != "S":
            nivel_pendiente = 1
        elif cot["NIVEL_AUT_COT2"] != "S":
            nivel_pendiente = 2
        else:
            nivel_pendiente = None   # completamente autorizada

        def ts(v):
            return str(v) if v else None

        return CotizacionEstado(
            docto_rq_id      = cot["DOCTO_RQ_ID"],
            folio            = cot["FOLIO"],
            fecha            = ts(cot["FECHA"]),
            estatus          = cot["ESTATUS"],
            departamento     = depto,
            proveedor_clave  = cot["CLAVE_PROV"],
            descripcion      = cot["DESCRIPCION"],
            nivel_aut_cot    = cot["NIVEL_AUT_COT"],
            fecha_aut_cot    = ts(cot["FECHA_AUT_COT"]),
            descrip_aut_cot  = cot["DESCRIP_AUTORIZADO_COT"],
            nivel_aut_cot2   = cot["NIVEL_AUT_COT2"],
            fecha_aut_cot2   = ts(cot["FECHA_AUT_COT2"]),
            descrip_aut_cot2 = cot["DESCRIP_AUTORIZADO_COT2"],
            nivel_pendiente  = nivel_pendiente,
        )


def autorizar(req: AutorizarCotizacionRequest) -> AutorizarResponse:
    with get_db() as conn:
        cur = conn.cursor()
        cot = _obtener_cotizacion(cur, req.folio_cotizacion)
        docto_id = cot["DOCTO_RQ_ID"]

        # ── Validaciones ──────────────────────────────────────────────────────
        if cot["ESTATUS"] == "C":
            raise HTTPException(status_code=400,
                                detail="La cotizacion esta cancelada.")

        if req.nivel == 1:
            if cot["NIVEL_AUT_COT"] == "S":
                raise HTTPException(status_code=400,
                                    detail="El nivel 1 ya fue autorizado por "
                                           f"{cot['DESCRIP_AUTORIZADO_COT']}.")
            # ── UPDATE nivel 1 ────────────────────────────────────────────────
            cur.execute("""
                UPDATE DEMO_DOCTOS_RQ SET
                    NIVEL_AUT_COT          = 'S',
                    FECHA_AUT_COT          = CURRENT_TIMESTAMP,
                    DESCRIP_AUTORIZADO_COT = ?,
                    USUARIO_ULT_MODIF      = ?,
                    FECHA_HORA_ULT_MODIF   = CURRENT_TIMESTAMP
                WHERE DOCTO_RQ_ID = ?
            """, [req.usuario, req.usuario, docto_id])

            _insertar_notificacion(cur, docto_id, req.usuario, "AC1",
                                   req.folio_cotizacion, 1, req.comentario)
            log.info("Cotizacion %s autorizada nivel 1 por %s",
                     req.folio_cotizacion, req.usuario)

            return AutorizarResponse(
                ok=True,
                mensaje=f"Nivel 1 autorizado correctamente.",
                folio=req.folio_cotizacion,
                nivel_autorizado=1,
                completamente_autorizada=False,
                estatus_nuevo="N",
            )

        elif req.nivel == 2:
            if cot["NIVEL_AUT_COT"] != "S":
                raise HTTPException(status_code=400,
                                    detail="El nivel 1 aun no ha sido autorizado.")
            if cot["NIVEL_AUT_COT2"] == "S":
                raise HTTPException(status_code=400,
                                    detail="El nivel 2 ya fue autorizado por "
                                           f"{cot['DESCRIP_AUTORIZADO_COT2']}.")
            # ── UPDATE nivel 2 -> cambia ESTATUS a 'A' ────────────────────────
            cur.execute("""
                UPDATE DEMO_DOCTOS_RQ SET
                    NIVEL_AUT_COT2          = 'S',
                    FECHA_AUT_COT2          = CURRENT_TIMESTAMP,
                    DESCRIP_AUTORIZADO_COT2 = ?,
                    ESTATUS                 = 'A',
                    USUARIO_ULT_MODIF       = ?,
                    FECHA_HORA_ULT_MODIF    = CURRENT_TIMESTAMP
                WHERE DOCTO_RQ_ID = ?
            """, [req.usuario, req.usuario, docto_id])

            _insertar_notificacion(cur, docto_id, req.usuario, "AC2",
                                   req.folio_cotizacion, 2, req.comentario)
            log.info("Cotizacion %s autorizada nivel 2 por %s -> ESTATUS=A",
                     req.folio_cotizacion, req.usuario)

            return AutorizarResponse(
                ok=True,
                mensaje="Nivel 2 autorizado. Cotizacion completamente autorizada.",
                folio=req.folio_cotizacion,
                nivel_autorizado=2,
                completamente_autorizada=True,
                estatus_nuevo="A",
            )

        else:
            raise HTTPException(status_code=400,
                                detail="Nivel invalido. Solo se usan niveles 1 y 2.")


def rechazar(req: RechazarCotizacionRequest) -> AutorizarResponse:
    with get_db() as conn:
        cur = conn.cursor()
        cot = _obtener_cotizacion(cur, req.folio_cotizacion)
        docto_id = cot["DOCTO_RQ_ID"]

        if cot["ESTATUS"] == "C":
            raise HTTPException(status_code=400,
                                detail="La cotizacion ya esta cancelada.")

        cur.execute("""
            UPDATE DEMO_DOCTOS_RQ SET
                ESTATUS              = 'C',
                USUARIO_ULT_MODIF    = ?,
                FECHA_HORA_ULT_MODIF = CURRENT_TIMESTAMP
            WHERE DOCTO_RQ_ID = ?
        """, [req.usuario, docto_id])

        _insertar_notificacion(cur, docto_id, req.usuario, "RECHAZO",
                               req.folio_cotizacion, None, req.motivo)
        log.info("Cotizacion %s RECHAZADA por %s: %s",
                 req.folio_cotizacion, req.usuario, req.motivo)

        return AutorizarResponse(
            ok=True,
            mensaje=f"Cotizacion rechazada. Motivo: {req.motivo}",
            folio=req.folio_cotizacion,
            nivel_autorizado=None,
            completamente_autorizada=False,
            estatus_nuevo="C",
        )


def listar_pendientes(nivel: int = None) -> list:
    """Retorna cotizaciones pendientes de autorizacion."""
    with get_db() as conn:
        cur = conn.cursor()

        if nivel == 1:
            where = "r.NIVEL_AUT_COT <> 'S' AND r.ESTATUS <> 'C'"
        elif nivel == 2:
            where = "r.NIVEL_AUT_COT = 'S' AND r.NIVEL_AUT_COT2 <> 'S' AND r.ESTATUS <> 'C'"
        else:
            where = "(r.NIVEL_AUT_COT <> 'S' OR r.NIVEL_AUT_COT2 <> 'S') AND r.ESTATUS <> 'C'"

        cur.execute(f"""
            SELECT
                r.DOCTO_RQ_ID,
                TRIM(r.FOLIO)           AS FOLIO,
                r.FECHA,
                r.ESTATUS,
                TRIM(d.NOMBRE)          AS DEPARTAMENTO,
                TRIM(r.CLAVE_PROV)      AS PROVEEDOR,
                r.DESCRIPCION,
                r.NIVEL_AUT_COT,
                r.NIVEL_AUT_COT2
            FROM DEMO_DOCTOS_RQ r
            LEFT JOIN DEMO_DEPARTAMENTOS d ON d.DEPARTAMENTO_ID = r.DEPARTAMENTO_ID
            WHERE r.TIPO_DOCTO = 'C' AND {where}
            ORDER BY r.FECHA DESC
            ROWS 100
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── Notificaciones (auditoria) ────────────────────────────────────────────────

def _insertar_notificacion(cur, docto_id: int, usuario: str, tipo_evento: str,
                           folio: str, nivel: int | None, comentario: str | None):
    """Inserta registro en DEMO_NOTIFICACIONES para auditoria."""
    try:
        mensaje = f"Autorizacion via API Gateway\nFolio: {folio}"
        if nivel:
            mensaje += f"\nNivel: {nivel}"
        if comentario:
            mensaje += f"\nComentario: {comentario}"

        cur.execute("""
            INSERT INTO DEMO_NOTIFICACIONES
                (NOTIFICACION_ID, DOCTO_ID, USUARIO, FECHA_HORA_ENVIO,
                 MENSAJE, TIPO_EVENTO, SELECCION)
            VALUES (GEN_ID(GEN_DEMO_NOTIFICACIONES, 1), ?, ?,
                    CURRENT_TIMESTAMP, ?, ?, 'S')
        """, [docto_id, usuario, mensaje, tipo_evento])
    except Exception as e:
        # No bloqueamos la autorizacion si falla la notificacion
        log.warning("No se pudo insertar notificacion: %s", e)
