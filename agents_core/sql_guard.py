"""
sql_guard.py — Validación defensiva de SQL generado por el LLM.

Solo se permiten SELECT de solo lectura. Se rechaza cualquier SQL que:
  1. Contenga palabras clave de escritura/destrucción.
  2. Referencie tablas no presentes en el catálogo de capas del agente.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Palabras clave que implican escritura o ejecución de código arbitrario.
_DENY_KEYWORDS = [
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bTRUNCATE\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bEXECUTE\b",
    r"\bCALL\b",
    r"\bDO\b",
    r"\bCOPY\b",
    r"\bVACUUM\b",
    r"\bANALYZE\b",
    r"\bREINDEX\b",
    r"\bCLUSTER\b",
    r"\bSET\b",
    r"\bRESET\b",
    r"\bSHOW\b",
    r"\bLOAD\b",
    r"\bpg_sleep\b",
    r"\bpg_read_file\b",
    r"\bpg_ls_dir\b",
    r"\bpg_stat_file\b",
    r";\s*\w",          # múltiples sentencias
]

_DENY_RE = re.compile(
    "|".join(_DENY_KEYWORDS),
    re.IGNORECASE,
)

# Patrón simple para extraer nombres de tabla de un SELECT.
# Captura: FROM <tabla>, JOIN <tabla>, LATERAL (<subq>) — no es un parser SQL completo
# pero es suficiente para la whitelist de capas conocidas.
_TABLE_RE = re.compile(
    r"(?:FROM|JOIN|LATERAL\s+\(?\s*SELECT\s+\S+\s+FROM)\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
    re.IGNORECASE,
)


def validate_sql(
    sql: str,
    allowed_tables: Optional[List[str]] = None,
) -> str:
    """
    Valida el SQL generado por el LLM.

    Devuelve el SQL limpio si es válido.
    Lanza ValueError con el motivo si no lo es.

    :param sql: Sentencia SQL a validar.
    :param allowed_tables: Lista de nombres de tabla permitidos (esquema.tabla o solo tabla).
                           Si None o vacía, se omite la comprobación de tablas.
    """
    if not sql or not sql.strip():
        raise ValueError("SQL vacío")

    sql = sql.strip()

    # Debe empezar por SELECT (ignorando CTE: WITH ... SELECT)
    first_kw = re.match(r"^\s*(WITH|SELECT)\b", sql, re.IGNORECASE)
    if not first_kw:
        raise ValueError("Solo se permiten sentencias SELECT")

    # Deny-list de palabras clave peligrosas
    match = _DENY_RE.search(sql)
    if match:
        raise ValueError(f"SQL contiene operación no permitida: '{match.group()}'")

    # Whitelist de tablas
    if allowed_tables:
        allowed_set = set()
        for t in allowed_tables:
            # Normalizar: "schema.table" y "table" como variantes
            t_lower = t.lower()
            allowed_set.add(t_lower)
            if "." in t_lower:
                allowed_set.add(t_lower.split(".", 1)[1])  # solo nombre de tabla

        referenced = {m.group(1).lower() for m in _TABLE_RE.finditer(sql)}
        for table in referenced:
            t_bare = table.split(".")[-1] if "." in table else table
            if table not in allowed_set and t_bare not in allowed_set:
                raise ValueError(f"Tabla no autorizada en SQL: '{table}'")

    return sql
