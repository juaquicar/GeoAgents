"""
Tool: spatial.dissolve
Fusiona (disuelve) geometrías de una capa agrupando por un campo.
Equivalente a ST_Union(...) GROUP BY campo.

Útil para preguntas como:
  - "Fusiona las parcelas del mismo propietario"
  - "Une los tramos por categoría y muéstrame la geometría resultante"
  - "Agrupa los rodales por especie y calcula el área total de cada especie"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)

_ALLOWED_FUNCS = {"sum", "avg", "min", "max"}


@register_tool
class SpatialDissolveTool(BaseTool):
    name = "spatial.dissolve"
    description = (
        "Fusiona (disuelve) geometrías de una capa agrupando por un campo, usando ST_Union. "
        "Devuelve una feature por valor único del campo con la geometría fusionada y métricas "
        "(recuento de features originales, área total). Ideal para agregar geometrías por "
        "categoría, propietario, tipo u otro atributo clasificador."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa (de gis_layers_catalog).",
            },
            "dissolve_field": {
                "type": "string",
                "description": "Campo por el que agrupar y fusionar geometrías (debe estar en filter_fields).",
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
                "description": "Filtros de atributo opcionales. Mismo formato que spatial.query_layer.",
            },
            "aggs": {
                "type": "array",
                "description": (
                    "Agregaciones adicionales sobre campos numéricos. "
                    'Cada entrada: {"field": "campo", "func": "sum|avg|min|max", "alias": "nombre_resultado"}.'
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "func": {"type": "string", "enum": list(_ALLOWED_FUNCS)},
                        "alias": {"type": "string"},
                    },
                    "required": ["field", "func"],
                },
            },
            "include_geom": {
                "type": "boolean",
                "description": "Si true, incluye la geometría GeoJSON fusionada en cada grupo.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo número de grupos a devolver (1-200, defecto 50).",
            },
        },
        "required": ["layer", "dissolve_field"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        dissolve_field = (args.get("dissolve_field") or "").strip()
        if not dissolve_field:
            return ToolResult(ok=False, error="dissolve_field is required")

        filter_fields = set(layer.get("filter_fields") or [])
        all_fields = set(layer.get("fields") or []) | filter_fields
        id_col = layer.get("id_col", "id")
        filter_fields.add(id_col)

        if dissolve_field not in filter_fields:
            return ToolResult(ok=False, error=f"dissolve_field not allowed: {dissolve_field}")

        aggs_raw = args.get("aggs") or []
        filters = args.get("filters") or {}
        bbox = args.get("bbox")
        include_geom = bool(args.get("include_geom") or False)
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        # Validar aggs
        aggs = []
        for agg in aggs_raw:
            if not isinstance(agg, dict):
                return ToolResult(ok=False, error="each agg must be an object")
            field = (agg.get("field") or "").strip()
            func = (agg.get("func") or "").strip().lower()
            alias = (agg.get("alias") or f"{func}_{field}").strip()
            if not field:
                return ToolResult(ok=False, error="agg field is required")
            if func not in _ALLOWED_FUNCS:
                return ToolResult(ok=False, error=f"agg func must be one of: sum, avg, min, max")
            if field not in all_fields:
                return ToolResult(ok=False, error=f"agg field not in layer fields: {field}")
            aggs.append({"field": field, "func": func, "alias": alias})

        # Configuración de capa
        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        qfield = quote_col(dissolve_field)
        geom4326 = geom_to_4326(qgeom, srid)

        # WHERE
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

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")
        filters = {k: v for k, v in filters.items()
                   if v is not None and not isinstance(v, dict)}
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

        # SELECT: campo agrupador + COUNT + área + aggs opcionales + geom opcional
        dissolved_geom_expr = f"ST_Union({geom4326})"
        select_parts = [
            qfield,
            "COUNT(*)::int AS feature_count",
            f"ST_Area({dissolved_geom_expr}::geography)::float AS dissolved_area_m2",
        ]
        for agg in aggs:
            select_parts.append(
                f"{agg['func'].upper()}({quote_col(agg['field'])}) AS {quote_col(agg['alias'])}"
            )
        if include_geom:
            select_parts.append(f"ST_AsGeoJSON({dissolved_geom_expr}) AS dissolved_geom")

        select_sql = ", ".join(select_parts)

        count_sql = f"""
            SELECT COUNT(DISTINCT {qfield})::int AS total_groups
            FROM {table}
            WHERE {where_sql}
        """

        groups_sql = f"""
            SELECT {select_sql}
            FROM {table}
            WHERE {where_sql}
            GROUP BY {qfield}
            ORDER BY feature_count DESC
            LIMIT %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, params)
            total_groups = cur.fetchone()[0]

            cur.execute(groups_sql, params + [limit])
            groups = _fetchall_dict(cur)

        # Convertir Decimal → float para serialización JSON
        for row in groups:
            for k, v in row.items():
                if k == "dissolved_geom":
                    continue
                try:
                    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                        row[k] = float(v)
                except Exception:
                    pass

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "dissolve_field": dissolve_field,
                "bbox": bbox,
                "filters": filters,
                "total_groups": total_groups,
                "dissolved_features": groups,
                "include_geom": include_geom,
                "limit": limit,
            },
        )
