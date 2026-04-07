"""
Tool: spatial.buffer
Encuentra elementos de una capa (target_layer) dentro de un radio (buffer_m)
alrededor de una geometría fuente.

A diferencia de spatial.nearby (solo punto), la fuente puede ser:
  - Un punto explícito (source_point)
  - Un elemento de otra capa por id (source_layer + source_id) → funciona con
    líneas y polígonos, p.ej. "estructuras a menos de 50m de este tramo span"

Devuelve los elementos encontrados ordenados por distancia_m ascendente.
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table, quote_col,
    get_layer_srid, geom_to_4326,
)


@register_tool
class SpatialBufferTool(BaseTool):
    name = "spatial.buffer"
    description = (
        "Encuentra elementos de una capa (target_layer) dentro de un radio buffer_m "
        "alrededor de una geometría fuente. La fuente puede ser un punto explícito "
        "(source_point) o un elemento de otra capa (source_layer + source_id), lo que "
        "permite buffers sobre líneas y polígonos. Más potente que spatial.nearby para "
        "geometrías fuente no puntuales."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "target_layer": {
                "type": "string",
                "description": "Capa donde buscar elementos dentro del buffer.",
            },
            "buffer_m": {
                "type": "number",
                "description": "Radio del buffer en metros.",
            },
            "source_point": {
                "type": "object",
                "description": "Punto fuente (WGS84). Usar cuando la fuente es un punto explícito.",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                },
                "required": ["lon", "lat"],
            },
            "source_layer": {
                "type": "string",
                "description": "Capa del elemento fuente. Usar junto con source_id.",
            },
            "source_id": {
                "description": "ID del elemento fuente en source_layer (integer o string).",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial adicional opcional (WGS84).",
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
                "description": "Filtros de atributo opcionales sobre target_layer.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de elementos a devolver (1-200, defecto 50).",
            },
            "include_geom": {
                "type": "boolean",
                "description": "Incluir geometría GeoJSON de cada elemento.",
            },
        },
        "required": ["target_layer", "buffer_m"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        # ── Target layer ───────────────────────────────────────────────────
        target_name = (args.get("target_layer") or "").strip()
        if not target_name:
            return ToolResult(ok=False, error="target_layer is required")
        target_layer = _get_layer_cfg(target_name)
        if not target_layer:
            return ToolResult(ok=False, error=f"Unknown layer: {target_name}")

        buffer_m = float(args.get("buffer_m") or 0.0)
        buffer_m = max(0.1, min(buffer_m, 100_000.0))

        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        include_geom = bool(args.get("include_geom") or False)
        bbox = args.get("bbox")
        filters = args.get("filters") or {}
        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        # ── Fuente ─────────────────────────────────────────────────────────
        source_point = args.get("source_point")
        source_layer_name = (args.get("source_layer") or "").strip()
        source_id = args.get("source_id")

        if not source_point and not (source_layer_name and source_id is not None):
            return ToolResult(
                ok=False,
                error="Provide either source_point or both source_layer and source_id",
            )

        # ── Target config ──────────────────────────────────────────────────
        t_table = qualified_table(target_layer)
        t_geom_col = target_layer.get("geom_col", "the_geom")
        t_srid = get_layer_srid(target_layer)
        t_id_col = target_layer.get("id_col", "id")
        t_fields = target_layer.get("fields", [])
        t_filter_fields = set(target_layer.get("filter_fields") or [])
        t_filter_fields.add(t_id_col)

        t_qgeom = quote_col(t_geom_col)
        t_geom4326 = geom_to_4326(t_qgeom, t_srid)

        # Validar filtros
        filters = {
            k: v for k, v in filters.items()
            if v is not None and not isinstance(v, (dict, bool))
        }
        for k in filters:
            if k not in t_filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")

        # ── Construir geometría fuente ─────────────────────────────────────
        cte_sql = ""
        cte_params = []

        if source_point:
            lon = float(source_point["lon"])
            lat = float(source_point["lat"])
            src_geog_expr = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography"
            src_geog_params = [lon, lat]
            source_info = {"type": "point", "lon": lon, "lat": lat}
        else:
            src_layer = _get_layer_cfg(source_layer_name)
            if not src_layer:
                return ToolResult(ok=False, error=f"Unknown source_layer: {source_layer_name}")
            s_table = qualified_table(src_layer)
            s_geom_col = src_layer.get("geom_col", "the_geom")
            s_srid = get_layer_srid(src_layer)
            s_id_col = src_layer.get("id_col", "id")
            s_qgeom = quote_col(s_geom_col)
            s_geom4326 = geom_to_4326(s_qgeom, s_srid)

            # CTE para evitar repetir la subquery en WHERE y en SELECT
            cte_sql = f"""
WITH _src AS (
    SELECT {s_geom4326}::geography AS geog
    FROM {s_table}
    WHERE {quote_col(s_id_col)} = %s
)
"""
            cte_params = [str(source_id) if isinstance(source_id, int) else source_id]
            src_geog_expr = "(SELECT geog FROM _src)"
            src_geog_params = []
            source_info = {
                "type": "layer_element",
                "layer": source_layer_name,
                "id": source_id,
            }

        # ── WHERE ──────────────────────────────────────────────────────────
        where_clauses = [
            f"{t_qgeom} IS NOT NULL",
            f"ST_DWithin({t_geom4326}::geography, {src_geog_expr}, %s)",
        ]
        where_params = list(src_geog_params) + [buffer_m]

        if bbox:
            west  = float(bbox["west"])
            south = float(bbox["south"])
            east  = float(bbox["east"])
            north = float(bbox["north"])
            where_clauses.append(
                f"ST_Intersects({t_qgeom}, "
                f"ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
                f"{'::geometry' if t_srid == 4326 else f' transformed to {t_srid}'})"
            )
            # Más simple y portable: transformar el envelope al SRID de la capa
            where_clauses[-1] = (
                f"ST_Intersects({t_qgeom}, "
                f"ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), {t_srid}))"
            )
            where_params.extend([west, south, east, north])
        else:
            west = south = east = north = None

        for k, v in filters.items():
            if isinstance(v, list):
                if not v:
                    continue
                placeholders = ", ".join(["%s"] * len(v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                where_params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                where_clauses.append(f"{quote_col(k)} = %s")
                where_params.append(str(v) if isinstance(v, (int, float)) else v)

        where_sql = " AND ".join(where_clauses)

        # ── SELECT ─────────────────────────────────────────────────────────
        select_cols = [quote_col(t_id_col)] + [quote_col(f) for f in t_fields]
        select_fields_sql = ", ".join(select_cols)

        centroid_sql = (
            f"ST_X(ST_Centroid({t_geom4326}))::float AS lon, "
            f"ST_Y(ST_Centroid({t_geom4326}))::float AS lat"
        )
        metrics_sql = f"""
            GeometryType({t_qgeom}) AS geom_type,
            ST_Dimension({t_qgeom})::int AS geom_dim,
            CASE WHEN ST_Dimension({t_qgeom}) = 1
                 THEN ST_Length({t_geom4326}::geography)::float ELSE 0::float END AS length_m,
            CASE WHEN ST_Dimension({t_qgeom}) = 2
                 THEN ST_Area({t_geom4326}::geography)::float ELSE 0::float END AS area_m2
        """
        distance_sql = (
            f"ST_Distance({t_geom4326}::geography, {src_geog_expr})::float AS distance_m"
        )

        geom_sql = ""
        geom_params = []
        if include_geom:
            geom_sql = f", ST_AsGeoJSON({t_geom4326}) AS geom_geojson"

        count_sql = f"""
            {cte_sql}
            SELECT COUNT(*)::int FROM {t_table} WHERE {where_sql}
        """

        # Para el SELECT de distancia hay que repetir src_geog_params si no hay CTE
        dist_params = [] if cte_sql else list(src_geog_params)

        items_sql = f"""
            {cte_sql}
            SELECT
              {select_fields_sql},
              {centroid_sql},
              {metrics_sql},
              {distance_sql}
              {geom_sql}
            FROM {t_table}
            WHERE {where_sql}
            ORDER BY distance_m ASC
            LIMIT %s
        """

        with get_gis_connection().cursor() as cur:
            cur.execute(count_sql, cte_params + where_params)
            count_total = cur.fetchone()[0]

            items_params = cte_params + dist_params + geom_params + where_params + [limit]
            cur.execute(items_sql, items_params)
            items = _fetchall_dict(cur)

        if include_geom:
            for it in items:
                g = it.get("geom_geojson")
                if isinstance(g, str) and len(g) > 20_000:
                    it["geom_geojson"] = g[:20_000] + "...(truncated)"

        return ToolResult(
            ok=True,
            data={
                "target_layer": target_name,
                "source": source_info,
                "buffer_m": buffer_m,
                "bbox": {"west": west, "south": south, "east": east, "north": north} if bbox else None,
                "filters": filters,
                "count_total": count_total,
                "limit": limit,
                "items": items,
                "include_geom": include_geom,
            },
        )
