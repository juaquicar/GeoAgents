from django.conf import settings
from django.db import connections, close_old_connections


# ── Registro de aliases de agente ──────────────────────────────────────────

def _make_agent_db_cfg(conn_cfg: dict) -> dict:
    """
    Construye el dict de configuración de BD con todos los defaults
    que Django 6 espera (los inyecta via configure_settings solo al arrancar,
    no al añadir aliases dinámicamente).
    """
    options = {}
    if conn_cfg.get("sslmode"):
        options["sslmode"] = conn_cfg["sslmode"]
    return {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": conn_cfg.get("db_name", ""),
        "USER": conn_cfg.get("user", ""),
        "PASSWORD": conn_cfg.get("password", "") or "",
        "HOST": conn_cfg.get("host", ""),
        "PORT": str(conn_cfg.get("port", 5432)),
        # Defaults que Django 6 no inyecta en aliases dinámicos
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
        "OPTIONS": options,
        "TEST": {
            "CHARSET": None, "COLLATION": None,
            "MIGRATE": True, "MIRROR": None, "NAME": None,
        },
    }


def get_or_register_agent_alias(agent_pk: int, conn_cfg: dict) -> str:
    """
    Registra la BD de un agente como alias Django (idempotente) y devuelve el alias.
    Formato: _agent_<pk>__<conn_alias>
    """
    alias = f"_agent_{agent_pk}__{conn_cfg.get('alias', 'default')}"
    db_cfg = _make_agent_db_cfg(conn_cfg)

    current_cfg = connections.databases.get(alias)
    if current_cfg != db_cfg:
        connections.databases[alias] = db_cfg
        if current_cfg is not None:
            # Forzar nueva conexión cuando cambian host/db/credenciales.
            try:
                connections[alias].close()
            except Exception:
                pass
        # Limpiar el wrapper cacheado para forzar recreación con la nueva config
        try:
            delattr(connections._connections, alias)
        except AttributeError:
            pass
    return alias


# ── Conexión GIS (context-aware) ───────────────────────────────────────────

def get_gis_connection(layer_cfg: dict = None):
    """
    Devuelve la conexión de BD para las herramientas GIS.

    Orden de resolución:
    1. Si hay un agente en contexto con gis_db_connections:
       a. Si layer_cfg tiene '_db_alias', usa esa conexión del agente.
       b. Si no, usa la conexión marcada como is_default (o la primera).
    2. Fallback: alias de settings.AGENTS_GIS_DB_ALIAS.
    """
    from agents_gis.context import get_current_agent
    agent = get_current_agent()

    alias = None
    if agent and agent.gis_db_connections:
        conns = agent.gis_db_connections
        # Intentar con la conexión específica del layer
        if layer_cfg and layer_cfg.get("_db_alias"):
            db_alias_name = layer_cfg["_db_alias"]
            conn_cfg = next((c for c in conns if c.get("alias") == db_alias_name), None)
        else:
            conn_cfg = None
        # Fallback a la conexión por defecto del agente
        if not conn_cfg:
            conn_cfg = next((c for c in conns if c.get("is_default")), None) or conns[0]
        alias = get_or_register_agent_alias(agent.pk, conn_cfg)

    if alias is None:
        alias = getattr(settings, "AGENTS_GIS_DB_ALIAS", "default")

    close_old_connections()
    conn = connections[alias]
    try:
        conn.ensure_connection()
    except Exception:
        conn.close()
        conn.ensure_connection()
    return conn


# ── Schema GIS (context-aware) ─────────────────────────────────────────────

def get_gis_schema() -> str:
    """Devuelve el esquema PostgreSQL para las capas GIS."""
    from agents_gis.context import get_current_agent
    agent = get_current_agent()
    if agent and agent.gis_db_connections:
        default_conn = (
            next((c for c in agent.gis_db_connections if c.get("is_default")), None)
            or agent.gis_db_connections[0]
        )
        return default_conn.get("schema", "public")
    return getattr(settings, "AGENTS_GIS_SCHEMA", "public")


# ── Catálogo de capas (context-aware) ──────────────────────────────────────

def get_agent_gis_layers(agent=None) -> list:
    """
    Devuelve el catálogo de capas activo.
    Prioridad: agente pasado > agente en contexto > settings.AGENTS_GIS_LAYERS.
    """
    if agent is None:
        from agents_gis.context import get_current_agent
        agent = get_current_agent()
    if agent:
        return list(agent.gis_layers_catalog or [])
    return list(getattr(settings, "AGENTS_GIS_LAYERS", []))


def _get_layer_cfg(layer_name: str):
    """Busca la configuración de una capa por nombre (context-aware)."""
    from agents_gis.context import get_current_agent
    agent = get_current_agent()
    layers = (agent.gis_layers_catalog or []) if agent else getattr(settings, "AGENTS_GIS_LAYERS", [])
    for layer in layers:
        if layer.get("name") == layer_name:
            return layer
    return None


# ── Utilidades SQL ─────────────────────────────────────────────────────────

def qualified_table(layer_cfg: dict) -> str:
    """Devuelve schema.tabla o solo tabla según la configuración."""
    schema = layer_cfg.get("schema") or get_gis_schema()
    table = layer_cfg["table"]
    if schema and schema != "public":
        return f'"{schema}"."{table}"'
    return f'"{table}"'


def quote_col(name: str) -> str:
    """Envuelve un nombre de columna en comillas dobles."""
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
    """SQL fragment para un envelope de bbox 4326 convertido al SRID de la capa."""
    if srid == 4326:
        return "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
    return f"ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), {srid})"


def point_in_layer_srid(srid: int) -> str:
    """SQL fragment para un punto lon/lat 4326 convertido al SRID de la capa."""
    if srid == 4326:
        return "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
    return f"ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), {srid})"


def _json_safe(value):
    """Convierte tipos no serializables a JSON a su representación string."""
    import datetime
    import decimal
    import uuid
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    return value


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [
        {k: _json_safe(v) for k, v in zip(cols, row)}
        for row in cursor.fetchall()
    ]
