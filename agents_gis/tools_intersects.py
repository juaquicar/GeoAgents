from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table, quote_col,
    get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialIntersectsTool(BaseTool):
    name = "spatial.intersects"
    description = "Devuelve pares de features intersectadas entre dos capas configuradas dentro de un bbox."
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {"type": "string"},
            "target_layer": {"type": "string"},
            "bbox": {
                "type": "object",
                "properties": {
                    "west": {"type": "number"},
                    "south": {"type": "number"},
                    "east": {"type": "number"},
                    "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "include_geom": {"type": "boolean"},
            "simplify_meters": {"type": "number"},
            "source_filters": {"type": "object"},
            "target_filters": {"type": "object"},
        },
        "required": ["source_layer", "target_layer", "bbox"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        source_layer_name = (args.get("source_layer") or "").strip()
        target_layer_name = (args.get("target_layer") or "").strip()

        if not source_layer_name or not target_layer_name:
            return ToolResult(ok=False, error="source_layer and target_layer are required")

        source = _get_layer_cfg(source_layer_name)
        target = _get_layer_cfg(target_layer_name)

        if not source:
            return ToolResult(ok=False, error=f"Unknown source_layer: {source_layer_name}")
        if not target:
            return ToolResult(ok=False, error=f"Unknown target_layer: {target_layer_name}")

        bbox = args["bbox"]
        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        offset = int(args.get("offset") or 0)
        offset = max(0, offset)

        include_geom = bool(args.get("include_geom") or False)
        simplify_meters = float(args.get("simplify_meters") or 0.0)
        simplify_meters = max(0.0, min(simplify_meters, 50.0))

        source_filters = args.get("source_filters") or {}
        target_filters = args.get("target_filters") or {}

        if not isinstance(source_filters, dict):
            return ToolResult(ok=False, error="source_filters must be an object")
        if not isinstance(target_filters, dict):
            return ToolResult(ok=False, error="target_filters must be an object")

        s_table = qualified_table(source)
        s_geom = source.get("geom_col", "the_geom")
        s_srid = get_layer_srid(source)
        s_id = source.get("id_col", "id")
        s_fields = source.get("fields", [])
        s_filter_fields = set(source.get("filter_fields", []) or [])

        t_table = qualified_table(target)
        t_geom = target.get("geom_col", "the_geom")
        t_srid = get_layer_srid(target)
        t_id = target.get("id_col", "id")
        t_fields = target.get("fields", [])
        t_filter_fields = set(target.get("filter_fields", []) or [])

        qs_geom = quote_col(s_geom)
        qt_geom = quote_col(t_geom)
        s_geom4326 = geom_to_4326(f"s.{qs_geom}", s_srid)
        t_geom4326 = geom_to_4326(f"t.{qt_geom}", t_srid)

        for k in source_filters.keys():
            if k not in s_filter_fields:
                return ToolResult(ok=False, error=f"source filter not allowed: {k}")
        for k in target_filters.keys():
            if k not in t_filter_fields:
                return ToolResult(ok=False, error=f"target filter not allowed: {k}")

        s_envelope_sql = bbox_in_layer_srid(s_srid)
        t_envelope_sql = bbox_in_layer_srid(t_srid)

        params_base = [west, south, east, north, west, south, east, north]

        source_where = [
            f"s.{qs_geom} IS NOT NULL",
            f"ST_Intersects(s.{qs_geom}, {s_envelope_sql})",
        ]
        target_where = [
            f"t.{qt_geom} IS NOT NULL",
            f"ST_Intersects(t.{qt_geom}, {t_envelope_sql})",
        ]

        source_filter_params = []
        target_filter_params = []

        for k, v in source_filters.items():
            if not isinstance(v, (str, int, float, bool)) and v is not None:
                return ToolResult(ok=False, error=f"source filter value for '{k}' must be a scalar")
            source_where.append(f"s.{quote_col(k)} = %s")
            source_filter_params.append(v)

        for k, v in target_filters.items():
            if not isinstance(v, (str, int, float, bool)) and v is not None:
                return ToolResult(ok=False, error=f"target filter value for '{k}' must be a scalar")
            target_where.append(f"t.{quote_col(k)} = %s")
            target_filter_params.append(v)

        source_where_sql = " AND ".join(source_where)
        target_where_sql = " AND ".join(target_where)

        s_select = ", ".join(
            [f"s.{quote_col(s_id)} AS source_id"]
            + [f"s.{quote_col(f)} AS source_{f}" for f in s_fields]
        )
        t_select = ", ".join(
            [f"t.{quote_col(t_id)} AS target_id"]
            + [f"t.{quote_col(f)} AS target_{f}" for f in t_fields]
        )

        # Intersección en 4326 para métricas y GeoJSON
        intersection_4326 = f"ST_Transform(ST_Intersection(s.{qs_geom}, t.{qt_geom}), 4326)"

        geom_geojson_sql = ""
        geom_params = []
        if include_geom:
            if simplify_meters > 0:
                geom_geojson_sql = f"""
                    ,
                    ST_AsGeoJSON(
                      ST_Transform(
                        ST_SimplifyPreserveTopology(
                          ST_Transform(ST_Intersection(s.{qs_geom}, t.{qt_geom}), 3857),
                          %s
                        ),
                        4326
                      )
                    ) AS intersection_geojson
                """
                geom_params = [simplify_meters]
            else:
                geom_geojson_sql = f"""
                    ,
                    ST_AsGeoJSON({intersection_4326}) AS intersection_geojson
                """

        count_sql = f"""
            SELECT COUNT(*)::int
            FROM {s_table} s
            JOIN {t_table} t
              ON ST_Intersects(s.{qs_geom}, t.{qt_geom})
            WHERE {source_where_sql}
              AND {target_where_sql}
        """

        items_sql = f"""
            SELECT
              {s_select},
              {t_select},
              ST_X(ST_Centroid({s_geom4326}))::float AS source_lon,
              ST_Y(ST_Centroid({s_geom4326}))::float AS source_lat,
              ST_X(ST_Centroid({t_geom4326}))::float AS target_lon,
              ST_Y(ST_Centroid({t_geom4326}))::float AS target_lat,
              GeometryType({intersection_4326}) AS intersection_geom_type,
              CASE
                WHEN ST_Dimension({intersection_4326}) = 1
                  THEN ST_Length({intersection_4326}::geography)::float
                ELSE 0::float
              END AS intersection_length_m,
              CASE
                WHEN ST_Dimension({intersection_4326}) = 2
                  THEN ST_Area({intersection_4326}::geography)::float
                ELSE 0::float
              END AS intersection_area_m2
              {geom_geojson_sql}
            FROM {s_table} s
            JOIN {t_table} t
              ON ST_Intersects(s.{qs_geom}, t.{qt_geom})
            WHERE {source_where_sql}
              AND {target_where_sql}
            LIMIT %s OFFSET %s
        """

        count_params = []
        count_params.extend(params_base)
        count_params.extend(source_filter_params)
        count_params.extend(target_filter_params)

        items_params = []
        items_params.extend(geom_params)
        items_params.extend(params_base)
        items_params.extend(source_filter_params)
        items_params.extend(target_filter_params)
        items_params.extend([limit, offset])

        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, count_params)
            count_total = cur.fetchone()[0]

            cur.execute(items_sql, items_params)
            items = _fetchall_dict(cur)

        if include_geom:
            for it in items:
                g = it.get("intersection_geojson")
                if isinstance(g, str) and len(g) > 20_000:
                    it["intersection_geojson"] = g[:20_000] + "...(truncated)"

        return ToolResult(
            ok=True,
            data={
                "source_layer": source_layer_name,
                "target_layer": target_layer_name,
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "source_filters": source_filters,
                "target_filters": target_filters,
                "limit": limit,
                "offset": offset,
                "count_total": count_total,
                "items": items,
                "include_geom": include_geom,
                "simplify_meters": simplify_meters,
            },
        )