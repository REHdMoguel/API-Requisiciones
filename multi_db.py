"""Optional multi-branch database configuration from environment variables."""
import json
from config import settings

DEFAULT_SUCURSAL = "default"


def _load_branches() -> dict:
    raw = __import__("os").getenv("DB_BRANCHES_JSON", "{}")
    branches = json.loads(raw)
    if not isinstance(branches, dict):
        raise ValueError("DB_BRANCHES_JSON must be a JSON object")
    return branches


SUCURSALES = _load_branches()


def get_sucursal_config(sucursal: str) -> dict:
    if sucursal in ("", DEFAULT_SUCURSAL, None):
        return {
            "host": settings.DB_HOST,
            "path": settings.DB_PATH,
            "user": settings.DB_USER,
            "password": settings.DB_PASSWORD,
            "charset": settings.DB_CHARSET,
        }
    if sucursal not in SUCURSALES:
        raise KeyError(f"Unknown branch: {sucursal}")
    cfg = SUCURSALES[sucursal]
    required = {"host", "path", "user", "password"}
    missing = sorted(required - cfg.keys())
    if missing:
        raise ValueError(f"Branch {sucursal} is missing: {', '.join(missing)}")
    return {**cfg, "charset": cfg.get("charset", settings.DB_CHARSET)}


def listar_sucursales() -> list:
    return sorted(SUCURSALES)
