import fdb
import contextvars
from contextlib import contextmanager
from multi_db import get_sucursal_config, DEFAULT_SUCURSAL

# Context variable: si esta seteada, get_db() usa esta sucursal.
# Si no, usa la BD default (compatibilidad hacia atras).
_current_sucursal = contextvars.ContextVar("sucursal", default=None)


def _new_conn_from_config(cfg: dict):
    return fdb.connect(
        host=cfg["host"],
        database=cfg["path"],
        user=cfg["user"],
        password=cfg["password"],
        charset=cfg.get("charset", "WIN1252"),
    )


def _get_active_config() -> dict:
    """Resuelve que config de BD usar: sucursal activa o default."""
    suc = _current_sucursal.get()
    if suc:
        return get_sucursal_config(suc)
    return get_sucursal_config(DEFAULT_SUCURSAL)


@contextmanager
def get_db():
    """Context manager unico. Usa sucursal activa si hay una, o default."""
    cfg = _get_active_config()
    conn = _new_conn_from_config(cfg)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Helper para routers multi-tenant ─────────────────────────────────────────

def db_for(sucursal: str):
    """FastAPI dependency: activa una sucursal para este request."""
    _current_sucursal.set(sucursal)


def listar_sucursales() -> list:
    """Lista sucursales disponibles (sin la default)."""
    from multi_db import listar_sucursales as _ls
    return _ls()
