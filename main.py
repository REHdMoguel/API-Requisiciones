from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routers.cotizaciones import router as cot_router
from routers.cotizaciones import router_mt
from config import settings
import logging
import time
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log"), encoding="utf-8"),
    ],
)

app = FastAPI(
    title="Procurement API Gateway",
    description=(
        "API Gateway para autorizacion de cotizaciones del modulo de "
        "procurement workflow en a Firebird ERP. Etapa 2: autorizaciones + generacion de OC."
    ),
    version="2.0.0",
)

app.include_router(cot_router)
app.include_router(router_mt)


# ── Debug middleware ───────────────────────────────────────────────────────────

@app.middleware("http")
async def debug_log_middleware(request: Request, call_next):
    """Loggea requests y responses cuando DEBUG_LOG=true."""
    if settings.DEBUG_LOG:
        body = None
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.body()
                body = body.decode("utf-8", errors="replace")[:500]
            except Exception:
                body = "[error leyendo body]"

        logging.info(
            ">>> %s %s | client=%s | body=%s",
            request.method, request.url.path, request.client.host if request.client else "?",
            body or "-",
        )

    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000

    if settings.DEBUG_LOG:
        logging.info(
            "<<< %s | status=%s | %.0fms",
            request.url.path, response.status_code, elapsed,
        )

    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error("Error no controlado: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "mensaje": "Error interno del servidor.",
                 "detalle": str(exc)},
    )


@app.get("/health", tags=["Sistema"])
def health():
    """Verifica que el servicio esta activo y la BD default conectada."""
    from database import get_db
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM DEMO_DOCTOS_RQ")
            total = cur.fetchone()[0]
        return {"ok": True, "db": "conectada", "total_cotizaciones": total}
    except Exception as e:
        return JSONResponse(status_code=503,
                            content={"ok": False, "db": "error", "detalle": str(e)})


@app.get("/health/all", tags=["Sistema"])
def health_all():
    """Verifica conexion a todas las sucursales configuradas."""
    from database import db_for, listar_sucursales, _get_active_config
    from multi_db import SUCURSALES
    import fdb

    status = {}
    for name in SUCURSALES:
        db_for(name)
        try:
            cfg = _get_active_config()
            conn = fdb.connect(
                host=cfg["host"], database=cfg["path"],
                user=cfg["user"], password=cfg["password"],
                charset=cfg.get("charset", "WIN1252"),
            )
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM DEMO_DOCTOS_RQ")
            total = cur.fetchone()[0]
            conn.close()
            status[name or "default"] = {"ok": True, "total": total}
        except Exception as e:
            status[name or "default"] = {"ok": False, "error": str(e)}

    return status


if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run("main:app", host=settings.API_HOST,
                port=settings.API_PORT, reload=False)
