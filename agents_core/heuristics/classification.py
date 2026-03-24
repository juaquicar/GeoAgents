from typing import Any, Dict, List, Sequence

from .catalog import KEYWORD_ANALYSIS_TYPES, TOOL_ANALYSIS_TYPES
from .text import normalize_goal


def add_unique(values: List[str], new_values) -> List[str]:
    seen = set(values)
    for value in new_values:
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


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


def infer_analysis_types(goal: str, plan: Dict[str, Any] | None, tools_used: Sequence[str]) -> List[str]:
    analysis_types: List[str] = []

    for tool_name in tools_used or []:
        tool_analysis = TOOL_ANALYSIS_TYPES.get(tool_name)
        if tool_analysis:
            add_unique(analysis_types, [tool_analysis])

    normalized_goal = normalize_goal(goal)
    for token, analysis_type in KEYWORD_ANALYSIS_TYPES.items():
        if token in normalized_goal:
            add_unique(analysis_types, [analysis_type])

    for step in (plan or {}).get("steps", []):
        if step.get("type") != "tool":
            continue
        if step.get("success_criteria"):
            add_unique(analysis_types, ["verification_driven"])
        if step.get("can_replan"):
            add_unique(analysis_types, ["replanning"])

    if not analysis_types:
        add_unique(analysis_types, ["generic_spatial"])

    return analysis_types


_LAYER_KEYS = {"layer", "source_layer", "target_layer"}


def infer_layers(plan: Dict[str, Any] | None, executed_outputs: Sequence[Dict[str, Any]]) -> List[str]:
    layers: List[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _LAYER_KEYS and isinstance(item, str) and item.strip():
                    add_unique(layers, [item.strip()])
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