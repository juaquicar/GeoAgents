from typing import Any, Dict, List

from django.db import transaction

from .heuristics import (
    build_goal_signature,
    classify_goal_domain,
    infer_analysis_types,
    infer_layers,
    normalize_goal,
    recommend_strategy,
    tool_sequence_signature,
)
from .models import Episode, EpisodePattern, Run, RunMemory


def _dedupe_strings(values: List[str]) -> List[str]:
    deduped = []
    seen = set()
    for value in values:
        text = (value or "").strip()
        if not text or text in seen:
            continue
        deduped.append(text)
        seen.add(text)
    return deduped


def _search_blob(values: List[str]) -> str:
    return " ".join(_dedupe_strings([value.lower() for value in values]))


def _extract_tool_sequence(executed_outputs: List[Dict[str, Any]]) -> List[str]:
    return [
        item.get("name", "").strip()
        for item in (executed_outputs or [])
        if item.get("type") == "tool" and item.get("name")
    ]


def _extract_tools_used(executed_outputs: List[Dict[str, Any]]) -> List[str]:
    return _dedupe_strings(_extract_tool_sequence(executed_outputs))


def _verification_summary(run: Run) -> Dict[str, Any]:
    output = run.output_json or {}
    summary = output.get("verification_summary") or {}
    if summary:
        return summary

    executed_outputs = output.get("executed_outputs") or []
    counts = {
        "verified": 0,
        "refuted": 0,
        "inconclusive": 0,
        "not_evaluated": 0,
    }
    groups = {key: [] for key in counts}

    for step in executed_outputs:
        if step.get("type") != "tool":
            continue
        verification = step.get("verification") or {}
        status = verification.get("status") or "not_evaluated"
        if status not in counts:
            status = "not_evaluated"
        counts[status] += 1
        groups[status].append(
            {
                "id": step.get("id"),
                "tool": step.get("name"),
                "reason": verification.get("reason", ""),
                "observed": verification.get("observed"),
            }
        )

    groups["counts"] = counts
    return groups


def _verification_status(summary: Dict[str, Any]) -> str:
    counts = (summary or {}).get("counts") or {}
    if counts.get("refuted"):
        return "refuted"
    if counts.get("inconclusive"):
        return "inconclusive"
    if counts.get("verified"):
        return "verified"
    return "not_evaluated"


def _extract_errors(run: Run, executed_outputs: List[Dict[str, Any]]) -> List[str]:
    errors = []
    if run.error:
        errors.append(run.error)
    for item in executed_outputs or []:
        if item.get("error"):
            errors.append(item["error"])
        for attempt in item.get("attempts") or []:
            if attempt.get("error"):
                errors.append(attempt["error"])
    return _dedupe_strings(errors)


def _extract_failure_modes(errors: List[str], verification_summary: Dict[str, Any]) -> List[str]:
    failure_modes: List[str] = []
    lowered = " ".join(error.lower() for error in errors)

    if "timeout" in lowered:
        failure_modes.append("timeout")
    if "not allowed" in lowered:
        failure_modes.append("tool_not_allowed")
    if "depends on unavailable" in lowered or "references unavailable" in lowered:
        failure_modes.append("dependency_resolution")
    if (verification_summary.get("counts") or {}).get("refuted"):
        failure_modes.append("verification_refuted")
    if (verification_summary.get("counts") or {}).get("inconclusive"):
        failure_modes.append("verification_inconclusive")
    if errors and not failure_modes:
        failure_modes.append("execution_error")

    return _dedupe_strings(failure_modes)


def _extract_replans(plan_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in (plan_history or []) if item.get("label") != "initial"]


def _summarize_structured_results(executed_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    tool_results = []
    for item in executed_outputs or []:
        if item.get("type") != "tool":
            continue

        data = item.get("data") or {}
        tool_results.append(
            {
                "id": item.get("id"),
                "tool": item.get("name"),
                "ok": item.get("ok"),
                "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
                "feature_count": len(data.get("features") or []) if isinstance(data, dict) else 0,
                "count_total": data.get("count_total") if isinstance(data, dict) else None,
                "path_found": data.get("path_found") if isinstance(data, dict) else None,
                "resolved_args": item.get("resolved_args") or {},
                "verification": item.get("verification") or {},
            }
        )

    return {
        "tool_results": tool_results,
        "tool_count": len(tool_results),
        "successful_tools": len([item for item in tool_results if item.get("ok")]),
        "failed_tools": len([item for item in tool_results if not item.get("ok")]),
    }


@transaction.atomic
def persist_run_intelligence(run: Run) -> None:
    payload = run.input_json or {}
    output = run.output_json or {}
    goal = payload.get("goal", "")
    plan = output.get("plan") or {}
    plan_history = output.get("plan_history") or []
    executed_outputs = output.get("executed_outputs") or []

    normalized_goal = normalize_goal(goal)
    goal_signature = build_goal_signature(goal)
    tool_sequence = _extract_tool_sequence(executed_outputs)
    tools_used = _extract_tools_used(executed_outputs)
    domain = classify_goal_domain(goal, tool_sequence)
    analysis_types = infer_analysis_types(goal, plan, tools_used)
    layers = infer_layers(plan, executed_outputs)
    verification_summary = _verification_summary(run)
    verification_status = _verification_status(verification_summary)
    errors = _extract_errors(run, executed_outputs)
    failure_modes = _extract_failure_modes(errors, verification_summary)
    replans = _extract_replans(plan_history)
    structured_results = _summarize_structured_results(executed_outputs)
    outcome = {
        "status": run.status,
        "ok": bool(output.get("ok", run.status == "succeeded")),
        "final_text": run.final_text,
        "replan_count": output.get("replan_count", 0),
        "tool_steps_executed": structured_results["tool_count"],
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }

    tool_signature = tool_sequence_signature(tool_sequence)
    recommended_strategy = recommend_strategy(
        goal=goal,
        tools_used=tools_used,
        verification_summary=verification_summary,
        errors=errors,
        allowlist=getattr(run.agent, "tool_allowlist", []) or [],
    )

    memory_defaults = {
        "normalized_goal": normalized_goal,
        "goal_signature": goal_signature,
        "domain": domain,
        "analysis_types": analysis_types,
        "analysis_types_search": _search_blob(analysis_types),
        "layers": layers,
        "layers_search": _search_blob(layers),
        "tools_used": tools_used,
        "tools_search": _search_blob(tools_used),
        "tool_sequence_signature": tool_signature,
        "final_plan": plan,
        "plan_history": plan_history,
        "structured_results": structured_results,
        "verification_summary": verification_summary,
        "verification_status": verification_status,
        "outcome": outcome,
        "errors": errors,
        "failure_modes": failure_modes,
        "failure_modes_search": _search_blob(failure_modes),
        "replans": replans,
    }
    RunMemory.objects.update_or_create(run=run, defaults=memory_defaults)

    episode_defaults = {
        "normalized_goal": normalized_goal,
        "goal_signature": goal_signature,
        "domain": domain,
        "analysis_types": analysis_types,
        "tools_used": tools_used,
        "tool_sequence": tool_sequence,
        "tool_sequence_signature": tool_signature,
        "outcome_status": run.status,
        "verification_status": verification_status,
        "success": run.status == "succeeded" and verification_status != "refuted",
        "failure_mode": failure_modes[0] if failure_modes else "",
        "failure_modes": failure_modes,
        "recommended_strategy": recommended_strategy,
        "verification_summary": verification_summary,
        "evidence": structured_results,
        "replan_count": output.get("replan_count", 0),
    }
    episode, _ = Episode.objects.update_or_create(run=run, defaults=episode_defaults)

    pattern, _ = EpisodePattern.objects.get_or_create(
        goal_signature=goal_signature,
        domain=domain,
        tool_sequence_signature=tool_signature,
        defaults={
            "tool_sequence": tool_sequence,
        },
    )

    matching_episodes = Episode.objects.filter(
        goal_signature=goal_signature,
        domain=domain,
        tool_sequence_signature=tool_signature,
    )
    sample_size = matching_episodes.count()
    success_count = matching_episodes.filter(success=True).count()
    failure_count = sample_size - success_count
    pattern.tool_sequence = tools_used
    pattern.sample_size = sample_size
    pattern.success_count = success_count
    pattern.failure_count = failure_count
    pattern.success_rate = (success_count / sample_size) if sample_size else 0.0
    pattern.last_outcome_status = episode.outcome_status
    pattern.last_failure_mode = episode.failure_mode
    pattern.recommended_strategy = episode.recommended_strategy
    pattern.save(
        update_fields=[
            "tool_sequence",
            "sample_size",
            "success_count",
            "failure_count",
            "success_rate",
            "last_outcome_status",
            "last_failure_mode",
            "recommended_strategy",
            "updated_at",
        ]
    )
