import re
import unicodedata
from typing import Any, Dict, Iterable, List, Sequence


STOPWORDS = {
    "a",
    "al",
    "and",
    "con",
    "de",
    "del",
    "el",
    "en",
    "esta",
    "este",
    "for",
    "la",
    "las",
    "los",
    "mapa",
    "por",
    "que",
    "quiero",
    "sobre",
    "the",
    "un",
    "una",
    "ver",
    "zona",
}

TOOL_ANALYSIS_TYPES = {
    "spatial.context_pack": "spatial_context",
    "spatial.intersects": "spatial_relation",
    "spatial.nearby": "proximity_analysis",
    "spatial.network_trace": "network_trace",
    "spatial.query_layer": "layer_query",
    "spatial.summary": "spatial_summary",
}

KEYWORD_ANALYSIS_TYPES = {
    "debug": "debugging",
    "depura": "debugging",
    "fallback": "resilience",
    "interse": "spatial_relation",
    "network": "network_trace",
    "proxim": "proximity_analysis",
    "red": "network_trace",
    "replan": "replanning",
    "ruta": "network_trace",
    "solap": "spatial_relation",
    "trace": "network_trace",
}


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(ch)
    )


def normalize_goal(goal: str) -> str:
    cleaned = _strip_accents((goal or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def goal_keywords(goal: str, limit: int = 8) -> List[str]:
    tokens = []
    seen = set()
    for token in normalize_goal(goal).split():
        if len(token) <= 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def build_goal_signature(goal: str) -> str:
    keywords = goal_keywords(goal, limit=6)
    return "|".join(keywords) if keywords else "generic"


def tool_sequence_signature(tools_used: Sequence[str]) -> str:
    sequence = [tool.strip() for tool in (tools_used or []) if tool and tool.strip()]
    return ">".join(sequence) if sequence else "none"


def classify_goal_domain(goal: str, tools_used: Sequence[str] | None = None) -> str:
    normalized = normalize_goal(goal)
    tools_used = list(tools_used or [])

    if "spatial.network_trace" in tools_used or any(
        token in normalized for token in ("traza", "trace", "red", "network", "ruta")
    ):
        return "network"
    if "spatial.intersects" in tools_used or any(
        token in normalized for token in ("interse", "solap", "cruce", "contiene")
    ):
        return "spatial_relation"
    if "spatial.context_pack" in tools_used or any(
        token in normalized for token in ("contexto", "entorno", "overview", "resumen")
    ):
        return "spatial_context"
    if "spatial.nearby" in tools_used or any(
        token in normalized for token in ("cerca", "proxim", "nearby")
    ):
        return "proximity"
    if "spatial.query_layer" in tools_used:
        return "layer_inspection"
    return "generic_spatial"


def _add_unique(values: List[str], new_values: Iterable[str]) -> List[str]:
    seen = set(values)
    for value in new_values:
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def infer_analysis_types(goal: str, plan: Dict[str, Any] | None, tools_used: Sequence[str]) -> List[str]:
    analysis_types: List[str] = []

    for tool_name in tools_used or []:
        tool_analysis = TOOL_ANALYSIS_TYPES.get(tool_name)
        if tool_analysis:
            _add_unique(analysis_types, [tool_analysis])

    normalized_goal = normalize_goal(goal)
    for token, analysis_type in KEYWORD_ANALYSIS_TYPES.items():
        if token in normalized_goal:
            _add_unique(analysis_types, [analysis_type])

    for step in (plan or {}).get("steps", []):
        if step.get("type") != "tool":
            continue
        if step.get("success_criteria"):
            _add_unique(analysis_types, ["verification_driven"])
        if step.get("can_replan"):
            _add_unique(analysis_types, ["replanning"])

    if not analysis_types:
        _add_unique(analysis_types, ["generic_spatial"])

    return analysis_types


_LAYER_KEYS = {"layer", "source_layer", "target_layer"}


def infer_layers(plan: Dict[str, Any] | None, executed_outputs: Sequence[Dict[str, Any]]) -> List[str]:
    layers: List[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _LAYER_KEYS and isinstance(item, str) and item.strip():
                    _add_unique(layers, [item.strip()])
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(plan or {})
    for output in executed_outputs or []:
        collect(output.get("resolved_args") or {})
        collect(output.get("data") or {})

    return layers


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

    if allowlist:
        suggestions = [tool for tool in suggestions if tool in allowlist]
        if not suggestions:
            suggestions = allowlist[:1]

    return suggestions


def select_fallback_tools(
    goal: str,
    failed_tool: str | None,
    allowlist: Sequence[str] | None = None,
) -> List[str]:
    fallback_map = {
        "spatial.network_trace": ["spatial.query_layer", "spatial.context_pack"],
        "spatial.context_pack": ["spatial.query_layer", "spatial.nearby"],
        "spatial.intersects": ["spatial.query_layer", "spatial.context_pack"],
        "spatial.nearby": ["spatial.context_pack", "spatial.query_layer"],
        "spatial.query_layer": ["spatial.context_pack"],
    }
    suggestions = list(fallback_map.get(failed_tool or "", []))
    suggestions.extend(select_initial_tools(goal, allowlist=None))

    deduped: List[str] = []
    _add_unique(deduped, suggestions)

    allowlist = list(allowlist or [])
    if allowlist:
        deduped = [tool for tool in deduped if tool in allowlist]

    return deduped[:3]


def recommend_strategy(
    goal: str,
    tools_used: Sequence[str],
    verification_summary: Dict[str, Any] | None,
    errors: Sequence[str] | None,
    allowlist: Sequence[str] | None = None,
) -> str:
    verification_summary = verification_summary or {}
    counts = verification_summary.get("counts") or {}
    errors = [error for error in (errors or []) if error]

    initial_tools = select_initial_tools(goal, allowlist)
    failed_tool = next((tool for tool in reversed(list(tools_used or [])) if tool), None)
    fallback_tools = select_fallback_tools(goal, failed_tool, allowlist)

    if counts.get("refuted"):
        return (
            "Hipótesis refutada: conviene replanificar con una tool alternativa. "
            f"Inicio sugerido: {', '.join(initial_tools)}. "
            f"Fallback sugerido: {', '.join(fallback_tools)}."
        )

    if counts.get("inconclusive") or errors:
        return (
            "Evidencia inconclusa o error operativo: repetir con verificación explícita y fallback controlado. "
            f"Inicio sugerido: {', '.join(initial_tools)}. "
            f"Fallback sugerido: {', '.join(fallback_tools)}."
        )

    if tools_used:
        return (
            "Secuencia efectiva detectada: "
            f"{' -> '.join(tools_used)}. "
            f"Próximo arranque recomendado: {', '.join(initial_tools)}."
        )

    return f"Arranque recomendado: {', '.join(initial_tools)}."


def build_planner_heuristics(run, payload: Dict[str, Any]) -> Dict[str, Any]:
    goal = payload.get("goal", "")
    allowlist = getattr(run.agent, "tool_allowlist", []) or []
    domain = classify_goal_domain(goal)
    signature = build_goal_signature(goal)

    pattern_hints = []
    try:
        from .models import EpisodePattern

        patterns = EpisodePattern.objects.filter(domain=domain).order_by(
            "-success_rate",
            "-sample_size",
        )[:3]
        for pattern in patterns:
            pattern_hints.append(
                {
                    "goal_signature": pattern.goal_signature,
                    "tool_sequence": pattern.tool_sequence,
                    "success_rate": pattern.success_rate,
                    "sample_size": pattern.sample_size,
                    "recommended_strategy": pattern.recommended_strategy,
                }
            )
    except Exception:
        pattern_hints = []

    return {
        "goal_signature": signature,
        "domain": domain,
        "initial_tools": select_initial_tools(goal, allowlist),
        "fallback_tools": select_fallback_tools(goal, None, allowlist),
        "pattern_hints": pattern_hints,
    }
