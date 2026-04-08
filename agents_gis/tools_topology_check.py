"""
Tool: spatial.topology_check
Detecta problemas topológicos en una capa GIS:
  - Geometrías inválidas (ST_IsValid)
  - Geometrías vacías (ST_IsEmpty)
  - Self-intersections / rings degenerados (ST_IsValidReason)
  - Solapamientos entre features de la misma capa (ST_Overlaps)

Útil para preguntas como:
  - "¿Hay geometrías inválidas en la capa parcelas?"
  - "Comprueba la integridad topológica de la red"
  - "¿Existen solapamientos entre los rodales?"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialTopologyCheckTool(BaseTool):
    name = "spatial.topology_check"
    description = (
        "Detecta problemas topológicos en una capa: geometrías inválidas (ST_IsValid), "
        "geometrías vacías (ST_IsEmpty), y solapamientos entre features (ST_Overlaps). "
        "Devuelve un resumen con recuentos y la lista de features problemáticos."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa (de gis_layers_catalog).",
            },
            "check_overlaps": {
                "type": "boolean",
                "description": (
                    "Si true, detecta también solapamientos entre features de la misma capa. "
                    "Puede ser lento en capas grandes. Defecto false."
                ),
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
            "limit": {
                "type": "integer",
                "description": "Máximo de features con errores a devolver (1-200, defecto 50).",
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

        check_overlaps = bool(args.get("check_overlaps", False))
        bbox = args.get("bbox")
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields") or []
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        geom_4326 = geom_to_4326(qgeom, srid)
        qid = quote_col(id_col)

        where_clauses = []
        params: list = []

        if bbox:
            env = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

        where_sql = (" AND ".join(where_clauses)) if where_clauses else "TRUE"

        # 1. Conteo total de features en el rango
        count_sql = f"SELECT COUNT(*)::int FROM {table} WHERE {where_sql}"
        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, params)
            total_features = cur.fetchone()[0]

        # 2. Geometrías inválidas y vacías
        attr_sel = ", ".join(f"{quote_col(f)}" for f in fields[:5])  # max 5 campos para no saturar
        attr_sel = (", " + attr_sel) if attr_sel else ""

        invalid_sql = f"""
            SELECT
                {qid} AS fid,
                ST_X(ST_Centroid({geom_4326}))::float AS centroid_lon,
                ST_Y(ST_Centroid({geom_4326}))::float AS centroid_lat
                {attr_sel},
                CASE WHEN {qgeom} IS NULL THEN 'null_geometry'
                     WHEN ST_IsEmpty({qgeom}) THEN 'empty_geometry'
                     ELSE 'invalid: ' || ST_IsValidReason({qgeom})
                END AS issue
            FROM {table}
            WHERE {where_sql}
              AND (
                {qgeom} IS NULL
                OR ST_IsEmpty({qgeom})
                OR NOT ST_IsValid({qgeom})
              )
            LIMIT %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(invalid_sql, params + [limit])
            invalid_rows = _fetchall_dict(cur)

        # Contar total inválidas sin LIMIT
        count_invalid_sql = f"""
            SELECT COUNT(*)::int FROM {table}
            WHERE {where_sql}
              AND ({qgeom} IS NULL OR ST_IsEmpty({qgeom}) OR NOT ST_IsValid({qgeom}))
        """
        with get_gis_connection().cursor() as cur:
            cur.execute(count_invalid_sql, params)
            total_invalid = cur.fetchone()[0]

        # 3. Solapamientos (opcional, costoso)
        overlap_rows = []
        total_overlapping_pairs = 0

        if check_overlaps:
            overlap_sql = f"""
                SELECT
                    a.{qid} AS fid_a,
                    b.{qid} AS fid_b,
                    ST_Area(ST_Intersection(a.{geom_4326}, b.{geom_4326})::geography)::float AS overlap_area_m2
                FROM {table} a
                JOIN {table} b
                    ON a.{qid} < b.{qid}
                    AND ST_Overlaps(a.{qgeom}, b.{qgeom})
                WHERE {'a.' + where_sql.replace(f'{qgeom}', f'a.{qgeom}') if where_sql != 'TRUE' else 'TRUE'}
                LIMIT %s
            """
            try:
                with get_gis_connection().cursor() as cur:
                    cur.execute(overlap_sql, params + [limit])
                    overlap_rows = _fetchall_dict(cur)
                total_overlapping_pairs = len(overlap_rows)
            except Exception as e:
                overlap_rows = []
                total_overlapping_pairs = -1  # indica error en el cálculo

        # Limpiar Decimal
        for row in invalid_rows:
            for k, v in row.items():
                try:
                    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                        row[k] = float(v)
                except Exception:
                    pass

        is_clean = total_invalid == 0 and (not check_overlaps or total_overlapping_pairs == 0)

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": bbox,
                "total_features_checked": total_features,
                "is_topologically_clean": is_clean,
                "invalid_geometry_count": total_invalid,
                "invalid_features": invalid_rows,
                **(
                    {
                        "overlapping_pairs_count": total_overlapping_pairs,
                        "overlapping_pairs": overlap_rows,
                    }
                    if check_overlaps
                    else {}
                ),
            },
        )
