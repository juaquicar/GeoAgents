from typing import List, Sequence

from .text import normalize_goal


def select_initial_tools(goal: str, allowlist: Sequence[str] | None = None) -> List[str]:
    allowlist = list(allowlist or [])
    normalized = normalize_goal(goal)
    suggestions: List[str] = []

    if any(token in normalized for token in ("traza", "trace", "red", "network", "ruta")):
        suggestions.append("spatial.network_trace")
    if any(token in normalized for token in ("contexto", "entorno", "overview", "resumen")):
        suggestions.append("spatial.context_pack")
    if any(token in normalized for token in ("interse", "solap", "cruce", "contiene")):
        suggestions.append("spatial.intersects")
    if any(token in normalized for token in ("cerca", "proxim", "nearby")):
        suggestions.append("spatial.nearby")
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