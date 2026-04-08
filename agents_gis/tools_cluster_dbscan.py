"""
Tool: spatial.cluster_dbscan
Agrupa features de una capa usando el algoritmo DBSCAN (Density-Based Spatial
Clustering of Applications with Noise) a través de ST_ClusterDBSCAN de PostGIS.

No necesita que el usuario especifique el número de clusters — los descubre
automáticamente según la densidad. Los outliers se marcan con cluster_id = -1.

Útil para:
  - "¿Dónde se concentran los incidentes?"
  - "¿Cuántos focos de averías hay?"
  - "Detecta agrupaciones naturales de activos"
"""
from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table,
    quote_col, get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


@register_tool
class SpatialClusterDbscanTool(BaseTool):
    name = "spatial.cluster_dbscan"
    description = (
        "Agrupa features de una capa con DBSCAN (ST_ClusterDBSCAN). "
        "Descubre automáticamente el número de clusters según la densidad espacial. "
        "cluster_id = -1 indica outlier (ruido). "
        "Devuelve los features con su cluster_id y un resumen por cluster."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "eps_m": {
                "type": "number",
                "description": "Radio de vecindad en metros. Features a menos de eps_m forman un cluster.",
            },
            "min_points": {
                "type": "integer",
                "description": "Mínimo de features para que una zona se considere cluster (no ruido). Defecto 3.",
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
            "filters": {"type": "object"},
            "limit": {
                "type": "integer",
                "description": "Máximo de features individuales a devolver (1-500, defecto 200). El resumen por cluster siempre se devuelve completo.",
            },
        },
        "required": ["layer", "eps_m"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        eps_m = float(args.get("eps_m") or 0)
        if eps_m <= 0:
            return ToolResult(ok=False, error="eps_m must be greater than 0")

        min_points = max(1, int(args.get("min_points") or 3))
        bbox = args.get("bbox")
        filters = args.get("filters") or {}
        limit = int(args.get("limit") or 200)
        limit = max(1, min(limit, 500))

        if not isinstance(filters, dict):
            return ToolResult(ok=False, error="filters must be an object")

        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")
        fields = layer.get("fields", [])
        filter_fields = set(layer.get("filter_fields") or []) | {id_col}
        srid = get_layer_srid(layer)
        table = qualified_table(layer)
        qgeom = quote_col(geom_col)
        geom_4326 = geom_to_4326(qgeom, srid)

        # WHERE
        where_clauses = [f"{qgeom} IS NOT NULL"]
        params: list = []

        if bbox:
            env = bbox_in_layer_srid(srid)
            where_clauses.append(f"ST_Intersects({qgeom}, {env})")
            params.extend([float(bbox["west"]), float(bbox["south"]),
                           float(bbox["east"]), float(bbox["north"])])

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
        fields_sql = ", ".join(quote_col(f) for f in fields)
        select_fields = f"{quote_col(id_col)}" + (f", {fields_sql}" if fields_sql else "")

        centroid_sql = (
            f"ST_X(ST_Centroid({geom_4326}))::float AS lon, "
            f"ST_Y(ST_Centroid({geom_4326}))::float AS lat"
        )

        # ST_ClusterDBSCAN trabaja en 3857 (metros) para eps preciso
        geom_3857 = f"ST_Transform({qgeom}, 3857)" if srid != 3857 else qgeom

        features_sql = f"""
            WITH clustered AS (
                SELECT
                    {select_fields},
                    {centroid_sql},
                    ST_ClusterDBSCAN({geom_3857}, %s, %s) OVER () AS cluster_id
                FROM {table}
                WHERE {where_sql}
            )
            SELECT * FROM clustered
            ORDER BY cluster_id NULLIF cluster_id = -1, cluster_id
            LIMIT %s
        """

        # Fix ORDER BY syntax
        features_sql = f"""
            WITH clustered AS (
                SELECT
                    {select_fields},
                    {centroid_sql},
                    ST_ClusterDBSCAN({geom_3857}, %s, %s) OVER () AS cluster_id
                FROM {table}
                WHERE {where_sql}
            )
            SELECT * FROM clustered
            ORDER BY
                CASE WHEN cluster_id = -1 THEN 1 ELSE 0 END,
                cluster_id
            LIMIT %s
        """

        summary_sql = f"""
            WITH clustered AS (
                SELECT
                    {centroid_sql},
                    ST_ClusterDBSCAN({geom_3857}, %s, %s) OVER () AS cluster_id
                FROM {table}
                WHERE {where_sql}
            )
            SELECT
                cluster_id,
                COUNT(*)::int AS count,
                AVG(lon)::float AS centroid_lon,
                AVG(lat)::float AS centroid_lat,
                cluster_id = -1 AS is_noise
            FROM clustered
            GROUP BY cluster_id
            ORDER BY
                CASE WHEN cluster_id = -1 THEN 1 ELSE 0 END,
                count DESC
        """

        cluster_params = [eps_m, min_points] + params
        features_params = cluster_params + [limit]
        summary_params = cluster_params

        with get_gis_connection().cursor() as cur:
            cur.execute(features_sql, features_params)
            features = _fetchall_dict(cur)

            cur.execute(summary_sql, summary_params)
            summary = _fetchall_dict(cur)

        noise = next((s for s in summary if s.get("cluster_id") == -1), None)
        real_clusters = [s for s in summary if s.get("cluster_id") != -1]

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "eps_m": eps_m,
                "min_points": min_points,
                "bbox": bbox,
                "total_features": sum(s.get("count", 0) for s in summary),
                "cluster_count": len(real_clusters),
                "noise_count": noise.get("count", 0) if noise else 0,
                "cluster_summary": summary,
                "features": features,
            },
        )
