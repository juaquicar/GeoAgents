"""
Tool: spatial.count_within
Para cada feature de source_layer, cuenta cuántos features de target_layer
están contenidos en su interior (ST_Within).

Útil para preguntas como:
  - "¿Cuántas farolas hay en cada zona verde?"
  - "¿Cuántos incidentes por parcela?"
  - "¿Cuántos árboles tiene cada rodal?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


def _build_attr_where(filters, filter_fields, alias, params):
    """Construye cláusulas WHERE de atributo para una capa con alias de tabla."""
    clauses = []
    filters = {k: v for k, v in (filters or {}).items()
               if v is not None and not isinstance(v, dict)}
    for k, v in filters.items():
        if k not in filter_fields:
            raise ValueError(f"filter not allowed: {k}")
        col = f"{alias}.{quote_col(k)}"
        if isinstance(v, list):
            if not v:
                continue
            placeholders = ", ".join(["%s"] * len(v))
            clauses.append(f"{col} IN ({placeholders})")
            params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
        else:
            clauses.append(f"{col} = %s")
            params.append(str(v) if isinstance(v, (int, float)) else v)
    return clauses


@register_tool
class SpatialCountWithinTool(BaseTool):
    name = "spatial.count_within"
    description = (
        "Para cada feature de source_layer, cuenta cuántos features de target_layer "
        "están dentro de su geometría (ST_Within). Devuelve un recuento por feature "
        "de la capa contenedora. Ideal para preguntas del tipo '¿cuántos X hay en cada Y?'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa contenedora (p.ej. zonas_verdes, parcelas). Suele ser polígonos.",
            },
            "target_layer": {
                "type": "string",
                "description": "Capa de elementos a contar (p.ej. farolas, árboles).",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial opcional sobre source_layer (WGS84).",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "source_filters": {"type": "object"},
            "target_filters": {"type": "object"},
            "min_count": {
                "type": "integer",
                "description": "Solo devuelve features con al menos N elementos target dentro. Defecto 0.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de features source a devolver (1-200, defecto 50).",
            },
        },
        "required": ["source_layer", "target_layer"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        tgt_name = (args.get("target_layer") or "").strip()
        if not src_name or not tgt_name:
            return ToolResult(ok=False, error="source_layer and target_layer are required")

        src = _get_layer_cfg(src_name)
        tgt = _get_layer_cfg(tgt_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")
        if not tgt:
            return ToolResult(ok=False, error=f"Unknown target_layer: {tgt_name}")

        bbox = args.get("bbox")
        min_count = max(0, int(args.get("min_count") or 0))
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        src_id = src.get("id_col", "id")
        src_fields = src.get("fields", [])
        src_filter_fields = set(src.get("filter_fields") or []) | {src_id}
        tgt_id = tgt.get("id_col", "id")
        tgt_filter_fields = set(tgt.get("filter_fields") or []) | {tgt_id}

        src_geom_col = src.get("geom_col", "the_geom")
        tgt_geom_col = tgt.get("geom_col", "the_geom")
        src_srid = get_layer_srid(src)
        tgt_srid = get_layer_srid(tgt)

        src_g = f'a.{quote_col(src_geom_col)}'
        tgt_g = f'b.{quote_col(tgt_geom_col)}'
        src_4326 = geom_to_4326(src_g, src_srid)
        tgt_4326 = geom_to_4326(tgt_g, tgt_srid)

        params = []

        # WHERE source
        src_where = [f"a.{quote_col(src_geom_col)} IS NOT NULL"]
        if bbox:
            env = bbox_in_layer_srid(src_srid)
            src_where.append(f"ST_Intersects(a.{quote_col(src_geom_col)}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        try:
            src_where += _build_attr_where(
                args.get("source_filters"), src_filter_fields, "a", params)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # JOIN target conditions
        tgt_join = [
            f"ST_Within({tgt_4326}, {src_4326})",
            f"b.{quote_col(tgt_geom_col)} IS NOT NULL",
        ]
        try:
            tgt_join += _build_attr_where(
                args.get("target_filters"), tgt_filter_fields, "b", params)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        src_select_cols = [f"a.{quote_col(src_id)}"] + [f"a.{quote_col(f)}" for f in src_fields]
        src_select_sql = ", ".join(src_select_cols)
        group_sql = ", ".join(src_select_cols + [f"a.{quote_col(src_geom_col)}"])
        having_sql = f"HAVING COUNT(b.{quote_col(tgt_id)}) >= {min_count}" if min_count > 0 else ""

        sql = f"""
            SELECT
                {src_select_sql},
                ST_X(ST_Centroid({src_4326}))::float AS centroid_lon,
                ST_Y(ST_Centroid({src_4326}))::float AS centroid_lat,
                COUNT(b.{quote_col(tgt_id)})::int AS count_within
            FROM {qualified_table(src)} a
            LEFT JOIN {qualified_table(tgt)} b
                ON {" AND ".join(tgt_join)}
            WHERE {" AND ".join(src_where)}
            GROUP BY {group_sql}
            {having_sql}
            ORDER BY count_within DESC
            LIMIT %s
        """
        params.append(limit)

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params)
            items = _fetchall_dict(cur)

        return ToolResult(
            ok=True,
            data={
                "source_layer": src_name,
                "target_layer": tgt_name,
                "limit": limit,
                "min_count": min_count,
                "items": items,
                "count_total": len(items),
            },
        )
