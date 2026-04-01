from django.conf import settings
from django.db import connections


def get_gis_connection():
    """Devuelve la conexión de BD configurada para las herramientas GIS."""
    alias = getattr(settings, "AGENTS_GIS_DB_ALIAS", "default")
    return connections[alias]


def get_gis_schema() -> str:
    """Devuelve el esquema PostgreSQL donde están las capas GIS."""
    return getattr(settings, "AGENTS_GIS_SCHEMA", "public")


def qualified_table(layer_cfg: dict) -> str:
    """Devuelve schema.tabla o solo tabla según la configuración."""
    schema = layer_cfg.get("schema") or get_gis_schema()
    table = layer_cfg["table"]
    if schema and schema != "public":
        return f'"{schema}"."{table}"'
    return f'"{table}"'


def quote_col(name: str) -> str:
    """Envuelve un nombre de columna en comillas dobles para evitar conflictos con palabras reservadas."""
    return f'"{name}"'


def get_layer_srid(layer_cfg: dict) -> int:
    """Devuelve el SRID de la capa (campo 'srid' o '_srid', por defecto 4326)."""
    return int(layer_cfg.get("srid") or layer_cfg.get("_srid") or 4326)


def geom_to_4326(expr: str, srid: int) -> str:
    """Envuelve una expresión de geometría con ST_Transform a 4326 si el SRID no es 4326."""
    if srid == 4326:
        return expr
    return f"ST_Transform({expr}, 4326)"


def bbox_in_layer_srid(srid: int) -> str:
    """
    SQL fragment para un envelope de bbox 4326 convertido al SRID de la capa.
    Parámetros: west, south, east, north
    """
    if srid == 4326:
        return "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
    return f"ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), {srid})"


def point_in_layer_srid(srid: int) -> str:
    """
    SQL fragment para un punto lon/lat 4326 convertido al SRID de la capa.
    Parámetros: lon, lat
    """
    if srid == 4326:
        return "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
    return f"ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), {srid})"


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _get_layer_cfg(layer_name: str):
    layers = getattr(settings, "AGENTS_GIS_LAYERS", [])
    for l in layers:
        if l.get("name") == layer_name:
            return l
    return None
