"""
Tool: spatial.within_distance
Devuelve los features de la capa fuente que están a menos de X metros
de al menos un feature de la capa de referencia.

Útil para preguntas como:
  - "¿Qué parcelas están a menos de 50m de una zona de protección?"
  - "Farolas a menos de 100m de cualquier incidencia"
  - "¿Qué tramos de red pasan cerca de edificios catalogados?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialWithinDistanceTool(BaseTool):
    name = "spatial.within_distance"
    description = (
        "Devuelve los features de source_layer que se encuentran a menos de distance_m metros "
        "de al menos un feature de reference_layer (ST_DWithin en EPSG:3857). "
        "Útil para encontrar elementos de una capa que están cerca de los de otra."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa cuyos features se evalúan.",
            },
            "reference_layer": {
                "type": "string",
                "description": "Capa de referencia. Se comprueba si cada feature de source está cerca de alguno de esta capa.",
            },
            "distance_m": {
                "type": "number",
                "description": "Distancia máxima en metros.",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial sobre source_layer (WGS84).",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "source_filters": {
                "type": "object",
                "description": "Filtros de atributo sobre source_layer.",
            },
            "reference_filters": {
                "type": "object",
                "description": "Filtros de atributo sobre reference_layer.",
            },
            "include_min_distance": {
                "type": "boolean",
                "description": "Si true, incluye la distancia mínima al vecino más cercano de reference_layer.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de features a devolver (1-500, defecto 100).",
            },
        },
        "required": ["source_layer", "reference_layer", "distance_m"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        ref_name = (args.get("reference_layer") or "").strip()
        distance_m = args.get("distance_m")

        if not src_name:
            return ToolResult(ok=False, error="source_layer is required")
        if not ref_name:
            return ToolResult(ok=False, error="reference_layer is required")
        if not distance_m or float(distance_m) <= 0:
            return ToolResult(ok=False, error="distance_m must be greater than 0")

        distance_m = float(distance_m)

        src = _get_layer_cfg(src_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")
        ref = _get_layer_cfg(ref_name)
        if not ref:
            return ToolResult(ok=False, error=f"Unknown reference_layer: {ref_name}")

        bbox = args.get("bbox")
        src_filters = args.get("source_filters") or {}
        ref_filters = args.get("reference_filters") or {}
        include_min_dist = bool(args.get("include_min_distance", True))
        limit = int(args.get("limit") or 100)
        limit = max(1, min(limit, 500))

        # Configuración capa fuente
        src_geom_col = src.get("geom_col", "the_geom")
        src_id_col = src.get("id_col", "id")
        src_fields = src.get("fields") or []
        src_srid = get_layer_srid(src)
        src_table = qualified_table(src)
        src_qgeom = quote_col(src_geom_col)
        # Prefijo de tabla para evitar ambigüedad en subqueries correlated (EXISTS, min_dist)
        src_geom_4326 = geom_to_4326(f"src.{src_qgeom}", src_srid)
        src_filter_fields = set(src.get("filter_fields") or []) | {src_id_col}

        # Configuración capa referencia
        ref_geom_col = ref.get("geom_col", "the_geom")
        ref_id_col = ref.get("id_col", "id")
        ref_srid = get_layer_srid(ref)
        ref_table = qualified_table(ref)
        ref_qgeom = quote_col(ref_geom_col)
        ref_geom_4326 = geom_to_4326(f"ref.{ref_qgeom}", ref_srid)
        ref_filter_fields = set(ref.get("filter_fields") or []) | {ref_id_col}

        # WHERE source
        src_where = [f"src.{src_qgeom} IS NOT NULL"]
        params: list = []

        if bbox:
            env = bbox_in_layer_srid(src_srid)
            src_where.append(f"ST_Intersects(src.{src_qgeom}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        if not isinstance(src_filters, dict):
            return ToolResult(ok=False, error="source_filters must be an object")
        src_filters = {k: v for k, v in src_filters.items() if v is not None and not isinstance(v, dict)}
        for k in src_filters:
            if k not in src_filter_fields:
                return ToolResult(ok=False, error=f"source filter not allowed: {k}")
        for k, v in src_filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                src_where.append(f"src.{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                src_where.append(f"src.{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        # WHERE reference
        ref_where = [f"ref.{ref_qgeom} IS NOT NULL"]
        ref_params: list = []

        if not isinstance(ref_filters, dict):
            return ToolResult(ok=False, error="reference_filters must be an object")
        ref_filters = {k: v for k, v in ref_filters.items() if v is not None and not isinstance(v, dict)}
        for k in ref_filters:
            if k not in ref_filter_fields:
                return ToolResult(ok=False, error=f"reference filter not allowed: {k}")
        for k, v in ref_filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                ref_where.append(f"ref.{quote_col(k)} IN ({placeholders})")
                ref_params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                ref_where.append(f"ref.{quote_col(k)} = %s")
                ref_params.append(str(v) if isinstance(v, (int, float)) else v)

        src_where_sql = " AND ".join(src_where)
        ref_where_sql = " AND ".join(ref_where)

        src_attr_sel = ", ".join(f"src.{quote_col(f)}" for f in src_fields)
        src_attr_sel = (", " + src_attr_sel) if src_attr_sel else ""

        src_3857 = f"ST_Transform({src_geom_4326}, 3857)"
        ref_3857 = f"ST_Transform({ref_geom_4326}, 3857)"

        min_dist_sel = ""
        if include_min_dist:
            min_dist_sel = f""",
                (SELECT MIN(ST_Distance({src_3857}, {ref_3857}))
                 FROM {ref_table} ref
                 WHERE {ref_where_sql})::float AS min_distance_m"""

        sql = f"""
            SELECT
                src.{quote_col(src_id_col)} AS fid,
                ST_X({src_geom_4326})::float AS centroid_lon,
                ST_Y({src_geom_4326})::float AS centroid_lat
                {src_attr_sel}
                {min_dist_sel}
            FROM {src_table} src
            WHERE {src_where_sql}
              AND EXISTS (
                  SELECT 1 FROM {ref_table} ref
                  WHERE {ref_where_sql}
                    AND ST_DWithin({src_3857}, {ref_3857}, %s)
              )
            ORDER BY fid
            LIMIT %s
        """

        # Parámetros: primero source WHERE, luego ref params para min_dist (si aplica),
        # luego ref params para EXISTS, luego distance y limit
        if include_min_dist:
            all_params = params + ref_params + ref_params + [distance_m, limit]
        else:
            all_params = params + ref_params + [distance_m, limit]

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, all_params)
            rows = _fetchall_dict(cur)

        # Contar total sin LIMIT
        count_sql = f"""
            SELECT COUNT(DISTINCT src.{quote_col(src_id_col)})::int
            FROM {src_table} src
            WHERE {src_where_sql}
              AND EXISTS (
                  SELECT 1 FROM {ref_table} ref
                  WHERE {ref_where_sql}
                    AND ST_DWithin({src_3857}, {ref_3857}, %s)
              )
        """
        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, params + ref_params + [distance_m])
            total = cur.fetchone()[0]

        for row in rows:
            for k, v in row.items():
                try:
                    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                        row[k] = float(v)
                except Exception:
                    pass

        return ToolResult(
            ok=True,
            data={
                "source_layer": src_name,
                "reference_layer": ref_name,
                "distance_m": distance_m,
                "bbox": bbox,
                "total_within_distance": total,
                "returned": len(rows),
                "limit": limit,
                "features": rows,
            },
        )
