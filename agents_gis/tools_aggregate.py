"""
Tool: spatial.aggregate
Agrupa elementos de una capa por uno o más campos y calcula métricas
(COUNT, SUM, AVG, MIN, MAX) por grupo. Equivalente a un GROUP BY de SQL.

Útil para preguntas como:
  - "¿cuántos tramos hay por categoría?"
  - "¿qué tipos de estructura predominan?"
  - "suma la longitud medida por tipo de canalización"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, bbox_in_layer_srid,
)

_ALLOWED_FUNCS = {"count", "sum", "avg", "min", "max"}


@register_tool
class SpatialAggregateTool(BaseTool):
    name = "spatial.aggregate"
    description = (
        "Agrupa elementos de una capa GIS por uno o más campos y calcula métricas por grupo "
        "(COUNT, SUM, AVG, MIN, MAX). Ideal para inventarios, recuentos por tipo/categoría "
        "y análisis estadísticos sin necesidad de descargar todos los registros."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa (de gis_layers_catalog).",
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de campos por los que agrupar (deben estar en filter_fields). "
                    "Máximo 4 campos."
                ),
            },
            "aggs": {
                "type": "array",
                "description": (
                    "Agregaciones adicionales a COUNT(*). Cada entrada: "
                    '{"field": "nombre_campo", "func": "sum|avg|min|max", "alias": "nombre_resultado"}.'
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "func": {"type": "string", "enum": list(_ALLOWED_FUNCS - {"count"})},
                        "alias": {"type": "string"},
                    },
                    "required": ["field", "func"],
                },
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial opcional (WGS84).",
                "properties": {
                    "west": {"type": "number"},
                    "south": {"type": "number"},
                    "east": {"type": "number"},
                    "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "filters": {
                "type": "object",
                "description": (
                    "Filtros de atributo opcionales. Mismo formato que spatial.query_layer: "
                    '{"campo": valor} o {"campo": [v1, v2]}.'
                ),
            },
            "order_by": {
                "type": "string",
                "enum": ["count_desc", "count_asc", "group_asc"],
                "description": (
                    "Ordenación: count_desc (más frecuente primero, defecto), "
                    "count_asc (menos frecuente primero), group_asc (orden alfabético del grupo)."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Máximo número de grupos a devolver (1-200, defecto 50).",
            },
        },
        "required": ["layer", "group_by"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        group_by = args.get("group_by") or []
        if not group_by or not isinstance(group_by, list):
            return ToolResult(ok=False, error="group_by must be a non-empty list of field names")
        if len(group_by) > 4:
            return ToolResult(ok=False, error="group_by supports at most 4 fields")

        aggs_raw = args.get("aggs") or []
        filters = args.get("filters") or {}
        bbox = args.get("bbox")
        order_by = (args.get("order_by") or "count_desc").strip()
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        # ── Validar campos ──────────────────────────────────────────────────
        filter_fields = set(layer.get("filter_fields") or [])
        all_fields = set(layer.get("fields") or []) | filter_fields
        id_col = layer.get("id_col", "id")
        filter_fields.add(id_col)

        for f in group_by:
            if f not in filter_fields:
                return ToolResult(ok=False, error=f"group_by field not allowed: {f}")

        aggs = []
        for agg in aggs_raw:
            if not isinstance(agg, dict):
                return ToolResult(ok=False, error="each agg must be an object")
            field = (agg.get("field") or "").strip()
            func = (agg.get("func") or "").strip().lower()
            alias = (agg.get("alias") or f"{func}_{field}").strip()

            if not field:
                return ToolResult(ok=False, error="agg field is required")
            if func not in _ALLOWED_FUNCS - {"count"}:
                return ToolResult(ok=False, error=f"agg func must be one of: sum, avg, min, max")
            if field not in all_fields:
                return ToolResult(ok=False, error=f"agg field not in layer fields: {field}")

            aggs.append({"field": field, "func": func, "alias": alias})

        # ── WHERE ───────────────────────────────────────────────────────────
        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)

        where_clauses = [f"{qgeom} IS NOT NULL"]
        params = []

        if bbox:
            west = float(bbox["west"])
            south = float(bbox["south"])
            east = float(bbox["east"])
            north = float(bbox["north"])
            envelope_sql = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {envelope_sql})")
            params.extend([west, south, east, north])
        else:
            west = south = east = north = None

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")
        filters = {k: v for k, v in filters.items()
                   if v is not None and not isinstance(v, (dict, bool))}
        for k in filters:
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")
        for k, v in filters.items():
            if isinstance(v, list):
                if not v:
                    continue
                placeholders = ", ".join(["%s"] * len(v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                where_clauses.append(f"{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        where_sql = " AND ".join(where_clauses)

        # ── SELECT ──────────────────────────────────────────────────────────
        group_cols_sql = ", ".join(quote_col(f) for f in group_by)
        select_parts = [group_cols_sql, "COUNT(*)::int AS count"]
        for agg in aggs:
            select_parts.append(
                f"{agg['func'].upper()}({quote_col(agg['field'])}) AS {quote_col(agg['alias'])}"
            )
        select_sql = ", ".join(select_parts)

        if order_by == "count_asc":
            order_sql = "ORDER BY count ASC"
        elif order_by == "group_asc":
            order_sql = f"ORDER BY {group_cols_sql} ASC"
        else:
            order_sql = "ORDER BY count DESC"

        # Total de grupos (sin LIMIT)
        count_groups_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT {group_cols_sql}
                FROM {table}
                WHERE {where_sql}
                GROUP BY {group_cols_sql}
            ) _g
        """

        groups_sql = f"""
            SELECT {select_sql}
            FROM {table}
            WHERE {where_sql}
            GROUP BY {group_cols_sql}
            {order_sql}
            LIMIT %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(count_groups_sql, params)
            total_groups = cur.fetchone()[0]

            cur.execute(groups_sql, params + [limit])
            groups = _fetchall_dict(cur)

        # Convertir Decimal → float para serialización JSON
        for row in groups:
            for k, v in row.items():
                try:
                    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                        row[k] = float(v)
                except Exception:
                    pass

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "group_by": group_by,
                "aggs": [{"field": a["field"], "func": a["func"], "alias": a["alias"]} for a in aggs],
                "bbox": {"west": west, "south": south, "east": east, "north": north} if bbox else None,
                "filters": filters,
                "total_groups": total_groups,
                "groups": groups,
                "limit": limit,
                "order_by": order_by,
            },
        )
