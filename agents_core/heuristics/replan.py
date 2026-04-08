from typing import List, Sequence

from .selection import select_initial_tools


# Fallback lógico cuando una tool falla: qué alternativas probar primero.
# La clave es la tool que falló; el valor es la lista de alternativas en orden de preferencia.
FALLBACK_MAP = {
    # Red: si la traza falla, probar ruta con coste y luego query
    "spatial.network_trace": ["spatial.route_cost", "spatial.query_layer", "spatial.context_pack"],
    "spatial.route_cost": ["spatial.network_trace", "spatial.query_layer", "spatial.context_pack"],
    "spatial.network_service_area": ["spatial.nearby", "spatial.within_distance", "spatial.query_layer"],

    # Relaciones espaciales
    "spatial.intersects": ["spatial.within_distance", "spatial.nearby", "spatial.query_layer"],
    "spatial.overlay": ["spatial.intersects", "spatial.spatial_join", "spatial.query_layer"],
    "spatial.spatial_join": ["spatial.intersects", "spatial.nearby", "spatial.query_layer"],
    "spatial.within_distance": ["spatial.nearby", "spatial.intersects", "spatial.query_layer"],
    "spatial.nearest_neighbor": ["spatial.nearby", "spatial.within_distance", "spatial.query_layer"],

    # Proximidad
    "spatial.nearby": ["spatial.within_distance", "spatial.context_pack", "spatial.query_layer"],
    "spatial.buffer": ["spatial.nearby", "spatial.within_distance", "spatial.query_layer"],

    # Análisis de densidad / clustering
    "spatial.cluster_dbscan": ["spatial.grid_stats", "spatial.aggregate", "spatial.query_layer"],
    "spatial.grid_stats": ["spatial.cluster_dbscan", "spatial.aggregate", "spatial.query_layer"],

    # Estadística
    "spatial.aggregate": ["spatial.count_within", "spatial.query_layer"],
    "spatial.count_within": ["spatial.aggregate", "spatial.query_layer"],

    # Geometría
    "spatial.dissolve": ["spatial.overlay", "spatial.aggregate", "spatial.query_layer"],
    "spatial.centroid": ["spatial.query_layer"],
    "spatial.convex_hull": ["spatial.measure", "spatial.query_layer"],
    "spatial.voronoi": ["spatial.buffer", "spatial.nearby", "spatial.query_layer"],
    "spatial.measure": ["spatial.query_layer", "spatial.summary"],
    "spatial.difference": ["spatial.overlay", "spatial.query_layer"],

    # Calidad
    "spatial.topology_check": ["spatial.query_layer", "spatial.summary"],

    # Consulta / resumen
    "spatial.query_layer": ["spatial.summary", "spatial.context_pack"],
    "spatial.summary": ["spatial.query_layer", "spatial.context_pack"],
    "spatial.context_pack": ["spatial.query_layer", "spatial.nearby"],
}


def select_fallback_tools(
    goal: str,
    failed_tool: str | None,
    allowlist: Sequence[str] | None = None,
) -> List[str]:
    suggestions = list(FALLBACK_MAP.get(failed_tool or "", []))
    suggestions.extend(select_initial_tools(goal, allowlist=None))

    deduped: List[str] = []
    seen = set()
    for tool in suggestions:
        if tool and tool not in seen:
            deduped.append(tool)
            seen.add(tool)

    allowlist = list(allowlist or [])
    if allowlist:
        deduped = [tool for tool in deduped if tool in allowlist]

    return deduped[:3]
