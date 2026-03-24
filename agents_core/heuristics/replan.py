from typing import List, Sequence

from .selection import select_initial_tools


FALLBACK_MAP = {
    "spatial.network_trace": ["spatial.query_layer", "spatial.context_pack"],
    "spatial.context_pack": ["spatial.query_layer", "spatial.nearby"],
    "spatial.intersects": ["spatial.query_layer", "spatial.context_pack"],
    "spatial.nearby": ["spatial.context_pack", "spatial.query_layer"],
    "spatial.query_layer": ["spatial.context_pack"],
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