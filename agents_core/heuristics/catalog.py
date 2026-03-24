from typing import Sequence


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


def tool_sequence_signature(tools_used: Sequence[str]) -> str:
    sequence = [tool.strip() for tool in (tools_used or []) if tool and tool.strip()]
    return ">".join(sequence) if sequence else "none"