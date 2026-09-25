import logging
import re
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from database import get_db
from models.cotizacion import GenerarOCRequest, GenerarOCResponse
from utils import normalizar_folio

log = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────────────────────

CONCEPTO_CP_ID = 51          # "Compra"
SUCURSAL_ID = 42793
NATURALEZA_CONCEPTO = "C"
SISTEMA_ORIGEN = "CM"
MONEDA_ID = 1
TIPO_CAMBIO = Decimal("1")
VIA_EMBARQUE_ID = 47787
IMPUESTO_ID = 632           # IVA 16%
FOLIO_OC_REGEX = re.compile(r"^OC\d{7}$")
COND_PAGO_ID_DEFAULT = 15926


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_as_dict(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return {d[0]: v for d, v in zip(cur.description, row)}


def _folio_requisicion(cur, docto_rq_id: int) -> Optional[str]:
    """Obtiene el folio de la requisicion origen de una cotizacion."""
    cur.execute(
        "SELECT FIRST 1 TRIM(r.FOLIO) "
        "FROM DEMO_DOCTOS_RQ r "
        "INNER JOIN DEMO_DOCTOS_RQ_LIGAS l ON l.DOCTO_RQ_FTE_ID = r.DOCTO_RQ_ID "
        "WHERE l.DOCTO_RQ_DEST_ID = ? AND r.TIPO_DOCTO = 'R'",
        (docto_rq_id,),
    )
    row = cur.fetchone()
    return str(row[0]).strip() if row and row[0] else None


def _siguiente_folio_oc(cur) -> str:
    """Siguiente folio OC desde DOCTOS_CM (tabla principal de Compras)."""
    cur.execute(
        "SELECT FOLIO FROM DOCTOS_CM "
        "WHERE TIPO_DOCTO = 'O' AND FOLIO SIMILAR TO 'OC[0-9]{7}' "
        "ORDER BY FOLIO DESC ROWS 1"
    )
    row = cur.fetchone()
    if row and row[0]:
        max_folio = row[0].strip()
        if FOLIO_OC_REGEX.match(max_folio):
            num = int(max_folio[2:]) + 1
            return f"OC{num:07d}"
    # Fallback: usar FOLIOS_COMPRAS
    cur.execute(
        "SELECT CONSECUTIVO FROM FOLIOS_COMPRAS "
        "WHERE TIPO_DOCTO = 'O' AND SERIE = 'OC' AND SUCURSAL_ID = ?",
        (SUCURSAL_ID,),
    )
    row = cur.fetchone()
    if row and row[0]:
        return f"OC{int(row[0]):07d}"
    return "OC0000001"


def _almacen_id(cur) -> int:
    """Obtiene el almacen de la OC mas reciente."""
    cur.execute(
        "SELECT FIRST 1 ALMACEN_ID FROM DOCTOS_CM "
        "WHERE TIPO_DOCTO = 'O' AND SUCURSAL_ID = ? "
        "ORDER BY DOCTO_CM_ID DESC",
        (SUCURSAL_ID,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else 1


# ── Funcion interna compartida: inserts de OC ─────────────────────────────────

def _insertar_oc(cur, docto_rq_id: int, proveedor_id, clave_prov: str,
                 cond_pago_id: int, folio_cot: str, descripcion: str,
                 usuario: str) -> dict:
    """
    Ejecuta los 8 inserts necesarios para generar una OC.
    Debe llamarse dentro de una transaccion ya abierta.
    Retorna dict con folio_oc, docto_cp_id, importe, impuesto, total.
    """
    # Folio requisicion
    folio_req = _folio_requisicion(cur, docto_rq_id)

    # Subtotal e IVA desde detalle (CAST para compatibilidad FB5)
    cur.execute(
        "SELECT CAST(SUM(PRECIO_TOTAL_NETO) AS DOUBLE PRECISION) FROM DEMO_DOCTOS_RQ_DET "
        "WHERE DOCTO_RQ_ID = ?",
        (docto_rq_id,),
    )
    total_row = cur.fetchone()
    importe_total = float(total_row[0] or Decimal("0"))
    impuesto = round(importe_total * 0.16, 2)

    if importe_total <= 0:
        raise HTTPException(400, "La cotizacion no tiene detalle o el importe es cero.")

    # Fecha de entrega desde el detalle
    cur.execute(
        "SELECT FIRST 1 FECHA_ENTREGA FROM DEMO_DOCTOS_RQ_DET "
        "WHERE DOCTO_RQ_ID = ?",
        (docto_rq_id,),
    )
    fecha_entrega = cur.fetchone()[0]

    # Folio OC
    folio_oc = _siguiente_folio_oc(cur)

    # Almacen
    almacen_id = _almacen_id(cur)

    # Descripcion (max 200 chars)
    desc_base = (descripcion or "").strip()
    partes = [desc_base] if desc_base else []
    if folio_req:
        partes.append(f"Req: {folio_req}")
    partes.append(f"Cot: {folio_cot}")
    desc_final = " ".join(partes)[:200]

    # ══ INSERTS ═══════════════════════════════════════════════════════════════

    # 1. DOCTOS_CM (Compras)
    cur.execute(
        "INSERT INTO DOCTOS_CM ("
        "  DOCTO_CM_ID, TIPO_DOCTO, SUCURSAL_ID, FOLIO, FECHA, "
        "  CLAVE_PROV, PROVEEDOR_ID, ALMACEN_ID, MONEDA_ID, "
        "  TIPO_CAMBIO, TIPO_DSCTO, ESTATUS, APLICADO, FECHA_ENTREGA, "
        "  DESCRIPCION, IMPORTE_NETO, TOTAL_IMPUESTOS, "
        "  SISTEMA_ORIGEN, FORMA_EMITIDA, CONTABILIZADO, "
        "  COND_PAGO_ID, VIA_EMBARQUE_ID, CARGAR_SUN, ENVIADO, "
        "  USUARIO_CREADOR, FECHA_HORA_CREACION, "
        "  USUARIO_ULT_MODIF, FECHA_HORA_ULT_MODIF, GEN_X_CFDI"
        ") VALUES ("
        "  -1, 'O', ?, ?, CURRENT_DATE,"
        "  ?, ?, ?, ?,"
        "  ?, 'P', 'P', 'S', ?,"
        "  ?, ?, ?,"
        "  'CM', 'N', 'N',"
        "  ?, ?, 'S', 'N',"
        "  ?, CURRENT_TIMESTAMP,"
        "  ?, CURRENT_TIMESTAMP, False"
        ")",
        (SUCURSAL_ID, folio_oc,
         clave_prov, proveedor_id, almacen_id, MONEDA_ID,
         TIPO_CAMBIO, fecha_entrega,
         desc_final, importe_total, impuesto,
         cond_pago_id, VIA_EMBARQUE_ID,
         usuario, usuario),
    )

    cur.execute("SELECT GEN_ID(ID_DOCTOS, 0) FROM RDB$DATABASE")
    docto_cm_id = cur.fetchone()[0]

    # 2. DOCTOS_CM_DET (lineas)
    cur.execute(
        "SELECT CLAVE_ARTICULO, ARTICULO_ID, CANTIDAD, PRECIO_UNITARIO, "
        "       PRECIO_TOTAL_NETO, DESCRIPCION_ARTICULO, POSICION "
        "FROM DEMO_DOCTOS_RQ_DET "
        "WHERE DOCTO_RQ_ID = ? ORDER BY POSICION",
        (docto_rq_id,),
    )
    lineas = 0
    for det in cur.fetchall():
        art_clave = det[0] or ""
        art_id = det[1] or 0
        cant = float(det[2] or 0)
        precio_u = float(det[3] or 0)
        precio_t = float(det[4] or 0)
        notas = (det[5] or "")[:100]
        pos = det[6] or (lineas + 1)

        cur.execute(
            "INSERT INTO DOCTOS_CM_DET ("
            "  DOCTO_CM_DET_ID, DOCTO_CM_ID, CLAVE_ARTICULO, ARTICULO_ID, "
            "  UNIDADES, UNIDADES_REC_DEV, UNIDADES_A_REC, UMED, CONTENIDO_UMED, "
            "  PRECIO_UNITARIO, PRECIO_TOTAL_NETO, "
            "  PCTJE_DSCTO, PCTJE_DSCTO_PRO, PCTJE_DSCTO_VOL, PCTJE_DSCTO_PROMO, "
            "  DSCTO_ART, DSCTO_EXTRA, PCTJE_ARANCEL, NOTAS, POSICION"
            ") VALUES ("
            "  -1, ?, ?, ?,"
            "  ?, ?, ?, 'PIEZA', 1,"
            "  ?, ?,"
            "  0, 0, 0, 0, 0, 0, 0, ?, ?"
            ")",
            (docto_cm_id, art_clave, art_id,
             cant, cant, cant,
             precio_u, precio_t,
             notas, pos),
        )
        lineas += 1

    # 3. DOCTOS_CP (Cuentas por Pagar)
    cur.execute(
        "INSERT INTO DOCTOS_CP ("
        "  DOCTO_CP_ID, CONCEPTO_CP_ID, SUCURSAL_ID, NATURALEZA_CONCEPTO, "
        "  SISTEMA_ORIGEN, INTEG_BA, CONTABILIZADO_BA, GEN_X_CFDI, "
        "  FOLIO, FECHA, CLAVE_PROV, PROVEEDOR_ID, COND_PAGO_ID, "
        "  CANCELADO, APLICADO, DESCRIPCION, "
        "  USUARIO_CREADOR, FECHA_HORA_CREACION, "
        "  USUARIO_ULT_MODIF, FECHA_HORA_ULT_MODIF"
        ") VALUES ("
        "  -1, ?, ?, ?,"
        "  'CM', 'N', 'N', False,"
        "  ?, CURRENT_DATE, ?, ?, ?,"
        "  'N', 'S', ?,"
        "  ?, CURRENT_TIMESTAMP,"
        "  ?, CURRENT_TIMESTAMP"
        ")",
        (CONCEPTO_CP_ID, SUCURSAL_ID, NATURALEZA_CONCEPTO,
         folio_oc, clave_prov, proveedor_id, cond_pago_id,
         desc_final,
         usuario, usuario),
    )

    cur.execute("SELECT GEN_ID(ID_DOCTOS, 0) FROM RDB$DATABASE")
    docto_cp_id = cur.fetchone()[0]

    # 4. IMPORTES_DOCTOS_CP
    cur.execute(
        "INSERT INTO IMPORTES_DOCTOS_CP ("
        "  IMPTE_DOCTO_CP_ID, DOCTO_CP_ID, CANCELADO, APLICADO, "
        "  TIPO_IMPTE, DOCTO_CP_ACR_ID, "
        "  IMPORTE, IMPUESTO, IVA_RETENIDO, ISR_RETENIDO, DSCTO_PPAG"
        ") VALUES ("
        "  -1, ?, 'N', 'S', 'C', 0,"
        "  ?, ?, 0, 0, 0"
        ")",
        (docto_cp_id, importe_total, impuesto),
    )

    cur.execute("SELECT GEN_ID(ID_DOCTOS, 0) FROM RDB$DATABASE")
    impte_id = cur.fetchone()[0]

    # 5. IMPORTES_DOCTOS_CP_IMPTOS
    if impuesto > 0:
        cur.execute(
            "INSERT INTO IMPORTES_DOCTOS_CP_IMPTOS ("
            "  IMPTE_DOCTO_CP_IMPTO_ID, IMPTE_DOCTO_CP_ID, IMPUESTO_ID,"
            "  IMPORTE, PCTJE_IMPUESTO, IMPUESTO"
            ") VALUES (-1, ?, ?, ?, 16, ?)",
            (impte_id, IMPUESTO_ID, importe_total, impuesto),
        )

    # 6. VENCIMIENTOS_CARGOS_CP
    cur.execute(
        "INSERT INTO VENCIMIENTOS_CARGOS_CP "
        "(DOCTO_CP_ID, FECHA_VENCIMIENTO, PCTJE_VEN) "
        "VALUES (?, CURRENT_DATE, 100)",
        (docto_cp_id,),
    )

    # 7. DEMO_DOCTOS_COT_LIGAS (trazabilidad)
    cur.execute(
        "INSERT INTO DEMO_DOCTOS_COT_LIGAS "
        "(DOCTO_COT_LIGA_ID, FOLIO_COT_FTE, FOLIO_OCM_DEST) "
        "VALUES (-1, ?, ?)",
        (folio_cot, folio_oc),
    )

    # 8. FOLIOS_COMPRAS
    cur.execute(
        "UPDATE FOLIOS_COMPRAS SET CONSECUTIVO = ? "
        "WHERE TIPO_DOCTO = 'O' AND SERIE = 'OC' AND SUCURSAL_ID = ?",
        (int(folio_oc[2:]) + 1, SUCURSAL_ID),
    )

    total_oc = round(importe_total + impuesto, 2)

    log.info(
        "OC generada: cot=%s -> OC=%s (CM=%s, CP=%s, importe=%.2f, usuario=%s)",
        folio_cot, folio_oc, docto_cm_id, docto_cp_id, importe_total, usuario,
    )

    return {
        "folio_oc": folio_oc,
        "docto_cp_id": docto_cp_id,
        "importe": importe_total,
        "impuesto": impuesto,
        "total": total_oc,
    }


# ── Servicio: generar OC (cotizacion ya autorizada) ───────────────────────────

def generar_oc(req: GenerarOCRequest) -> GenerarOCResponse:
    """
    Genera una Orden de Compra desde una cotizacion completamente autorizada.
    """
    with get_db() as conn:
        cur = conn.cursor()

        # 1. Obtener cotizacion
        cur.execute(
            "SELECT DOCTO_RQ_ID, PROVEEDOR_ID, TRIM(CLAVE_PROV) AS CLAVE_PROV, "
            "       COND_PAGO_ID, DESCRIPCION, ESTATUS, TRIM(FOLIO) AS FOLIO "
            "FROM DEMO_DOCTOS_RQ "
            "WHERE TRIM(FOLIO) = ? AND TIPO_DOCTO = 'C'",
            (normalizar_folio(req.folio_cotizacion),),
        )
        cot = _row_as_dict(cur)
        if not cot:
            raise HTTPException(404, f"Cotizacion '{req.folio_cotizacion}' no encontrada.")

        # 2. Validar autorizacion completa
        if cot["ESTATUS"] != "A":
            raise HTTPException(
                400,
                f"La cotizacion '{req.folio_cotizacion}' no esta completamente autorizada. "
                f"Estatus actual: {cot['ESTATUS']}. "
                "Debe tener NIVEL_AUT_COT='S' y NIVEL_AUT_COT2='S'.",
            )

        if not cot.get("PROVEEDOR_ID"):
            raise HTTPException(400, "La cotizacion no tiene proveedor asignado.")

        # 3. Validar que no tenga OC ya generada
        cur.execute(
            "SELECT COUNT(*) FROM DEMO_DOCTOS_COT_LIGAS "
            "WHERE TRIM(FOLIO_COT_FTE) = ? AND FOLIO_OCM_DEST IS NOT NULL",
            (normalizar_folio(req.folio_cotizacion),),
        )
        if cur.fetchone()[0] > 0:
            raise HTTPException(
                400,
                f"La cotizacion '{req.folio_cotizacion}' ya tiene una OC generada.",
            )

        result = _insertar_oc(
            cur,
            docto_rq_id=cot["DOCTO_RQ_ID"],
            proveedor_id=cot["PROVEEDOR_ID"],
            clave_prov=cot["CLAVE_PROV"] or "",
            cond_pago_id=cot["COND_PAGO_ID"] or COND_PAGO_ID_DEFAULT,
            folio_cot=cot["FOLIO"],
            descripcion=cot["DESCRIPCION"],
            usuario=req.usuario,
        )

        return GenerarOCResponse(
            ok=True,
            mensaje="Orden de Compra generada exitosamente.",
            folio_cotizacion=cot["FOLIO"],
            folio_oc=result["folio_oc"],
            docto_cp_id=result["docto_cp_id"],
            importe=result["importe"],
            impuesto=result["impuesto"],
            total=result["total"],
        )


# ── Servicio combinado: aprobar nivel 2 + generar OC (Teams) ──────────────────

def aprobar_y_generar_oc(req: "AprobarYGenerarOCRequest") -> "AprobarYGenerarOCResponse":
    """
    Flujo completo desde Teams/Approvals:
      1. Valida la cotizacion (existe, no cancelada, N1 autorizado, sin OC previa, tiene proveedor)
      2. Autoriza nivel 2 (si no esta ya autorizado)
      3. Genera la OC
    Todo en el mismo usuario que firmo en Teams.
    """
    from models.cotizacion import AprobarYGenerarOCRequest, AprobarYGenerarOCResponse
    with get_db() as conn:
        cur = conn.cursor()

        # ── 1. Obtener cotizacion ──────────────────────────────────────────────
        cur.execute(
            "SELECT DOCTO_RQ_ID, PROVEEDOR_ID, TRIM(CLAVE_PROV) AS CLAVE_PROV, "
            "       COND_PAGO_ID, DESCRIPCION, ESTATUS, TRIM(FOLIO) AS FOLIO, "
            "       NIVEL_AUT_COT, NIVEL_AUT_COT2, DESCRIP_AUTORIZADO_COT, "
            "       DESCRIP_AUTORIZADO_COT2 "
            "FROM DEMO_DOCTOS_RQ "
            "WHERE TRIM(FOLIO) = ? AND TIPO_DOCTO = 'C'",
            (normalizar_folio(req.folio_cotizacion),),
        )
        cot = _row_as_dict(cur)
        if not cot:
            raise HTTPException(404, f"Cotizacion '{req.folio_cotizacion}' no encontrada.")

        # ── 2. Validaciones previas (ANTES de cualquier escritura) ──────────────
        if cot["ESTATUS"] == "C":
            raise HTTPException(400, "La cotizacion esta cancelada.")

        if cot["NIVEL_AUT_COT"] != "S":
            raise HTTPException(400, "El nivel 1 aun no ha sido autorizado.")

        if not cot.get("PROVEEDOR_ID"):
            raise HTTPException(400, "La cotizacion no tiene proveedor asignado.")

        # Validar que no tenga OC ya generada
        cur.execute(
            "SELECT COUNT(*) FROM DEMO_DOCTOS_COT_LIGAS "
            "WHERE TRIM(FOLIO_COT_FTE) = ? AND FOLIO_OCM_DEST IS NOT NULL",
            (normalizar_folio(req.folio_cotizacion),),
        )
        if cur.fetchone()[0] > 0:
            raise HTTPException(
                400,
                f"La cotizacion '{req.folio_cotizacion}' ya tiene una OC generada.",
            )

        # ── 3. Autorizar nivel 2 si hace falta ─────────────────────────────────
        if cot["NIVEL_AUT_COT2"] == "S":
            log.info("Nivel 2 ya autorizado por %s, saltando...",
                     cot["DESCRIP_AUTORIZADO_COT2"])
        else:
            cur.execute(
                "UPDATE DEMO_DOCTOS_RQ SET "
                "  NIVEL_AUT_COT2          = 'S',"
                "  FECHA_AUT_COT2          = CURRENT_TIMESTAMP,"
                "  DESCRIP_AUTORIZADO_COT2 = ?,"
                "  ESTATUS                 = 'A',"
                "  USUARIO_ULT_MODIF       = ?,"
                "  FECHA_HORA_ULT_MODIF    = CURRENT_TIMESTAMP "
                "WHERE DOCTO_RQ_ID = ?",
                (req.usuario, req.usuario, cot["DOCTO_RQ_ID"]),
            )
            # Notificacion/auditoria
            try:
                cur.execute(
                    "INSERT INTO DEMO_NOTIFICACIONES "
                    "(NOTIFICACION_ID, DOCTO_ID, USUARIO, FECHA_HORA_ENVIO, "
                    " MENSAJE, TIPO_EVENTO, SELECCION) "
                    "VALUES (GEN_ID(GEN_DEMO_NOTIFICACIONES, 1), ?, ?, "
                    "CURRENT_TIMESTAMP, ?, 'AC2', 'S')",
                    (cot["DOCTO_RQ_ID"], req.usuario,
                     f"Aprobacion nivel 2 + OC via Teams\n"
                     f"Folio: {req.folio_cotizacion}\n"
                     f"Comentario: {getattr(req, 'comentario', None) or 'Sin comentario'}"),
                )
            except Exception as e:
                log.warning("No se pudo insertar notificacion: %s", e)

            log.info("Cotizacion %s autorizada nivel 2 por %s (Teams)",
                     req.folio_cotizacion, req.usuario)

        # ── 4. Generar OC ──────────────────────────────────────────────────────
        result = _insertar_oc(
            cur,
            docto_rq_id=cot["DOCTO_RQ_ID"],
            proveedor_id=cot["PROVEEDOR_ID"],
            clave_prov=cot["CLAVE_PROV"] or "",
            cond_pago_id=cot["COND_PAGO_ID"] or COND_PAGO_ID_DEFAULT,
            folio_cot=cot["FOLIO"],
            descripcion=cot["DESCRIPCION"],
            usuario=req.usuario,
        )

        return {
            "ok": True,
            "mensaje": "Cotizacion autorizada (nivel 2) y OC generada desde Teams.",
            "folio_cotizacion": cot["FOLIO"],
            "folio_oc": result["folio_oc"],
            "docto_cp_id": result["docto_cp_id"],
            "importe": result["importe"],
            "impuesto": result["impuesto"],
            "total": result["total"],
            "autorizado_por": req.usuario,
            "completamente_autorizada": True,
        }
