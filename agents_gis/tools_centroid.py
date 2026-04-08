"""
Tool: spatial.centroid
Extrae el centroide (punto representativo) de cada feature de una capa.
Útil para obtener coordenadas representativas de polígonos o líneas,
visualizar distribución de elementos, o como entrada para otros análisis.

Ejemplos:
  - "Dame las coordenadas centrales de cada parcela"
  - "Obtén los centroides de los rodales para visualizarlos en el mapa"
  - "Calcula el punto central de cada zona verde"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialCentroidTool(BaseTool):
    name = "spatial.centroid"
    description = (
        "Extrae el centroide (punto representativo) de cada feature de una capa GIS. "
        "Devuelve coordenadas lon/lat del centroide junto con los atributos del elemento. "
        "Útil para obtener coordenadas de polígonos o líneas, o como entrada para análisis posteriores."
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
                    "west": {"type": "number"},
                    "south": {"type": "number"},
                    "east": {"type": "number"},
                    "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "filters": {
                "type": "object",
                "description": "Filtros de atributo opcionales. Mismo formato que spatial.query_layer.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de elementos a devolver (1-500, defecto 100).",
            },
            "offset": {
                "type": "integer",
                "description": "Desplazamiento para paginación.",
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
        limit = int(args.get("limit") or 100)
        limit = max(1, min(limit, 500))
        offset = int(args.get("offset") or 0)
        offset = max(0, offset)

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields", [])
        filter_fields = set(layer.get("filter_fields", []) or [])
        filter_fields.add(id_col)
        qgeom = quote_col(geom_col)
        geom4326 = geom_to_4326(qgeom, srid)

        # WHERE
        where_clauses = [f"{qgeom} IS NOT NULL"]
        params = []

        if bbox:
            west = float(bbox["west"])
            south = float(bbox["south"])
            east = float(bbox["east"])
            north = float(bbox["north"])
            envelope_sql = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {envelope_sql})")
            params.extend([west, south, east, north])

        filters = {k: v for k, v in filters.items() if v is not None and not isinstance(v, dict)}
        for k in filters:
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")
        for k, v in filters.items():
            if isinstance(v, list):
                if not v:
                    continue
                placeholders = ", ".join(["%s"] * len(v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                where_clauses.append(f"{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        where_sql = " AND ".join(where_clauses)

        # SELECT
        select_cols = [quote_col(id_col)] + [quote_col(f) for f in fields]
        select_fields_sql = ", ".join(select_cols)

        centroid_sql = f"""
            ST_X(ST_Centroid({geom4326}))::float AS centroid_lon,
            ST_Y(ST_Centroid({geom4326}))::float AS centroid_lat
        """

        geom_type_sql = f"GeometryType({qgeom}) AS geom_type"

        count_sql = f"SELECT COUNT(*)::int FROM {table} WHERE {where_sql}"

        items_sql = f"""
            SELECT
              {select_fields_sql},
              {centroid_sql},
              {geom_type_sql}
            FROM {table}
            WHERE {where_sql}
            ORDER BY {quote_col(id_col)}
            LIMIT %s OFFSET %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, params)
            count_total = cur.fetchone()[0]

            cur.execute(items_sql, params + [limit, offset])
            items = _fetchall_dict(cur)

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": bbox,
                "filters": filters,
                "count_total": count_total,
                "limit": limit,
                "offset": offset,
                "items": items,
            },
        )
