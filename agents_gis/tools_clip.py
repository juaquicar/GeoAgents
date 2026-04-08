"""
Tool: spatial.clip
Recorta los features de source_layer a la geometría de un feature de clip_layer
(o a un bbox), devolviendo la geometría intersectada exacta.

Útil para:
  - "Dame los tramos de red que pasan por esta parcela"
  - "Recorta los edificios al límite del distrito"
  - "¿Qué parte de la zona verde está dentro de la parcela X?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialClipTool(BaseTool):
    name = "spatial.clip"
    description = (
        "Recorta (clip) los features de source_layer a la geometría de un feature concreto "
        "de clip_layer (o a un bbox). Devuelve la geometría intersectada exacta (ST_Intersection), "
        "no el feature completo. Ideal para análisis de solapamiento preciso."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa a recortar.",
            },
            "clip_layer": {
                "type": "string",
                "description": "Capa que proporciona la geometría de recorte.",
            },
            "clip_id": {
                "description": "ID del feature de clip_layer usado como geometría de recorte.",
            },
            "bbox": {
                "type": "object",
                "description": "Alternativa a clip_layer+clip_id: recorte por bbox WGS84.",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "source_filters": {"type": "object"},
            "include_geom": {
                "type": "boolean",
                "description": "Si true, incluye la geometría recortada (GeoJSON). Defecto true.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de features recortados a devolver (1-200, defecto 50).",
            },
        },
        "required": ["source_layer"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        if not src_name:
            return ToolResult(ok=False, error="source_layer is required")

        clip_layer_name = (args.get("clip_layer") or "").strip()
        clip_id = args.get("clip_id")
        bbox = args.get("bbox")

        if not clip_layer_name and not bbox:
            return ToolResult(ok=False, error="Either clip_layer+clip_id or bbox is required")
        if clip_layer_name and not clip_id:
            return ToolResult(ok=False, error="clip_id is required when clip_layer is provided")

        src = _get_layer_cfg(src_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")

        clip = None
        if clip_layer_name:
            clip = _get_layer_cfg(clip_layer_name)
            if not clip:
                return ToolResult(ok=False, error=f"Unknown clip_layer: {clip_layer_name}")

        include_geom = args.get("include_geom", True)
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        src_filters = args.get("source_filters") or {}

        src_id = src.get("id_col", "id")
        src_fields = src.get("fields", [])
        src_filter_fields = set(src.get("filter_fields") or []) | {src_id}
        src_geom_col = src.get("geom_col", "the_geom")
        src_srid = get_layer_srid(src)
        src_g = f'a.{quote_col(src_geom_col)}'
        src_4326 = geom_to_4326(src_g, src_srid)

        params = []

        # Geometría de recorte
        if clip:
            clip_geom_col = clip.get("geom_col", "the_geom")
            clip_srid = get_layer_srid(clip)
            clip_g = f'c.{quote_col(clip_geom_col)}'
            clip_4326 = geom_to_4326(clip_g, clip_srid)
            clip_id_col = clip.get("id_col", "id")
            clip_subquery = (
                f"(SELECT {geom_to_4326(quote_col(clip_geom_col), clip_srid)} AS geom "
                f" FROM {qualified_table(clip)} "
                f" WHERE {quote_col(clip_id_col)} = %s LIMIT 1)"
            )
            params.append(clip_id)
            clip_geom_expr = "clip.geom"
        else:
            clip_geom_expr = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        # WHERE source
        src_where = [f"a.{quote_col(src_geom_col)} IS NOT NULL"]
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
        intersection_expr = f"ST_Intersection({src_4326}, {clip_geom_expr})"
        geom_sql = f", ST_AsGeoJSON({intersection_expr}) AS clipped_geom" if include_geom else ""

        if clip:
            from_sql = f"""
                FROM {qualified_table(src)} a
                JOIN {clip_subquery} clip ON ST_Intersects({src_4326}, clip.geom)
            """
        else:
            from_sql = f"""
                FROM {qualified_table(src)} a
                WHERE ST_Intersects({src_4326}, {clip_geom_expr})
            """
            # bbox params already in params, add them again for the intersects check
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        if clip:
            where_sql = " AND ".join(src_where)
            sql = f"""
                SELECT {src_select_sql},
                       ST_Area({intersection_expr}::geography)::float AS clipped_area_m2,
                       ST_Length({intersection_expr}::geography)::float AS clipped_length_m
                       {geom_sql}
                {from_sql}
                WHERE {where_sql}
                  AND NOT ST_IsEmpty({intersection_expr})
                LIMIT %s
            """
        else:
            # bbox used twice already — restructure
            bbox_expr = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
            params_base = []
            src_where_base = [f"a.{quote_col(src_geom_col)} IS NOT NULL"]
            src_filters_base = {k: v for k, v in (args.get("source_filters") or {}).items()
                                if v is not None and not isinstance(v, dict)}
            bbox_params = [float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])]
            for k, v in src_filters_base.items():
                if isinstance(v, list):
                    placeholders = ", ".join(["%s"] * len(v))
                    src_where_base.append(f"a.{quote_col(k)} IN ({placeholders})")
                    params_base.extend(v)
                else:
                    src_where_base.append(f"a.{quote_col(k)} = %s")
                    params_base.append(v)

            intersection_expr2 = f"ST_Intersection({src_4326}, {bbox_expr})"
            geom_sql2 = f", ST_AsGeoJSON({intersection_expr2}) AS clipped_geom" if include_geom else ""
            where_sql = " AND ".join(src_where_base)
            sql = f"""
                SELECT {src_select_sql},
                       ST_Area({intersection_expr2}::geography)::float AS clipped_area_m2,
                       ST_Length({intersection_expr2}::geography)::float AS clipped_length_m
                       {geom_sql2}
                FROM {qualified_table(src)} a
                WHERE {where_sql}
                  AND ST_Intersects({src_4326}, {bbox_expr})
                  AND NOT ST_IsEmpty({intersection_expr2})
                LIMIT %s
            """
            params = bbox_params + params_base + bbox_params + bbox_params + [limit]

        if clip:
            params.append(limit)

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params)
            items = _fetchall_dict(cur)

        return ToolResult(
            ok=True,
            data={
                "source_layer": src_name,
                "clip_layer": clip_layer_name or None,
                "clip_id": clip_id,
                "bbox": bbox,
                "include_geom": include_geom,
                "count_total": len(items),
                "items": items,
            },
        )
