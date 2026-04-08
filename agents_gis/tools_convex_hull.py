"""
Tool: spatial.convex_hull
Calcula la envolvente convexa (convex hull) de un conjunto de features de una capa.

Útil para preguntas como:
  - "¿Cuál es el área que ocupan las incidencias?"
  - "Dibuja el contorno que envuelve todos los activos de la zona"
  - "¿Cuál es la extensión de los puntos de la capa farolas?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialConvexHullTool(BaseTool):
    name = "spatial.convex_hull"
    description = (
        "Calcula la envolvente convexa (ST_ConvexHull) de todos los features de una capa "
        "o de un subconjunto filtrado. Devuelve el polígono GeoJSON resultante, su área en m², "
        "el número de features incluidos y el centroide."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa (de gis_layers_catalog).",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial opcional (WGS84).",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "filters": {
                "type": "object",
                "description": "Filtros de atributo opcionales {campo: valor}.",
            },
            "include_geom": {
                "type": "boolean",
                "description": "Si true, incluye la geometría GeoJSON del hull.",
            },
        },
        "required": ["layer"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        bbox = args.get("bbox")
        filters = args.get("filters") or {}
        include_geom = bool(args.get("include_geom", True))

        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        geom_4326 = geom_to_4326(qgeom, srid)
        filter_fields = set(layer.get("filter_fields") or []) | {layer.get("id_col", "id")}

        where_clauses = [f"{qgeom} IS NOT NULL"]
        params: list = []

        if bbox:
            env = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")
        filters = {k: v for k, v in filters.items() if v is not None and not isinstance(v, dict)}
        for k in filters:
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")
        for k, v in filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                where_clauses.append(f"{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        where_sql = " AND ".join(where_clauses)
        hull_geom = f"ST_ConvexHull(ST_Collect({geom_4326}))"

        select_parts = [
            f"COUNT(*)::int AS feature_count",
            f"ST_Area({hull_geom}::geography)::float AS hull_area_m2",
            f"ST_X(ST_Centroid({hull_geom}))::float AS centroid_lon",
            f"ST_Y(ST_Centroid({hull_geom}))::float AS centroid_lat",
        ]
        if include_geom:
            select_parts.append(f"ST_AsGeoJSON({hull_geom}) AS hull_geom")

        sql = f"SELECT {', '.join(select_parts)} FROM {table} WHERE {where_sql}"

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()

        if not row or row[0] == 0:
            return ToolResult(ok=False, error="No features found to compute convex hull")

        result = dict(zip(cols, row))
        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": bbox,
                "filters": filters,
                "feature_count": result["feature_count"],
                "hull_area_m2": result["hull_area_m2"],
                "centroid_lon": result["centroid_lon"],
                "centroid_lat": result["centroid_lat"],
                **({"hull_geom": result["hull_geom"]} if include_geom else {}),
            },
        )
