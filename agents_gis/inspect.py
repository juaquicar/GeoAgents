"""
Lógica de introspección GIS reutilizable.
Se usa al guardar un Agente (auto-inspect) y desde el management command.
"""
from django.db import connections, close_old_connections

# Tipos de geometría PostGIS → geometry_kind
_GEOM_KIND_MAP = {
    "point": "point",
    "multipoint": "point",
    "linestring": "line",
    "multilinestring": "line",
    "linestringz": "line",
    "multilinestringz": "line",
    "polygon": "polygon",
    "multipolygon": "polygon",
    "geometry": "point",
    "geometrycollection": "point",
}

_SKIP_TYPES = {
    "geometry", "geography", "bytea", "oid", "xid", "cid", "tid",
}

_SYSTEM_COLS = {
    "tableoid", "cmax", "xmax", "cmin", "xmin", "ctid",
}


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _infer_id_col(columns: list) -> str:
    for col in columns:
        if col["name"] in ("id", "gid", "ogc_fid", "objectid", "fid"):
            return col["name"]
    for col in columns:
        if col["data_type"] in ("integer", "bigint", "smallint", "serial", "bigserial"):
            return col["name"]
    return "id"


def _infer_geometry_kind(geom_type: str) -> str:
    key = (geom_type or "").lower()
    return _GEOM_KIND_MAP.get(key, "point")


def _inspect_tables(cursor, schema: str) -> list:
    cursor.execute(
        """
        SELECT f_table_schema AS schema, f_table_name AS table_name,
               f_geometry_column AS geom_col, type AS geom_type, srid
        FROM geometry_columns
        WHERE f_table_schema = %s
        ORDER BY f_table_name
        """,
        [schema],
    )
    return _fetchall_dict(cursor)


def _inspect_columns(cursor, schema: str, table: str) -> list:
    cursor.execute(
        """
        SELECT column_name AS name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        [schema, table],
    )
    rows = _fetchall_dict(cursor)
    return [
        r for r in rows
        if r["name"] not in _SYSTEM_COLS
        and r["data_type"].lower() not in _SKIP_TYPES
    ]


def get_or_register_agent_alias(agent_pk: int, conn_cfg: dict) -> str:
    """
    Registra la BD de un agente como alias Django (si no existe) y devuelve el alias.
    El alias tiene formato: _agent_<pk>__<conn_alias>
    """
    alias = f"_agent_{agent_pk}__{conn_cfg.get('alias', 'default')}"
    if alias not in connections.databases:
        db_cfg = {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": conn_cfg.get("db_name", ""),
            "USER": conn_cfg.get("user", ""),
            "PASSWORD": conn_cfg.get("password", "") or "",
            "HOST": conn_cfg.get("host", ""),
            "PORT": str(conn_cfg.get("port", 5432)),
            "CONN_MAX_AGE": 0,
            "ATOMIC_REQUESTS": False,
        }
        if conn_cfg.get("sslmode"):
            db_cfg["OPTIONS"] = {"sslmode": conn_cfg["sslmode"]}
        connections.databases[alias] = db_cfg
    return alias


def inspect_agent_gis(agent) -> list:
    """
    Inspecciona todas las conexiones GIS del agente y devuelve el catálogo de capas.
    Cada entrada incluye '_db_alias' indicando de qué conexión proviene.

    Lanza RuntimeError si alguna conexión falla.
    """
    catalog = []
    for conn_cfg in (agent.gis_db_connections or []):
        alias = get_or_register_agent_alias(agent.pk, conn_cfg)
        schema = conn_cfg.get("schema", "public")
        conn_alias_name = conn_cfg.get("alias", "default")

        close_old_connections()
        conn = connections[alias]
        try:
            conn.ensure_connection()
        except Exception:
            conn.close()
            conn.ensure_connection()

        try:
            with conn.cursor() as cur:
                tables = _inspect_tables(cur, schema)
        except Exception as exc:
            raise RuntimeError(
                f"Error al conectar con '{conn_alias_name}' "
                f"({conn_cfg.get('host')}:{conn_cfg.get('port')}/{conn_cfg.get('db_name')}): {exc}"
            ) from exc

        for tbl in tables:
            table_name = tbl["table_name"]
            with conn.cursor() as cur:
                cols = _inspect_columns(cur, schema, table_name)

            geom_col = tbl["geom_col"]
            geom_type = tbl["geom_type"] or "GEOMETRY"
            geometry_kind = _infer_geometry_kind(geom_type)
            data_cols = [c["name"] for c in cols if c["name"] != geom_col]
            id_col = _infer_id_col([c for c in cols if c["name"] != geom_col])
            fields = [c for c in data_cols if c != id_col]

            entry = {
                "name": table_name,
                "table": table_name,
                "geom_col": geom_col,
                "id_col": id_col,
                "fields": fields,
                "filter_fields": fields,
                "geometry_kind": geometry_kind,
                "srid": int(tbl["srid"]) if tbl.get("srid") else 4326,
                "geom_type": geom_type,
                "_db_alias": conn_alias_name,
            }
            if schema != "public":
                entry["schema"] = schema

            catalog.append(entry)

    return catalog
