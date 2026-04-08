"""
Tool: spatial.grid_stats
Divide el bbox en una cuadrícula regular y cuenta (o agrega) features
de una capa por celda. Útil para análisis de densidad y distribución espacial.

Útil para:
  - "¿Dónde se concentran los incidentes?"
  - "Densidad de farolas por cuadrícula de 100m"
  - "Distribución espacial de los activos"
"""
import math

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326,
)

_MAX_CELLS = 10_000


@register_tool
class SpatialGridStatsTool(BaseTool):
    name = "spatial.grid_stats"
    description = (
        "Divide el bbox en una cuadrícula regular de celdas y cuenta (o agrega) "
        "features de una capa por celda. Devuelve solo las celdas con elementos. "
        "Ideal para análisis de densidad, mapas de calor y distribución espacial."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "bbox": {
                "type": "object",
                "description": "Área de análisis (WGS84). Requerida.",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "cell_size_m": {
                "type": "number",
                "description": "Tamaño de celda en metros. Defecto 100. Mínimo 10.",
            },
            "filters": {"type": "object"},
            "agg_field": {
                "type": "string",
                "description": "Campo numérico para calcular SUM por celda además del COUNT.",
            },
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

        bbox = args.get("bbox")
        if not bbox:
            return ToolResult(ok=False, error="bbox is required")

        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        cell_size_m = max(10.0, float(args.get("cell_size_m") or 100.0))
        filters = args.get("filters") or {}
        agg_field = (args.get("agg_field") or "").strip() or None

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        filter_fields = set(layer.get("filter_fields") or [])
        all_fields = set(layer.get("fields") or []) | filter_fields
        id_col = layer.get("id_col", "id")
        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)

        if agg_field and agg_field not in all_fields:
            return ToolResult(ok=False, error=f"agg_field not in layer fields: {agg_field}")

        # Calcular cols/rows aproximados (1° lat ≈ 111,320 m)
        mid_lat = (south + north) / 2.0
        deg_per_m_lat = 1.0 / 111_320.0
        deg_per_m_lon = 1.0 / (111_320.0 * max(math.cos(math.radians(mid_lat)), 0.001))

        cols = max(1, round((east - west) / (cell_size_m * deg_per_m_lon)))
        rows = max(1, round((north - south) / (cell_size_m * deg_per_m_lat)))

        if cols * rows > _MAX_CELLS:
            # Ajustar para no superar el máximo
            factor = math.sqrt(cols * rows / _MAX_CELLS)
            cols = max(1, round(cols / factor))
            rows = max(1, round(rows / factor))

        geom_4326 = geom_to_4326(quote_col(geom_col), srid)
        table = qualified_table(layer)

        # WHERE para features
        feat_where = [f"{quote_col(geom_col)} IS NOT NULL"]
        params: list = []

        filters = {k: v for k, v in filters.items() if v is not None and not isinstance(v, dict)}
        for k in filters:
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")
        for k, v in filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                feat_where.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                feat_where.append(f"{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        feat_where_sql = " AND ".join(feat_where)

        agg_select = f", SUM({quote_col(agg_field)}) AS agg_sum" if agg_field else ""

        sql = f"""
            WITH grid AS (
                SELECT
                    i, j,
                    ST_MakeEnvelope(
                        %s + i * (%s - %s) / %s::float,
                        %s + j * (%s - %s) / %s::float,
                        %s + (i + 1) * (%s - %s) / %s::float,
                        %s + (j + 1) * (%s - %s) / %s::float,
                        4326
                    ) AS cell_geom
                FROM generate_series(0, %s - 1) i,
                     generate_series(0, %s - 1) j
            )
            SELECT
                g.i AS col,
                g.j AS row,
                COUNT(f.{quote_col(id_col)})::int AS count
                {agg_select},
                ST_AsGeoJSON(g.cell_geom) AS cell_geom_json
            FROM grid g
            LEFT JOIN {table} f
                ON f.{quote_col(geom_col)} IS NOT NULL
                AND ST_Intersects({geom_4326}, g.cell_geom)
                AND {feat_where_sql}
            GROUP BY g.i, g.j, g.cell_geom
            HAVING COUNT(f.{quote_col(id_col)}) > 0
            ORDER BY count DESC
        """

        # Parámetros del grid (cols/rows replicated for each coord)
        grid_params = [
            west, east, west, cols,   # x min
            south, north, south, rows, # y min
            west, east, west, cols,   # x max
            south, north, south, rows, # y max
            cols, rows,
        ]

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, grid_params + params)
            cells = _fetchall_dict(cur)

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "cell_size_m": cell_size_m,
                "grid_cols": cols,
                "grid_rows": rows,
                "non_empty_cells": len(cells),
                "agg_field": agg_field,
                "cells": cells,
            },
        )
