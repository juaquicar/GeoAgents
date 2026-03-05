from django.conf import settings
from django.db import connection

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


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
        },
        "required": ["bbox"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        bbox = args["bbox"]
        zoom = args.get("zoom")
        per_layer_limit = int(args.get("per_layer_limit") or 10)
        per_layer_limit = max(1, min(per_layer_limit, 50))  # hard limit

        layers = getattr(settings, "AGENTS_GIS_LAYERS", [])
        if not layers:
            return ToolResult(ok=False, error="AGENTS_GIS_LAYERS is empty")

        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        # Envelope parametrizado (valores seguros)
        envelope_sql = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"

        out_layers = []
        with connection.cursor() as cur:
            for layer in layers:
                # Identifiers SOLO desde settings
                table = layer["table"]
                geom_col = layer.get("geom_col", "the_geom")
                id_col = layer.get("id_col", "id")
                fields = layer.get("fields", [])

                # Count
                count_sql = f"""
                    SELECT COUNT(*)::int AS count
                    FROM {table}
                    WHERE {geom_col} IS NOT NULL
                      AND ST_Intersects({geom_col}, {envelope_sql})
                """
                cur.execute(count_sql, [west, south, east, north])
                count = cur.fetchone()[0]

                # Sample
                select_cols = [id_col] + list(fields)
                select_fields_sql = ", ".join(select_cols)

                sample_sql = f"""
                    SELECT
                      {select_fields_sql},
                      ST_X(ST_Centroid({geom_col}))::float AS lon,
                      ST_Y(ST_Centroid({geom_col}))::float AS lat
                    FROM {table}
                    WHERE {geom_col} IS NOT NULL
                      AND ST_Intersects({geom_col}, {envelope_sql})
                    LIMIT %s
                """
                cur.execute(sample_sql, [west, south, east, north, per_layer_limit])
                samples = _fetchall_dict(cur)

                out_layers.append(
                    {
                        "name": layer.get("name", table),
                        "table": table,
                        "count": count,
                        "samples": samples,
                    }
                )

        return ToolResult(
            ok=True,
            data={
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "zoom": zoom,
                "per_layer_limit": per_layer_limit,
                "layers": out_layers,
            },
        )