"""
Tool: spatial.voronoi
Genera polígonos de Voronoi a partir de una capa de puntos.
Cada polígono representa la zona más próxima a cada punto origen.

Útil para preguntas como:
  - "¿Cuál es el área de influencia de cada farola?"
  - "Crea zonas de cobertura para cada sensor"
  - "¿Qué zona atiende cada punto de servicio?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialVoronoiTool(BaseTool):
    name = "spatial.voronoi"
    description = (
        "Genera polígonos de Voronoi (ST_VoronoiPolygons) a partir de una capa de puntos. "
        "Cada polígono cubre el área más cercana a su punto origen. "
        "Devuelve cada polígono con su área en m² y los atributos del punto origen."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa de puntos (de gis_layers_catalog).",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial opcional (WGS84). Recorta los polígonos resultantes.",
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
                "description": "Si true, incluye la geometría GeoJSON de cada polígono Voronoi.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de polígonos a devolver (1-500, defecto 200).",
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

        geom_kind = (layer.get("geometry_kind") or "").lower()
        if geom_kind not in ("point", "multipoint", ""):
            return ToolResult(
                ok=False,
                error=f"spatial.voronoi requires a point layer, got geometry_kind='{geom_kind}'"
            )

        bbox = args.get("bbox")
        filters = args.get("filters") or {}
        include_geom = bool(args.get("include_geom", True))
        limit = int(args.get("limit") or 200)
        limit = max(1, min(limit, 500))

        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields") or []
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        geom_4326 = geom_to_4326(qgeom, srid)
        filter_fields = set(layer.get("filter_fields") or []) | {id_col}

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

        # Campos de atributos del punto origen
        attr_cols = ", ".join(f"pts.{quote_col(f)}" for f in fields) if fields else ""
        attr_select = f", {attr_cols}" if attr_cols else ""

        # Coordenadas del punto origen
        origin_coords = (
            f"ST_X({geom_4326})::float AS origin_lon, "
            f"ST_Y({geom_4326})::float AS origin_lat"
        )

        # Geometría Voronoi recortada al extent de los propios puntos (o al bbox)
        clip_expr = f"ST_ConvexHull(ST_Collect({geom_4326}))"

        geom_select = (
            f", ST_AsGeoJSON(ST_Intersection(vp.geom, {clip_expr}_hull))::text AS voronoi_geom"
            if include_geom else ""
        )

        # Usamos LATERAL para emparejar cada polígono voronoi con su punto origen
        sql = f"""
            WITH pts AS (
                SELECT
                    {quote_col(id_col)} AS fid,
                    {geom_4326} AS geom_4326
                    {attr_select.replace('pts.', '')}
                FROM {table}
                WHERE {where_sql}
            ),
            hull AS (
                SELECT ST_ConvexHull(ST_Collect(geom_4326)) AS geom_hull FROM pts
            ),
            voronoi AS (
                SELECT
                    (ST_Dump(ST_VoronoiPolygons(ST_Collect(geom_4326)))).geom AS geom
                FROM pts
            )
            SELECT
                pts.fid,
                ST_Area(ST_Intersection(vp.geom, hull.geom_hull)::geography)::float AS voronoi_area_m2
                {attr_select}
                {', ST_AsGeoJSON(ST_Intersection(vp.geom, hull.geom_hull))::text AS voronoi_geom' if include_geom else ''}
            FROM pts
            CROSS JOIN hull
            JOIN voronoi vp ON ST_Within(pts.geom_4326, vp.geom)
            ORDER BY pts.fid
            LIMIT %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params + [limit])
            rows = _fetchall_dict(cur)

        # Convertir Decimal → float
        for row in rows:
            for k, v in row.items():
                if k == "voronoi_geom":
                    continue
                try:
                    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                        row[k] = float(v)
                except Exception:
                    pass

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": bbox,
                "filters": filters,
                "polygon_count": len(rows),
                "include_geom": include_geom,
                "polygons": rows,
            },
        )
