"""
Tool: spatial.overlay
Superposición geométrica de dos capas de polígonos.
Modos: intersect (zona común), union (todo junto), difference (A menos B a nivel de capa).

Útil para preguntas como:
  - "¿Qué parcelas se solapan con la zona de protección?"
  - "¿Cuál es la unión de las zonas verdes y los parques?"
  - "Dame el área de las parcelas que NO está cubierta por edificios"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)

_VALID_MODES = {"intersect", "union", "difference"}


@register_tool
class SpatialOverlayTool(BaseTool):
    name = "spatial.overlay"
    description = (
        "Superposición geométrica de dos capas de polígonos (ST_Intersection / ST_Union / ST_Difference). "
        "intersect: devuelve los fragmentos comunes entre ambas capas. "
        "union: combina todas las geometrías de ambas capas. "
        "difference: devuelve la parte de la capa A no cubierta por la capa B. "
        "Devuelve el área en m² del resultado y, opcionalmente, la geometría GeoJSON."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer_a": {
                "type": "string",
                "description": "Capa base (de gis_layers_catalog).",
            },
            "layer_b": {
                "type": "string",
                "description": "Capa a superponer (de gis_layers_catalog).",
            },
            "mode": {
                "type": "string",
                "enum": ["intersect", "union", "difference"],
                "description": "Tipo de operación de superposición.",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial (WGS84). Muy recomendado para limitar el cálculo.",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "filters_a": {
                "type": "object",
                "description": "Filtros de atributo para la capa A.",
            },
            "filters_b": {
                "type": "object",
                "description": "Filtros de atributo para la capa B.",
            },
            "include_geom": {
                "type": "boolean",
                "description": "Si true, incluye la geometría GeoJSON del resultado.",
            },
        },
        "required": ["layer_a", "layer_b", "mode"],
    }

    def _build_subquery(self, layer, filters, bbox, alias):
        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
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
            return None, None, "filters must be an object"
        filters = {k: v for k, v in filters.items() if v is not None and not isinstance(v, dict)}
        for k in filters:
            if k not in filter_fields:
                return None, None, f"filter not allowed in {alias}: {k}"
        for k, v in filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                where_clauses.append(f"{quote_col(k)} = %s")
                params.append(str(v) if isinstance(v, (int, float)) else v)

        where_sql = " AND ".join(where_clauses)
        # Recopilamos la unión de geometrías de la capa
        subq = f"(SELECT ST_Union({geom_4326}) AS geom FROM {table} WHERE {where_sql})"
        return subq, params, None

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_a_name = (args.get("layer_a") or "").strip()
        layer_b_name = (args.get("layer_b") or "").strip()
        mode = (args.get("mode") or "").strip().lower()

        if not layer_a_name:
            return ToolResult(ok=False, error="layer_a is required")
        if not layer_b_name:
            return ToolResult(ok=False, error="layer_b is required")
        if mode not in _VALID_MODES:
            return ToolResult(ok=False, error=f"mode must be one of: {', '.join(_VALID_MODES)}")

        layer_a = _get_layer_cfg(layer_a_name)
        if not layer_a:
            return ToolResult(ok=False, error=f"Unknown layer_a: {layer_a_name}")
        layer_b = _get_layer_cfg(layer_b_name)
        if not layer_b:
            return ToolResult(ok=False, error=f"Unknown layer_b: {layer_b_name}")

        bbox = args.get("bbox")
        filters_a = args.get("filters_a") or {}
        filters_b = args.get("filters_b") or {}
        include_geom = bool(args.get("include_geom", False))

        subq_a, params_a, err = self._build_subquery(layer_a, filters_a, bbox, "layer_a")
        if err:
            return ToolResult(ok=False, error=err)
        subq_b, params_b, err = self._build_subquery(layer_b, filters_b, bbox, "layer_b")
        if err:
            return ToolResult(ok=False, error=err)

        if mode == "intersect":
            result_geom = f"ST_Intersection(a.geom, b.geom)"
        elif mode == "union":
            result_geom = f"ST_Union(a.geom, b.geom)"
        else:  # difference
            result_geom = f"ST_Difference(a.geom, COALESCE(b.geom, 'GEOMETRYCOLLECTION EMPTY'::geometry))"

        geom_select = f"ST_AsGeoJSON({result_geom}) AS result_geom" if include_geom else f"NULL AS result_geom"

        sql = f"""
            SELECT
                ST_Area({result_geom}::geography)::float AS result_area_m2,
                ST_IsEmpty({result_geom}) AS is_empty,
                {geom_select}
            FROM {subq_a} AS a, {subq_b} AS b
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, params_a + params_b)
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()

        if not row:
            return ToolResult(ok=False, error="Overlay query returned no result")

        result = dict(zip(cols, row))
        data = {
            "layer_a": layer_a_name,
            "layer_b": layer_b_name,
            "mode": mode,
            "bbox": bbox,
            "result_area_m2": result.get("result_area_m2") or 0.0,
            "is_empty": bool(result.get("is_empty")),
        }
        if include_geom and result.get("result_geom"):
            data["result_geom"] = result["result_geom"]

        return ToolResult(ok=True, data=data)
