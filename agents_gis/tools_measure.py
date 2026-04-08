"""
Tool: spatial.measure
Calcula métricas geométricas de los features de una capa:
longitud (líneas), área y perímetro (polígonos), o simplemente cuenta puntos.

Útil para preguntas como:
  - "¿Cuántos metros de red hay en esta zona?"
  - "¿Cuál es el área total de las parcelas filtradas?"
  - "Dame la longitud media de los tramos por categoría"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialMeasureTool(BaseTool):
    name = "spatial.measure"
    description = (
        "Calcula métricas geométricas (longitud, área, perímetro) de los features de una capa. "
        "Devuelve totales y estadísticas (min/max/avg) por feature o agrupadas por campo. "
        "Las medidas se calculan en metros/m² usando ST_Length/ST_Area sobre geografía (EPSG:4326)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {
                "type": "string",
                "description": "Nombre de la capa (de gis_layers_catalog).",
            },
            "group_by": {
                "type": "string",
                "description": (
                    "Campo por el que agrupar las métricas (debe estar en filter_fields). "
                    "Si se omite, devuelve totales de toda la capa."
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
            "filters": {
                "type": "object",
                "description": "Filtros de atributo opcionales {campo: valor}.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de grupos a devolver cuando se usa group_by (1-200, defecto 50).",
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

        group_by = (args.get("group_by") or "").strip() or None
        bbox = args.get("bbox")
        filters = args.get("filters") or {}
        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))

        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
        geom_kind = (layer.get("geometry_kind") or "").lower()
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        geom_4326 = geom_to_4326(qgeom, srid)
        filter_fields = set(layer.get("filter_fields") or []) | {id_col}

        if group_by and group_by not in filter_fields:
            return ToolResult(ok=False, error=f"group_by field not allowed: {group_by}")

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

        # Determinar métricas según tipo de geometría
        is_line = any(k in geom_kind for k in ("line", "string"))
        is_poly = any(k in geom_kind for k in ("polygon",))

        metric_parts = ["COUNT(*)::int AS feature_count"]
        if is_line:
            geo_expr = f"{geom_4326}::geography"
            metric_parts += [
                f"SUM(ST_Length({geo_expr}))::float AS total_length_m",
                f"AVG(ST_Length({geo_expr}))::float AS avg_length_m",
                f"MIN(ST_Length({geo_expr}))::float AS min_length_m",
                f"MAX(ST_Length({geo_expr}))::float AS max_length_m",
            ]
        elif is_poly:
            geo_expr = f"{geom_4326}::geography"
            metric_parts += [
                f"SUM(ST_Area({geo_expr}))::float AS total_area_m2",
                f"AVG(ST_Area({geo_expr}))::float AS avg_area_m2",
                f"MIN(ST_Area({geo_expr}))::float AS min_area_m2",
                f"MAX(ST_Area({geo_expr}))::float AS max_area_m2",
                f"SUM(ST_Perimeter({geo_expr}))::float AS total_perimeter_m",
            ]
        # points: solo feature_count

        if group_by:
            qgb = quote_col(group_by)
            select_sql = f"{qgb}, {', '.join(metric_parts)}"
            sql = f"""
                SELECT {select_sql}
                FROM {table}
                WHERE {where_sql}
                GROUP BY {qgb}
                ORDER BY feature_count DESC
                LIMIT %s
            """
            sql_params = params + [limit]
        else:
            select_sql = ", ".join(metric_parts)
            sql = f"SELECT {select_sql} FROM {table} WHERE {where_sql}"
            sql_params = params

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, sql_params)
            if group_by:
                rows = _fetchall_dict(cur)
                for row in rows:
                    for k, v in row.items():
                        try:
                            if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                                row[k] = float(v)
                        except Exception:
                            pass
                data_result = rows
            else:
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                data_result = dict(zip(cols, row)) if row else {}
                for k, v in data_result.items():
                    try:
                        if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                            data_result[k] = float(v)
                    except Exception:
                        pass

        geometry_type = "line" if is_line else "polygon" if is_poly else "point"
        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "geometry_type": geometry_type,
                "bbox": bbox,
                "filters": filters,
                "group_by": group_by,
                **({"groups": data_result, "group_count": len(data_result)} if group_by else {"totals": data_result}),
            },
        )
