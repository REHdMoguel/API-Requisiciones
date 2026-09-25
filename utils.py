"""Utilidades compartidas del API Procurement."""
import re

_FOLIO_COT_REGEX = re.compile(r"^C(\d+)$")


def normalizar_folio(folio: str) -> str:
    """Convierte 'C27814' -> 'C0027814' para matching exacto en BD."""
    folio = folio.strip().upper()
    m = _FOLIO_COT_REGEX.match(folio)
    if m:
        num = m.group(1)
        if len(num) < 7:
            num = num.zfill(7)
        return f"C{num}"
    return folio
