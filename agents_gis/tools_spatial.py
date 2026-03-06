from django.conf import settings
from django.db import connection

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import _fetchall_dict

@register_tool
class SpatialSummaryTool(BaseTool):
    name = "spatial.summary"
    description = "Resumen espacial por capas (AGENTS_GIS_LAYERS) para un bbox en EPSG:4326."
    input_schema = {
        "type": "object",
        "properties": {
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
            "zoom": {"type": "integer"},
            "per_layer_limit": {"type": "integer"},
            "layers": {"type": "array"},  # lista de nombres de capa (layer["name"])
            "random_sample": {"type": "boolean"},  # ORDER BY random()
            "include_geom": {"type": "boolean"},  # incluir geom_geojson (simplificado)
            "simplify_meters": {"type": "number"}  # simplificación aproximada en metros
        },
        "required": ["bbox"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        bbox = args["bbox"]
        zoom = args.get("zoom")
        per_layer_limit = int(args.get("per_layer_limit") or 10)
        per_layer_limit = max(1, min(per_layer_limit, 50))  # hard limit

        requested_layers = args.get("layers")  # e.g. ["demo_points"]
        random_sample = bool(args.get("random_sample") or False)
        include_geom = bool(args.get("include_geom") or False)

        simplify_meters = args.get("simplify_meters")
        if simplify_meters is None:
            simplify_meters = 0.0
        simplify_meters = float(simplify_meters)
        simplify_meters = max(0.0, min(simplify_meters, 50.0))  # limit razonable

        layers_cfg = getattr(settings, "AGENTS_GIS_LAYERS", [])
        if not layers_cfg:
            return ToolResult(ok=False, error="AGENTS_GIS_LAYERS is empty")

        # Filtrado por nombre (si el usuario lo pide)
        if requested_layers:
            requested_set = set(str(x) for x in requested_layers)
            layers_cfg = [l for l in layers_cfg if l.get("name") in requested_set]

        if not layers_cfg:
            return ToolResult(ok=False, error="No matching layers (check args.layers)")

        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        envelope_sql = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
        order_sql = "ORDER BY random()" if random_sample else ""

        out_layers = []
        with connection.cursor() as cur:
            for layer in layers_cfg:
                table = layer["table"]
                geom_col = layer.get("geom_col", "the_geom")
                id_col = layer.get("id_col", "id")
                fields = layer.get("fields", [])

                # 1) Count
                count_sql = f"""
                    SELECT COUNT(*)::int AS count
                    FROM {table}
                    WHERE {geom_col} IS NOT NULL
                      AND ST_Intersects({geom_col}, {envelope_sql})
                """
                cur.execute(count_sql, [west, south, east, north])
                count = cur.fetchone()[0]

                # 2) Distribución simple de tipos de geometría
                # (útil para saber si es point/line/polygon sin mirar samples)
                geom_types_sql = f"""
                    SELECT GeometryType({geom_col}) AS geom_type, COUNT(*)::int AS n
                    FROM {table}
                    WHERE {geom_col} IS NOT NULL
                      AND ST_Intersects({geom_col}, {envelope_sql})
                    GROUP BY GeometryType({geom_col})
                    ORDER BY n DESC
                    LIMIT 10
                """
                cur.execute(geom_types_sql, [west, south, east, north])
                geom_types = _fetchall_dict(cur)

                # 3) Sample
                select_cols = [id_col] + list(fields)
                select_fields_sql = ", ".join(select_cols)

                # Métricas: area/length en "geography" (aprox en metros) sin reproyectar
                # - length_m: para lines
                # - area_m2: para polygons
                # Para points será 0.
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

                # Centroid (para cualquier geom)
                centroid_sql = f"""
                    ST_X(ST_Centroid({geom_col}))::float AS lon,
                    ST_Y(ST_Centroid({geom_col}))::float AS lat
                """

                # Geom simplificada opcional (GeoJSON)
                geom_geojson_sql = ""
                if include_geom:
                    if simplify_meters > 0:
                        # simplificamos en 3857 por metros, y volvemos a 4326
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
                    else:
                        geom_geojson_sql = f""",
                          ST_AsGeoJSON({geom_col}) AS geom_geojson
                        """

                sample_sql = f"""
                    SELECT
                      {select_fields_sql},
                      {centroid_sql},
                      {metrics_sql}
                      {geom_geojson_sql}
                    FROM {table}
                    WHERE {geom_col} IS NOT NULL
                      AND ST_Intersects({geom_col}, {envelope_sql})
                    {order_sql}
                    LIMIT %s
                """

                params = [west, south, east, north]
                # si include_geom y simplify_meters > 0, añade ese param antes del envelope
                # ojo: en sample_sql, %s del simplify está ANTES que los del envelope
                if include_geom and simplify_meters > 0:
                    params = [simplify_meters] + params

                params = params + [per_layer_limit]

                cur.execute(sample_sql, params)
                samples = _fetchall_dict(cur)

                # Hard guard: recorta geom_geojson si se va de tamaño
                # (evita payloads gigantes por error)
                if include_geom:
                    for s in samples:
                        g = s.get("geom_geojson")
                        if isinstance(g, str) and len(g) > 20_000:
                            s["geom_geojson"] = g[:20_000] + "...(truncated)"

                out_layers.append(
                    {
                        "name": layer.get("name", table),
                        "table": table,
                        "count": count,
                        "geom_types": geom_types,
                        "samples": samples,
                    }
                )

        return ToolResult(
            ok=True,
            data={
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "zoom": zoom,
                "per_layer_limit": per_layer_limit,
                "random_sample": random_sample,
                "include_geom": include_geom,
                "simplify_meters": simplify_meters,
                "layers": out_layers,
            },
        )