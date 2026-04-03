from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table, quote_col,
    get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialQueryLayerTool(BaseTool):
    name = "spatial.query_layer"
    description = (
        "Consulta una capa concreta (AGENTS_GIS_LAYERS) con filtros de atributo y/o bbox espacial. "
        "bbox es opcional: omítelo cuando busques por id o atributo sin restricción espacial."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
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
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "random_sample": {"type": "boolean"},
            "include_geom": {"type": "boolean"},
            "simplify_meters": {"type": "number"},
            "filters": {"type": "object"},  # { "field": scalar } o { "field": [v1, v2] } → IN
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
        if bbox:
            west = float(bbox["west"])
            south = float(bbox["south"])
            east = float(bbox["east"])
            north = float(bbox["north"])
        else:
            west = south = east = north = None

        limit = int(args.get("limit") or 50)
        limit = max(1, min(limit, 200))
        offset = int(args.get("offset") or 0)
        offset = max(0, offset)

        random_sample = bool(args.get("random_sample") or False)
        include_geom = bool(args.get("include_geom") or False)
        simplify_meters = float(args.get("simplify_meters") or 0.0)
        simplify_meters = max(0.0, min(simplify_meters, 50.0))

        filters = args.get("filters") or {}
        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        table = qualified_table(layer)
        geom_col = layer.get("geom_col", "the_geom")
        srid = get_layer_srid(layer)
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields", [])
        filter_fields = set(layer.get("filter_fields", []) or [])
        filter_fields.add(id_col)  # el id_col siempre es filtrable

        # Ignorar silenciosamente la key "fields": el LLM la usa para selección de columnas,
        # no para filtrar — no es un campo de la tabla.
        filters = {k: v for k, v in filters.items() if k != "fields"}

        # Ignorar filtros con valores no soportados:
        #   - None: campo opcional sin valor
        #   - dict: expresión de rango {"gt": x} que no soportamos
        #   - bool: causa errores de tipo en columnas numéricas (bigint = boolean)
        filters = {
            k: v for k, v in filters.items()
            if v is not None and not isinstance(v, (dict, bool))
        }

        # Validar que filters solo usa campos permitidos
        for k in filters.keys():
            if k not in filter_fields:
                return ToolResult(ok=False, error=f"filter not allowed: {k}")

        # WHERE base
        qgeom = quote_col(geom_col)
        geom4326 = geom_to_4326(qgeom, srid)
        where_clauses = [f"{qgeom} IS NOT NULL"]
        params = []

        if bbox:
            envelope_sql = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {envelope_sql})")
            params.extend([west, south, east, north])

        # Filtros parametrizados: escalar (=) o lista (IN)
        for k, v in filters.items():
            if isinstance(v, list):
                if not v:
                    continue  # lista vacía → no filtro
                bad = [i for i in v if not isinstance(i, (str, int, float, bool)) and i is not None]
                if bad:
                    return ToolResult(ok=False, error=f"filter list values for '{k}' must be scalars")
                # Normalizar a str: PostgreSQL puede hacer cast implícito str→número,
                # pero NO número→varchar (operator does not exist).
                norm_v = [str(i) if isinstance(i, (int, float)) and not isinstance(i, bool) else i for i in v]
                placeholders = ", ".join(["%s"] * len(norm_v))
                where_clauses.append(f"{quote_col(k)} IN ({placeholders})")
                params.extend(norm_v)
            else:
                if not isinstance(v, (str, int, float, bool)) and v is not None:
                    return ToolResult(ok=False, error=f"filter value for '{k}' must be a scalar")
                norm_v = str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
                where_clauses.append(f"{quote_col(k)} = %s")
                params.append(norm_v)

        where_sql = " AND ".join(where_clauses)
        order_sql = "ORDER BY random()" if random_sample else ""

        # COUNT total (sin limit/offset)
        count_sql = f"""
            SELECT COUNT(*)::int AS count
            FROM {table}
            WHERE {where_sql}
        """

        # SELECT items
        select_cols = [quote_col(id_col)] + [quote_col(f) for f in fields]
        select_fields_sql = ", ".join(select_cols)

        centroid_sql = f"""
            ST_X(ST_Centroid({geom4326}))::float AS lon,
            ST_Y(ST_Centroid({geom4326}))::float AS lat
        """

        metrics_sql = f"""
            GeometryType({qgeom}) AS geom_type,
            ST_Dimension({qgeom})::int AS geom_dim,
            CASE
              WHEN ST_Dimension({qgeom}) = 1 THEN ST_Length({geom4326}::geography)::float
              ELSE 0::float
            END AS length_m,
            CASE
              WHEN ST_Dimension({qgeom}) = 2 THEN ST_Area({geom4326}::geography)::float
              ELSE 0::float
            END AS area_m2
        """

        geom_geojson_sql = ""
        geom_params_prefix = []
        if include_geom:
            if simplify_meters > 0:
                geom_geojson_sql = f""",
                  ST_AsGeoJSON(
                    ST_Transform(
                      ST_SimplifyPreserveTopology(
                        ST_Transform({qgeom}, 3857),
                        %s
                      ),
                      4326
                    )
                  ) AS geom_geojson
                """
                geom_params_prefix = [simplify_meters]
            else:
                geom_geojson_sql = f""",
                  ST_AsGeoJSON({geom4326}) AS geom_geojson
                """

        items_sql = f"""
            SELECT
              {select_fields_sql},
              {centroid_sql},
              {metrics_sql}
              {geom_geojson_sql}
            FROM {table}
            WHERE {where_sql}
            {order_sql}
            LIMIT %s OFFSET %s
        """

        with get_gis_connection().cursor() as cur:
            # count
            cur.execute(count_sql, params)
            count_total = cur.fetchone()[0]

            # items
            items_params = []
            items_params.extend(geom_params_prefix)
            items_params.extend(params)
            items_params.extend([limit, offset])

            cur.execute(items_sql, items_params)
            items = _fetchall_dict(cur)

        # Hard guard geom size
        if include_geom:
            for it in items:
                g = it.get("geom_geojson")
                if isinstance(g, str) and len(g) > 20_000:
                    it["geom_geojson"] = g[:20_000] + "...(truncated)"

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "bbox": {"west": west, "south": south, "east": east, "north": north} if bbox else None,
                "filters": filters,
                "limit": limit,
                "offset": offset,
                "count_total": count_total,
                "items": items,
                "include_geom": include_geom,
                "simplify_meters": simplify_meters,
                "random_sample": random_sample,
            },
        )