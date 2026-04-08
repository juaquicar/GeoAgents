"""
Tool: spatial.difference
Calcula la diferencia geométrica de un feature de source_layer menos
las geometrías de subtract_layer que lo intersectan (ST_Difference).

Útil para:
  - "¿Qué parte de la parcela NO está cubierta por edificios?"
  - "Área libre de la zona verde descontando construcciones"
  - "Suelo disponible tras restar la red de infraestructura"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326,
)


@register_tool
class SpatialDifferenceTool(BaseTool):
    name = "spatial.difference"
    description = (
        "Calcula la diferencia geométrica: geometría de un feature de source_layer "
        "menos la unión de las geometrías de subtract_layer que lo intersectan. "
        "Devuelve la geometría residual con su área. Ideal para calcular 'área libre' "
        "o zonas no cubiertas por otra capa."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa que contiene el feature base.",
            },
            "source_id": {
                "description": "ID del feature de source_layer del que se calcula la diferencia.",
            },
            "subtract_layer": {
                "type": "string",
                "description": "Capa cuyas geometrías se restan.",
            },
            "subtract_filters": {
                "type": "object",
                "description": "Filtros de atributo opcionales sobre subtract_layer.",
            },
            "include_geom": {
                "type": "boolean",
                "description": "Si true, incluye la geometría residual (GeoJSON). Defecto true.",
            },
        },
        "required": ["source_layer", "source_id", "subtract_layer"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        sub_name = (args.get("subtract_layer") or "").strip()
        source_id = args.get("source_id")

        if not src_name or not sub_name:
            return ToolResult(ok=False, error="source_layer and subtract_layer are required")
        if source_id is None:
            return ToolResult(ok=False, error="source_id is required")

        src = _get_layer_cfg(src_name)
        sub = _get_layer_cfg(sub_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")
        if not sub:
            return ToolResult(ok=False, error=f"Unknown subtract_layer: {sub_name}")

        include_geom = args.get("include_geom", True)
        sub_filters = args.get("subtract_filters") or {}
        sub_filter_fields = set(sub.get("filter_fields") or []) | {sub.get("id_col", "id")}

        src_id_col = src.get("id_col", "id")
        src_geom_col = src.get("geom_col", "the_geom")
        src_fields = src.get("fields", [])
        src_srid = get_layer_srid(src)
        src_4326 = geom_to_4326(quote_col(src_geom_col), src_srid)

        sub_geom_col = sub.get("geom_col", "the_geom")
        sub_srid = get_layer_srid(sub)
        sub_g = f'b.{quote_col(sub_geom_col)}'
        sub_4326 = geom_to_4326(sub_g, sub_srid)

        params: list = [source_id]

        # Filtros subtract
        sub_where = [f"b.{quote_col(sub_geom_col)} IS NOT NULL"]
        sub_filters = {k: v for k, v in sub_filters.items()
                       if v is not None and not isinstance(v, dict)}
        for k in sub_filters:
            if k not in sub_filter_fields:
                return ToolResult(ok=False, error=f"subtract_filters field not allowed: {k}")
        for k, v in sub_filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                sub_where.append(f"b.{quote_col(k)} IN ({placeholders})")
                params.extend(v)
            else:
                sub_where.append(f"b.{quote_col(k)} = %s")
                params.append(v)

        sub_where_sql = " AND ".join(sub_where)
        src_fields_sql = ", ".join(f"a.{quote_col(f)}" for f in src_fields)

        empty_geom = "ST_GeomFromText('GEOMETRYCOLLECTION EMPTY', 4326)"
        diff_expr = f"ST_Difference({src_4326}, COALESCE(ST_Union({sub_4326}), {empty_geom}))"
        geom_sql = f", ST_AsGeoJSON({diff_expr}) AS difference_geom" if include_geom else ""

        sql = f"""
            SELECT
                a.{quote_col(src_id_col)}
                {', ' + src_fields_sql if src_fields_sql else ''},
                ST_Area({src_4326}::geography)::float AS original_area_m2,
                ST_Area({diff_expr}::geography)::float AS difference_area_m2,
                COUNT(b.{quote_col(sub.get('id_col', 'id'))})::int AS subtracted_features
                {geom_sql}
            FROM {qualified_table(src)} a
            LEFT JOIN {qualified_table(sub)} b
                ON {sub_where_sql}
                AND ST_Intersects({src_4326}, {sub_4326})
            WHERE a.{quote_col(src_id_col)} = %s
              AND a.{quote_col(src_geom_col)} IS NOT NULL
            GROUP BY a.{quote_col(src_id_col)}{', ' + src_fields_sql if src_fields_sql else ''}, a.{quote_col(src_geom_col)}
        """

        # Reordenar params: source_id al final (WHERE)
        params_reordered = params[1:] + [source_id]

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params_reordered)
            rows = cur.fetchall()
            if not rows:
                return ToolResult(ok=False, error=f"Feature not found: {src_name} id={source_id}")
            cols_desc = [c[0] for c in cur.description]
            result_row = dict(zip(cols_desc, rows[0]))

        from agents_gis.service import _json_safe
        result_row = {k: _json_safe(v) for k, v in result_row.items()}

        return ToolResult(
            ok=True,
            data={
                "source_layer": src_name,
                "source_id": source_id,
                "subtract_layer": sub_name,
                "original_area_m2": result_row.get("original_area_m2"),
                "difference_area_m2": result_row.get("difference_area_m2"),
                "subtracted_features": result_row.get("subtracted_features", 0),
                "difference_geom": result_row.get("difference_geom"),
                "attributes": {k: v for k, v in result_row.items()
                               if k not in ("original_area_m2", "difference_area_m2",
                                            "subtracted_features", "difference_geom")},
            },
        )
