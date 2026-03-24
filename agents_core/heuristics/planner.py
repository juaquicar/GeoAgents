from typing import Dict

from .classification import classify_goal_domain
from .replan import select_fallback_tools
from .selection import select_initial_tools
from .text import build_goal_signature


def build_planner_heuristics(run, payload: Dict[str, object]) -> Dict[str, object]:
    goal = payload.get("goal", "")
    allowlist = getattr(run.agent, "tool_allowlist", []) or []
    domain = classify_goal_domain(goal)
    signature = build_goal_signature(goal)

    pattern_hints = []
    try:
        from agents_core.models import EpisodePattern

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