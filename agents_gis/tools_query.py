from django.db import connection

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import _fetchall_dict, _get_layer_cfg


@register_tool
class SpatialQueryLayerTool(BaseTool):
    name = "spatial.query_layer"
    description = "Consulta una capa concreta (AGENTS_GIS_LAYERS) dentro de un bbox con filtros allowlist."
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
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
            "random_sample": {"type": "boolean"},
            "include_geom": {"type": "boolean"},
            "simplify_meters": {"type": "number"},
            "filters": {"type": "object"},  # { "field": value, ... } (solo igualdad)
        },
        "required": ["layer", "bbox"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        bbox = args["bbox"]
        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        offset = int(args.get("offset") or 0)
        offset = max(0, offset)

        random_sample = bool(args.get("random_sample") or False)
        include_geom = bool(args.get("include_geom") or False)
        simplify_meters = float(args.get("simplify_meters") or 0.0)
        simplify_meters = max(0.0, min(simplify_meters, 50.0))

        filters = args.get("filters") or {}
        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        table = layer["table"]
        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields", [])
        filter_fields = set(layer.get("filter_fields", []) or [])

        # Validar que filters solo usa campos permitidos
        for k in filters.keys():
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")

        envelope_sql = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"

        # WHERE base
        where_clauses = [
            f"{geom_col} IS NOT NULL",
            f"ST_Intersects({geom_col}, {envelope_sql})",
        ]
        params = [west, south, east, north]

        # Filtros igualdad parametrizados (valores seguros)
        for k, v in filters.items():
            # k es identifier trusted (allowlist)
            where_clauses.append(f"{k} = %s")
            params.append(v)

        where_sql = " AND ".join(where_clauses)
        order_sql = "ORDER BY random()" if random_sample else ""

        # COUNT total (sin limit/offset)
        count_sql = f"""
            SELECT COUNT(*)::int AS count
            FROM {table}
            WHERE {where_sql}
        """

        # SELECT items
        select_cols = [id_col] + list(fields)
        select_fields_sql = ", ".join(select_cols)

        centroid_sql = f"""
            ST_X(ST_Centroid({geom_col}))::float AS lon,
            ST_Y(ST_Centroid({geom_col}))::float AS lat
        """

        metrics_sql = f"""
            GeometryType({geom_col}) AS geom_type,
            ST_Dimension({geom_col})::int AS geom_dim,
            CASE
              WHEN ST_Dimension({geom_col}) = 1 THEN ST_Length({geom_col}::geography)::float
              ELSE 0::float
            END AS length_m,
            CASE
              WHEN ST_Dimension({geom_col}) = 2 THEN ST_Area({geom_col}::geography)::float
              ELSE 0::float
            END AS area_m2
        """

        geom_geojson_sql = ""
        geom_params_prefix = []
        if include_geom:
            if simplify_meters > 0:
                geom_geojson_sql = f""",
                  ST_AsGeoJSON(
                    ST_Transform(
                      ST_SimplifyPreserveTopology(
                        ST_Transform({geom_col}, 3857),
                        %s
                      ),
                      4326
                    )
                  ) AS geom_geojson
                """
                geom_params_prefix = [simplify_meters]
            else:
                geom_geojson_sql = f""",
                  ST_AsGeoJSON({geom_col}) AS geom_geojson
                """

        items_sql = f"""
            SELECT
              {select_fields_sql},
              {centroid_sql},
              {metrics_sql}
              {geom_geojson_sql}
            FROM {table}
            WHERE {where_sql}
            {order_sql}
            LIMIT %s OFFSET %s
        """

        with connection.cursor() as cur:
            # count
            cur.execute(count_sql, params)
            count_total = cur.fetchone()[0]

            # items
            items_params = []
            items_params.extend(geom_params_prefix)
            items_params.extend(params)
            items_params.extend([limit, offset])

            cur.execute(items_sql, items_params)
            items = _fetchall_dict(cur)

        # Hard guard geom size
        if include_geom:
            for it in items:
                g = it.get("geom_geojson")
                if isinstance(g, str) and len(g) > 20_000:
                    it["geom_geojson"] = g[:20_000] + "...(truncated)"

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "filters": filters,
                "limit": limit,
                "offset": offset,
                "count_total": count_total,
                "items": items,
                "include_geom": include_geom,
                "simplify_meters": simplify_meters,
                "random_sample": random_sample,
            },
        )