from typing import List, Sequence

from .text import normalize_goal


def select_initial_tools(goal: str, allowlist: Sequence[str] | None = None) -> List[str]:
    allowlist = list(allowlist or [])
    normalized = normalize_goal(goal)
    suggestions: List[str] = []

    # Ruta topológica con origen/destino explícitos → network_trace / route_cost
    if any(token in normalized for token in ("traza", "trace", "ruta", "camino", "conexion")):
        suggestions.append("spatial.network_trace")
    if any(token in normalized for token in ("coste", "costo", "penaliz", "restric")):
        suggestions.append("spatial.route_cost")
    # Área de servicio / cobertura alcanzable desde un origen → service_area
    if any(token in normalized for token in ("servicio", "cobertura", "alcanzable", "service area", "isocron")):
        suggestions.append("spatial.network_service_area")
    # Relación espacial entre capas → intersects
    if any(token in normalized for token in ("interse", "solap", "cruce", "contiene", "superpone")):
        suggestions.append("spatial.intersects")
    # Proximidad a un punto → nearby; buffer si fuente es geometría de capa
    if any(token in normalized for token in ("cerca", "proxim", "nearby")):
        suggestions.append("spatial.nearby")
    if any(token in normalized for token in ("buffer", "radio", "metros de", "distancia de")):
        suggestions.append("spatial.buffer")
    # Agrupación / distribución / estadística → aggregate
    if any(token in normalized for token in (
        "por categoria", "por tipo", "distribucion", "predomina",
        "cuantos hay", "agrup", "suma de", "total de", "promedio", "estadistic",
    )):
        suggestions.append("spatial.aggregate")
    # Inventario / listado / consulta de capa concreta → query_layer
    elif any(token in normalized for token in (
        "inventario", "lista", "listar", "cuantos", "tipos", "categoria", "campo",
        "elementos", "registros", "detalle",
    )):
        suggestions.append("spatial.query_layer")
    # Análisis de red / grafo sin ruta explícita → summary para recuento por capas
    if any(token in normalized for token in ("red", "network", "grafo", "topolog")):
        if not suggestions:
            suggestions.append("spatial.summary")
    # Overview genuinamente genérico (sin operación ni capa mencionada) → context_pack
    if any(token in normalized for token in ("contexto", "entorno", "overview", "que hay")):
        if not suggestions:
            suggestions.append("spatial.context_pack")
    if not suggestions:
        suggestions.append("spatial.query_layer")

    deduped = []
    seen = set()
    for item in suggestions:
        if item not in seen:
            deduped.append(item)
            seen.add(item)

    if allowlist:
        deduped = [tool for tool in deduped if tool in allowlist]
        if not deduped:
            deduped = allowlist[:1]

    return deduped