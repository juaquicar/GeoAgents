"""
Tool: spatial.spatial_join
Para cada feature de source_layer, adjunta atributos del feature de join_layer
que lo contiene (modo 'contains') o del más cercano (modo 'nearest').

Útil para:
  - "Añade el nombre del barrio a cada farola"
  - "¿En qué parcela está cada árbol?"
  - "Asigna la zona de mantenimiento más cercana a cada incidente"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialJoinTool(BaseTool):
    name = "spatial.spatial_join"
    description = (
        "Adjunta atributos de join_layer a cada feature de source_layer según relación espacial. "
        "Modo 'contains': busca qué feature de join_layer contiene a cada source. "
        "Modo 'nearest': busca el feature de join_layer más cercano a cada source."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa de features a enriquecer.",
            },
            "join_layer": {
                "type": "string",
                "description": "Capa de la que se toman los atributos.",
            },
            "join_type": {
                "type": "string",
                "enum": ["contains", "nearest"],
                "description": "'contains': el feature source debe estar dentro de un feature join. 'nearest': se une al más cercano.",
            },
            "join_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Campos de join_layer a adjuntar. Deben estar en filter_fields de join_layer.",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial sobre source_layer (WGS84).",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "source_filters": {"type": "object"},
            "limit": {
                "type": "integer",
                "description": "Máximo de features source a devolver (1-200, defecto 50).",
            },
        },
        "required": ["source_layer", "join_layer", "join_fields"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        join_name = (args.get("join_layer") or "").strip()
        if not src_name or not join_name:
            return ToolResult(ok=False, error="source_layer and join_layer are required")

        src = _get_layer_cfg(src_name)
        join = _get_layer_cfg(join_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")
        if not join:
            return ToolResult(ok=False, error=f"Unknown join_layer: {join_name}")

        join_type = (args.get("join_type") or "nearest").strip()
        if join_type not in ("contains", "nearest"):
            return ToolResult(ok=False, error="join_type must be 'contains' or 'nearest'")

        join_fields = args.get("join_fields") or []
        if not join_fields:
            return ToolResult(ok=False, error="join_fields must be a non-empty list")

        join_allowed = set(join.get("filter_fields") or []) | {join.get("id_col", "id")}
        for f in join_fields:
            if f not in join_allowed:
                return ToolResult(ok=False, error=f"join_field not allowed: {f}")

        bbox = args.get("bbox")
        src_filters = args.get("source_filters") or {}
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        src_id = src.get("id_col", "id")
        src_fields = src.get("fields", [])
        src_filter_fields = set(src.get("filter_fields") or []) | {src_id}
        src_geom_col = src.get("geom_col", "the_geom")
        join_geom_col = join.get("geom_col", "the_geom")
        src_srid = get_layer_srid(src)
        join_srid = get_layer_srid(join)

        src_g = f'a.{quote_col(src_geom_col)}'
        join_g = f'j.{quote_col(join_geom_col)}'
        src_4326 = geom_to_4326(src_g, src_srid)
        join_4326 = geom_to_4326(join_g, join_srid)

        params = []

        # WHERE source
        src_where = [f"a.{quote_col(src_geom_col)} IS NOT NULL"]
        if bbox:
            env = bbox_in_layer_srid(src_srid)
            src_where.append(f"ST_Intersects(a.{quote_col(src_geom_col)}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        src_filters = {k: v for k, v in src_filters.items()
                       if v is not None and not isinstance(v, dict)}
        for k in src_filters:
            if k not in src_filter_fields:
                return ToolResult(ok=False, error=f"source_filters field not allowed: {k}")
        for k, v in src_filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                src_where.append(f"a.{quote_col(k)} IN ({placeholders})")
                params.extend(v)
            else:
                src_where.append(f"a.{quote_col(k)} = %s")
                params.append(v)

        src_select = [f"a.{quote_col(src_id)}"] + [f"a.{quote_col(f)}" for f in src_fields]
        src_select_sql = ", ".join(src_select)
        join_select_sql = ", ".join(f"j.{quote_col(f)} AS {quote_col('join_' + f)}" for f in join_fields)
        centroid_sql = (
            f"ST_X(ST_Centroid({src_4326}))::float AS centroid_lon, "
            f"ST_Y(ST_Centroid({src_4326}))::float AS centroid_lat"
        )
        src_where_sql = " AND ".join(src_where)

        if join_type == "contains":
            sql = f"""
                SELECT {src_select_sql}, {centroid_sql}, {join_select_sql}
                FROM {qualified_table(src)} a
                LEFT JOIN {qualified_table(join)} j
                    ON ST_Within({src_4326}, {join_4326})
                    AND j.{quote_col(join_geom_col)} IS NOT NULL
                WHERE {src_where_sql}
                LIMIT %s
            """
        else:
            # nearest: LATERAL con operador <-> (geometry, no geography)
            join_fields_lateral = ", ".join(
                f"{quote_col(f)} AS {quote_col('join_' + f)}" for f in join_fields
            )
            sql = f"""
                SELECT {src_select_sql}, {centroid_sql}, {join_select_sql},
                       ST_Distance({src_4326}::geography, {join_4326}::geography)::float AS join_distance_m
                FROM {qualified_table(src)} a
                LEFT JOIN LATERAL (
                    SELECT {join_fields_lateral},
                           {quote_col(join_geom_col)}
                    FROM {qualified_table(join)}
                    WHERE {quote_col(join_geom_col)} IS NOT NULL
                    ORDER BY a.{quote_col(src_geom_col)} <-> {quote_col(join_geom_col)}
                    LIMIT 1
                ) j ON true
                WHERE {src_where_sql}
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
                "join_layer": join_name,
                "join_type": join_type,
                "join_fields": join_fields,
                "limit": limit,
                "count_total": len(items),
                "items": items,
            },
        )
