from django.db import connection

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import _fetchall_dict, _get_layer_cfg


@register_tool
class SpatialNearbyTool(BaseTool):
    name = "spatial.nearby"
    description = "Busca features cercanas a un punto (lon/lat) en una capa configurada, con radio en metros."
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "point": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                },
                "required": ["lon", "lat"],
            },
            "radius_m": {"type": "number"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "include_geom": {"type": "boolean"},
            "simplify_meters": {"type": "number"},
            "filters": {"type": "object"},
        },
        "required": ["layer", "point", "radius_m"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        pt = args.get("point") or {}
        lon = float(pt.get("lon"))
        lat = float(pt.get("lat"))

        radius_m = float(args.get("radius_m") or 0.0)
        radius_m = max(0.0, min(radius_m, 50_000.0))

        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        offset = int(args.get("offset") or 0)
        offset = max(0, offset)

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

        for k in filters.keys():
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")

        pt_geog_sql = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography"

        where_clauses = [
            f"{geom_col} IS NOT NULL",
            f"ST_DWithin({geom_col}::geography, {pt_geog_sql}, %s)",
        ]
        where_params = [lon, lat, radius_m]

        for k, v in filters.items():
            where_clauses.append(f"{k} = %s")
            where_params.append(v)

        where_sql = " AND ".join(where_clauses)

        count_sql = f"""
            SELECT COUNT(*)::int AS count
            FROM {table}
            WHERE {where_sql}
        """

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

        distance_sql = f"""
            ST_Distance({geom_col}::geography, {pt_geog_sql})::float AS distance_m
        """

        geom_geojson_sql = ""
        geom_params = []
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
                geom_params = [simplify_meters]
            else:
                geom_geojson_sql = f""",
                  ST_AsGeoJSON({geom_col}) AS geom_geojson
                """

        items_sql = f"""
            SELECT
              {select_fields_sql},
              {centroid_sql},
              {metrics_sql},
              {distance_sql}
              {geom_geojson_sql}
            FROM {table}
            WHERE {where_sql}
            ORDER BY distance_m ASC
            LIMIT %s OFFSET %s
        """

        with connection.cursor() as cur:
            cur.execute(count_sql, where_params)
            count_total = cur.fetchone()[0]

            # ORDEN CORRECTO DE PARAMS:
            # 1) distance_sql -> lon, lat
            # 2) geom simplification -> simplify_meters (si aplica)
            # 3) where_sql -> lon, lat, radius_m, filtros
            # 4) limit, offset
            items_params = []
            items_params.extend([lon, lat])      # distance_sql
            items_params.extend(geom_params)     # geom_geojson_sql si tiene %s
            items_params.extend(where_params)    # WHERE
            items_params.extend([limit, offset]) # LIMIT/OFFSET

            cur.execute(items_sql, items_params)
            items = _fetchall_dict(cur)

        if include_geom:
            for it in items:
                g = it.get("geom_geojson")
                if isinstance(g, str) and len(g) > 20_000:
                    it["geom_geojson"] = g[:20_000] + "...(truncated)"

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "point": {"lon": lon, "lat": lat},
                "radius_m": radius_m,
                "filters": filters,
                "limit": limit,
                "offset": offset,
                "count_total": count_total,
                "items": items,
                "include_geom": include_geom,
                "simplify_meters": simplify_meters,
            },
        )