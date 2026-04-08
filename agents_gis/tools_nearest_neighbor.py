"""
Tool: spatial.nearest_neighbor
Para cada feature de la capa A devuelve el feature más cercano de la capa B,
junto con la distancia en metros.

Útil para preguntas como:
  - "¿Cuál es la farola más cercana a cada incidencia?"
  - "Para cada parcela, ¿cuál es el edificio más próximo?"
  - "Asigna a cada sensor el punto de control más cercano"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialNearestNeighborTool(BaseTool):
    name = "spatial.nearest_neighbor"
    description = (
        "Para cada feature de la capa fuente (source_layer) devuelve el feature más cercano "
        "de la capa vecina (neighbor_layer) usando un índice KNN (operador <->). "
        "Devuelve la distancia en metros y los atributos del vecino más próximo."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source_layer": {
                "type": "string",
                "description": "Capa cuyos features se usarán como origen.",
            },
            "neighbor_layer": {
                "type": "string",
                "description": "Capa en la que buscar el vecino más cercano para cada feature origen.",
            },
            "neighbor_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Campos de neighbor_layer a incluir en el resultado (deben estar en filter_fields).",
            },
            "max_distance_m": {
                "type": "number",
                "description": "Distancia máxima en metros. Features sin vecino dentro de ese rango se omiten.",
            },
            "bbox": {
                "type": "object",
                "description": "Filtro espacial sobre la capa fuente (WGS84).",
                "properties": {
                    "west": {"type": "number"}, "south": {"type": "number"},
                    "east": {"type": "number"}, "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "source_filters": {
                "type": "object",
                "description": "Filtros de atributo sobre la capa fuente.",
            },
            "neighbor_filters": {
                "type": "object",
                "description": "Filtros de atributo sobre la capa vecina.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de pares (origen, vecino) a devolver (1-500, defecto 100).",
            },
        },
        "required": ["source_layer", "neighbor_layer"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        src_name = (args.get("source_layer") or "").strip()
        nbr_name = (args.get("neighbor_layer") or "").strip()

        if not src_name:
            return ToolResult(ok=False, error="source_layer is required")
        if not nbr_name:
            return ToolResult(ok=False, error="neighbor_layer is required")

        src = _get_layer_cfg(src_name)
        if not src:
            return ToolResult(ok=False, error=f"Unknown source_layer: {src_name}")
        nbr = _get_layer_cfg(nbr_name)
        if not nbr:
            return ToolResult(ok=False, error=f"Unknown neighbor_layer: {nbr_name}")

        neighbor_fields = args.get("neighbor_fields") or []
        max_dist = args.get("max_distance_m")
        bbox = args.get("bbox")
        src_filters = args.get("source_filters") or {}
        nbr_filters = args.get("neighbor_filters") or {}
        limit = int(args.get("limit") or 100)
        limit = max(1, min(limit, 500))

        # Capas
        src_geom_col = src.get("geom_col", "the_geom")
        src_id_col = src.get("id_col", "id")
        src_fields = src.get("fields") or []
        src_srid = get_layer_srid(src)
        src_table = qualified_table(src)
        src_qgeom = quote_col(src_geom_col)
        # Prefijo de tabla para evitar ambigüedad cuando src y nbr comparten el nombre de columna
        src_geom_4326 = geom_to_4326(f"src.{src_qgeom}", src_srid)
        src_filter_fields = set(src.get("filter_fields") or []) | {src_id_col}

        nbr_geom_col = nbr.get("geom_col", "the_geom")
        nbr_id_col = nbr.get("id_col", "id")
        nbr_srid = get_layer_srid(nbr)
        nbr_table = qualified_table(nbr)
        nbr_qgeom = quote_col(nbr_geom_col)
        nbr_geom_4326 = geom_to_4326(f"nbr.{nbr_qgeom}", nbr_srid)
        nbr_filter_fields = set(nbr.get("filter_fields") or []) | {nbr_id_col}

        # Validar neighbor_fields
        allowed_nbr = set(nbr.get("fields") or []) | nbr_filter_fields
        for f in neighbor_fields:
            if f not in allowed_nbr:
                return ToolResult(ok=False, error=f"neighbor_field not allowed: {f}")

        # WHERE source — filtramos geometrías nulas, vacías o con SRID incorrecto
        # para evitar errores de ST_Transform en filas con coordenadas fuera de rango.
        src_where = [
            f"src.{src_qgeom} IS NOT NULL",
            f"NOT ST_IsEmpty(src.{src_qgeom})",
            f"ST_SRID(src.{src_qgeom}) = {src_srid}",
        ]
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

        # WHERE neighbor (para el LATERAL) — mismos filtros defensivos
        nbr_where_clauses = [
            f"nbr.{nbr_qgeom} IS NOT NULL",
            f"NOT ST_IsEmpty(nbr.{nbr_qgeom})",
            f"ST_SRID(nbr.{nbr_qgeom}) = {nbr_srid}",
        ]
        nbr_params: list = []

        if not isinstance(nbr_filters, dict):
            return ToolResult(ok=False, error="neighbor_filters must be an object")
        nbr_filters = {k: v for k, v in nbr_filters.items() if v is not None and not isinstance(v, dict)}
        for k in nbr_filters:
            if k not in nbr_filter_fields:
                return ToolResult(ok=False, error=f"neighbor filter not allowed: {k}")
        for k, v in nbr_filters.items():
            if isinstance(v, list):
                placeholders = ", ".join(["%s"] * len(v))
                nbr_where_clauses.append(f"nbr.{quote_col(k)} IN ({placeholders})")
                nbr_params.extend([str(i) if isinstance(i, (int, float)) else i for i in v])
            else:
                nbr_where_clauses.append(f"nbr.{quote_col(k)} = %s")
                nbr_params.append(str(v) if isinstance(v, (int, float)) else v)

        src_where_sql = " AND ".join(src_where)
        nbr_where_sql = " AND ".join(nbr_where_clauses)

        # SELECT fuente
        src_attr_sel = ", ".join(f"src.{quote_col(f)} AS src_{f}" for f in src_fields)
        src_attr_sel = (", " + src_attr_sel) if src_attr_sel else ""

        # SELECT vecino
        nbr_attr_sel = ", ".join(f"nbr.{quote_col(f)} AS nbr_{f}" for f in neighbor_fields)
        nbr_attr_sel = (", " + nbr_attr_sel) if nbr_attr_sel else ""

        # Centroid-first: calculamos el centroide en el SRID nativo ANTES de transformar.
        # Esto es clave para MULTIPOINT/MULTILINESTRING con componentes de coordenada
        # fuera de rango (ej. easting=2049 en ETRS89/UTM): el centroide promedia los
        # componentes y cae dentro del rango válido aunque algún punto sea inválido.
        # Orden: ST_Centroid(geom_nativo) → ST_Transform(centroide, 4326)
        src_centroid_4326 = geom_to_4326(f"ST_Centroid(src.{src_qgeom})", src_srid)
        nbr_centroid_4326 = geom_to_4326(f"ST_Centroid(nbr.{nbr_qgeom})", nbr_srid)

        src_geog = f"{src_centroid_4326}::geography"
        nbr_geog = f"{nbr_centroid_4326}::geography"

        max_dist_filter = ""
        dist_params: list = []
        if max_dist is not None:
            if src_srid == nbr_srid and src_srid != 4326:
                # Mismo CRS proyectado (unidades métricas): distancia nativa sin transform.
                # Evita ST_Transform en el LATERAL donde el planner puede evaluarlo
                # antes de que los filtros de SRID/IsEmpty hayan excluido filas inválidas.
                max_dist_filter = f"AND ST_DWithin(src.{src_qgeom}, nbr.{nbr_qgeom}, %s)"
            else:
                max_dist_filter = f"AND ST_DWithin({src_geog}, {nbr_geog}, %s)"
            dist_params.append(float(max_dist))

        sql = f"""
            SELECT
                src.{quote_col(src_id_col)} AS src_fid,
                ST_X({src_centroid_4326})::float AS src_lon,
                ST_Y({src_centroid_4326})::float AS src_lat
                {src_attr_sel},
                nbr.{quote_col(nbr_id_col)} AS nbr_fid,
                ST_X({nbr_centroid_4326})::float AS nbr_lon,
                ST_Y({nbr_centroid_4326})::float AS nbr_lat
                {nbr_attr_sel},
                ST_Distance({src_geog}, {nbr_geog})::float AS distance_m
            FROM {src_table} src
            CROSS JOIN LATERAL (
                SELECT nbr.*
                FROM {nbr_table} nbr
                WHERE {nbr_where_sql}
                {max_dist_filter}
                ORDER BY src.{src_qgeom} <-> nbr.{nbr_qgeom}
                LIMIT 1
            ) nbr
            WHERE {src_where_sql}
            ORDER BY distance_m
            LIMIT %s
        """

        all_params = params + nbr_params + dist_params + [limit]

        with get_gis_connection().cursor() as cur:
            cur.execute(sql, all_params)
            rows = _fetchall_dict(cur)

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
                "neighbor_layer": nbr_name,
                "max_distance_m": max_dist,
                "bbox": bbox,
                "pair_count": len(rows),
                "pairs": rows,
            },
        )
