import copy
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from .memory import persist_run_intelligence
from .models import Run
from .steps import log_step

from agents_tools.executor import invoke_tool
from agents_llm.planner import plan_run
from agents_llm.synthesizer import synthesize_run


MAX_PLANNER_TOOL_STEPS = getattr(settings, "AGENTS_MAX_PLANNER_TOOL_STEPS", 5)
MAX_REPLANS = getattr(settings, "AGENTS_MAX_REPLANS", 1)
DEFAULT_STEP_MAX_RETRIES = getattr(settings, "AGENTS_STEP_MAX_RETRIES", 0)
DEFAULT_STEP_RETRY_BACKOFF_S = getattr(settings, "AGENTS_STEP_RETRY_BACKOFF_S", 0.0)


def _ensure_tool_allowed(run: Run, tool_name: str) -> None:
    allowlist = set(getattr(run.agent, "tool_allowlist", []) or [])
    if allowlist and tool_name not in allowlist:
        raise PermissionError(f"tool not allowed: {tool_name}")


def _enrich_tool_args_from_payload(tool_name: str, args: dict, payload: dict) -> dict:
    args = dict(args or {})
    map_context = payload.get("map_context") or {}

    if tool_name in {
        "spatial.summary",
        "spatial.context_pack",
        "spatial.query_layer",
        "spatial.intersects",
    }:
        if "bbox" not in args and map_context.get("bbox"):
            args["bbox"] = map_context["bbox"]

    if tool_name in {"spatial.summary", "spatial.context_pack"}:
        if "zoom" not in args and map_context.get("zoom") is not None:
            args["zoom"] = map_context["zoom"]

    return args


def _extract_step_references(value):
    if isinstance(value, str):
        return re.findall(r"\$step:([a-zA-Z0-9_\-]+)\.", value)
    if isinstance(value, list):
        refs = []
        for item in value:
            refs.extend(_extract_step_references(item))
        return refs
    if isinstance(value, dict):
        refs = []
        for item in value.values():
            refs.extend(_extract_step_references(item))
        return refs
    return []


def _resolve_step_references(value, executed_outputs_by_id):
    if isinstance(value, str):
        if not value.startswith("$step:"):
            return value

        path = value[len("$step:"):]
        if "." not in path:
            raise ValueError(f"Invalid step reference: {value}")

        step_id, rest = path.split(".", 1)
        if step_id not in executed_outputs_by_id:
            raise ValueError(f"Reference to unavailable step id: {step_id}")

        cursor = executed_outputs_by_id[step_id]
        for token in [p for p in rest.split(".") if p]:
            if isinstance(cursor, list):
                try:
                    idx = int(token)
                except ValueError as exc:
                    raise ValueError(f"Invalid list index in reference {value}: {token}") from exc
                if idx < 0 or idx >= len(cursor):
                    raise ValueError(f"List index out of bounds in reference {value}: {token}")
                cursor = cursor[idx]
            elif isinstance(cursor, dict):
                if token not in cursor:
                    raise ValueError(f"Missing field in reference {value}: {token}")
                cursor = cursor[token]
            else:
                raise ValueError(f"Cannot traverse token '{token}' in reference {value}")

        return cursor

    if isinstance(value, list):
        return [_resolve_step_references(v, executed_outputs_by_id) for v in value]

    if isinstance(value, dict):
        return {k: _resolve_step_references(v, executed_outputs_by_id) for k, v in value.items()}

    return value


def _compute_on_fail(required: bool, on_fail: Optional[str]) -> str:
    if on_fail in {"abort", "continue"}:
        return on_fail
    return "abort" if required else "continue"


def _build_execution_index(executed_outputs: List[dict]) -> Dict[str, dict]:
    index = {}
    for item in executed_outputs:
        step_id = item.get("id")
        if step_id:
            index[step_id] = item
    return index


def _safe_get_by_path(data: Any, path: str, default=None):
    if not path:
        return default

    cursor = data
    for token in [p for p in path.split(".") if p]:
        if isinstance(cursor, dict):
            if token not in cursor:
                return default
            cursor = cursor[token]
        elif isinstance(cursor, list):
            try:
                idx = int(token)
            except ValueError:
                return default
            if idx < 0 or idx >= len(cursor):
                return default
            cursor = cursor[idx]
        else:
            return default
    return cursor


def _criteria_operator(criteria: Dict[str, Any]) -> Optional[str]:
    for op in ("equals", "gt", "gte", "lt", "lte", "exists", "non_empty", "in"):
        if op in criteria:
            return op
    return None


def _evaluate_success_criteria(
    output_payload: Dict[str, Any],
    success_criteria: Dict[str, Any],
) -> Dict[str, Any]:
    if not success_criteria:
        return {
            "status": "not_evaluated",
            "criteria": {},
            "observed": None,
            "reason": "No success_criteria provided.",
        }

    path = success_criteria.get("path")
    operator = _criteria_operator(success_criteria)

    if not path or not operator:
        return {
            "status": "inconclusive",
            "criteria": success_criteria,
            "observed": None,
            "reason": "Malformed success_criteria.",
        }

    observed = _safe_get_by_path(output_payload, path, default=None)

    try:
        passed = False

        if operator == "equals":
            passed = observed == success_criteria.get("equals")
        elif operator == "gt":
            passed = observed is not None and observed > success_criteria.get("gt")
        elif operator == "gte":
            passed = observed is not None and observed >= success_criteria.get("gte")
        elif operator == "lt":
            passed = observed is not None and observed < success_criteria.get("lt")
        elif operator == "lte":
            passed = observed is not None and observed <= success_criteria.get("lte")
        elif operator == "exists":
            expected = bool(success_criteria.get("exists"))
            passed = (observed is not None) == expected
        elif operator == "non_empty":
            expected = bool(success_criteria.get("non_empty"))
            is_non_empty = observed is not None and hasattr(observed, "__len__") and len(observed) > 0
            passed = is_non_empty == expected
        elif operator == "in":
            options = success_criteria.get("in") or []
            passed = observed in options
        else:
            return {
                "status": "inconclusive",
                "criteria": success_criteria,
                "observed": observed,
                "reason": f"Unsupported operator: {operator}",
            }

        return {
            "status": "verified" if passed else "refuted",
            "criteria": success_criteria,
            "observed": observed,
            "reason": f"Evaluated {operator} on path '{path}'.",
        }

    except Exception as exc:
        return {
            "status": "inconclusive",
            "criteria": success_criteria,
            "observed": observed,
            "reason": f"Could not evaluate success_criteria: {exc}",
        }




def _summarize_verification(executed_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "verified": [],
        "refuted": [],
        "inconclusive": [],
        "not_evaluated": [],
        "counts": {
            "verified": 0,
            "refuted": 0,
            "inconclusive": 0,
            "not_evaluated": 0,
        },
    }

    for step in executed_outputs:
        if step.get("type") != "tool":
            continue

        verification = step.get("verification") or {}
        status = verification.get("status") or "not_evaluated"
        if status not in summary:
            status = "not_evaluated"

        item = {
            "id": step.get("id"),
            "tool": step.get("name"),
            "hypothesis": verification.get("hypothesis", ""),
            "target": verification.get("target", ""),
            "reason": verification.get("reason", ""),
            "observed": verification.get("observed"),
            "criteria": verification.get("criteria") or {},
            "ok": step.get("ok"),
            "error": step.get("error", ""),
            "depends_on": step.get("depends_on", []),
            "resolved_args": step.get("resolved_args", {}),
            "attempt_count": step.get("attempt_count", 0),
        }
        summary[status].append(item)
        summary["counts"][status] += 1

    return summary

def _build_step_verification(
    *,
    step: Dict[str, Any],
    tool_ok: bool,
    tool_data: Dict[str, Any],
    tool_error: str,
) -> Dict[str, Any]:
    success_criteria = step.get("success_criteria") or {}
    hypothesis = (step.get("hypothesis") or "").strip()
    verification_target = (step.get("verification_target") or "").strip() or hypothesis

    if not tool_ok:
        return {
            "status": "inconclusive",
            "target": verification_target,
            "hypothesis": hypothesis,
            "criteria": success_criteria,
            "observed": None,
            "reason": f"Tool execution failed before verification: {tool_error or 'unknown error'}",
        }

    evaluated = _evaluate_success_criteria(
        {
            "ok": tool_ok,
            "data": tool_data or {},
            "error": tool_error or "",
        },
        success_criteria,
    )
    return {
        "status": evaluated.get("status", "not_evaluated"),
        "target": verification_target,
        "hypothesis": hypothesis,
        "criteria": evaluated.get("criteria", success_criteria),
        "observed": evaluated.get("observed"),
        "reason": evaluated.get("reason", ""),
    }


def _should_replan(
    *,
    step: Dict[str, Any],
    step_result: Dict[str, Any],
    replan_count: int,
) -> bool:
    if replan_count >= MAX_REPLANS:
        return False
    if not bool(step.get("can_replan", False)):
        return False

    if not step_result.get("ok"):
        return True

    verification_status = ((step_result.get("verification") or {}).get("status") or "").strip()
    return verification_status in {"refuted", "inconclusive"}


def _build_replan_execution_context(
    *,
    payload: Dict[str, Any],
    executed_outputs: List[Dict[str, Any]],
    failed_step: Dict[str, Any],
    previous_plan: Dict[str, Any],
    replan_count: int,
) -> Dict[str, Any]:
    return {
        "goal": payload.get("goal", ""),
        "map_context": payload.get("map_context") or {},
        "replan_count": replan_count,
        "previous_plan_steps": previous_plan.get("steps", []),
        "executed_steps": executed_outputs,
        "last_step": failed_step,
    }


def _tool_steps_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in (plan.get("steps") or []) if s.get("type") == "tool"]


def _enforce_plan_limits(plan: Dict[str, Any]) -> None:
    tool_steps = _tool_steps_from_plan(plan)
    if len(tool_steps) > MAX_PLANNER_TOOL_STEPS:
        raise ValueError(
            f"Planner produced too many tool steps: {len(tool_steps)} > {MAX_PLANNER_TOOL_STEPS}"
        )


def _find_resume_index(steps: List[Dict[str, Any]], executed_outputs: List[Dict[str, Any]]) -> int:
    executed_ids = {item.get("id") for item in executed_outputs if item.get("id")}
    for idx, step in enumerate(steps):
        if step.get("type") != "tool":
            continue
        if step.get("id") not in executed_ids:
            return idx
    return len(steps)


def _execute_tool_step(
    *,
    run: Run,
    step: Dict[str, Any],
    payload: Dict[str, Any],
    executed_outputs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    required = bool(step.get("required", True))
    step_id = (step.get("id") or "").strip() or None
    hypothesis = (step.get("hypothesis") or "").strip()
    verification_target = (step.get("verification_target") or "").strip()
    depends_on = step.get("depends_on") or []
    on_fail = _compute_on_fail(required, step.get("on_fail"))
    tool_name = (step.get("name") or "").strip()
    success_criteria = step.get("success_criteria") or {}
    timeout_s = step.get("timeout_s", 0) or 0
    max_retries = step.get("max_retries", DEFAULT_STEP_MAX_RETRIES) or 0
    retry_backoff_s = step.get("retry_backoff_s", DEFAULT_STEP_RETRY_BACKOFF_S) or 0.0
    can_replan = bool(step.get("can_replan", False))

    if not tool_name:
        raise ValueError("Planner produced a tool step without name")

    args = _enrich_tool_args_from_payload(
        tool_name=tool_name,
        args=step.get("args") or {},
        payload=payload,
    )

    executed_outputs_by_id = _build_execution_index(executed_outputs)
    missing_dependencies = [dep for dep in depends_on if dep not in executed_outputs_by_id]
    if missing_dependencies:
        raise ValueError(
            f"Step {step_id or tool_name} depends on unavailable steps: {missing_dependencies}"
        )

    referenced_steps = sorted(set(_extract_step_references(args)))
    missing_references = [ref for ref in referenced_steps if ref not in executed_outputs_by_id]
    if missing_references:
        raise ValueError(
            f"Step {step_id or tool_name} references unavailable steps: {missing_references}"
        )

    resolved_args = _resolve_step_references(args, executed_outputs_by_id)

    _ensure_tool_allowed(run, tool_name)

    attempts: List[Dict[str, Any]] = []
    total_latency_ms = 0
    last_tool_res = None
    last_latency_ms = 0

    for attempt in range(max_retries + 1):
        if attempt > 0 and retry_backoff_s > 0:
            time.sleep(float(retry_backoff_s))

        attempt_started_at = time.perf_counter()
        tool_res, latency_ms = invoke_tool(
            run=run,
            tool_name=tool_name,
            args=resolved_args,
            user=run.user,
        )
        elapsed_ms = int((time.perf_counter() - attempt_started_at) * 1000.0)

        total_latency_ms += latency_ms
        last_tool_res = tool_res
        last_latency_ms = latency_ms

        timeout_exceeded = bool(timeout_s and (elapsed_ms / 1000.0) > float(timeout_s))
        attempts.append(
            {
                "attempt": attempt + 1,
                "ok": tool_res.ok,
                "error": tool_res.error,
                "latency_ms": latency_ms,
                "elapsed_ms": elapsed_ms,
                "timeout_exceeded": timeout_exceeded,
            }
        )

        if timeout_exceeded:
            if attempt < max_retries:
                continue
            last_tool_res.ok = False
            last_tool_res.error = (
                f"step timeout exceeded: {elapsed_ms / 1000.0:.3f}s > {float(timeout_s):.3f}s"
            )
            break

        if tool_res.ok:
            break

        if attempt >= max_retries:
            break

    tool_ok = bool(last_tool_res and last_tool_res.ok)
    tool_data = (last_tool_res.data if last_tool_res else {}) or {}
    tool_error = (last_tool_res.error if last_tool_res else "tool failed") or "tool failed"

    verification = _build_step_verification(
        step=step,
        tool_ok=tool_ok,
        tool_data=tool_data,
        tool_error=tool_error,
    )

    result = {
        "id": step_id,
        "type": "tool",
        "name": tool_name,
        "required": required,
        "hypothesis": hypothesis,
        "verification_target": verification_target,
        "success_criteria": success_criteria,
        "depends_on": depends_on,
        "on_fail": on_fail,
        "can_replan": can_replan,
        "resolved_args": resolved_args,
        "ok": tool_ok,
        "data": tool_data,
        "error": "" if tool_ok else tool_error,
        "timeout_s": timeout_s,
        "attempts": attempts,
        "attempt_count": len(attempts),
        "latency_ms": last_latency_ms,
        "latency_ms_total": total_latency_ms,
        "verification": verification,
    }

    return result


def _append_plan_history(plan_history: List[Dict[str, Any]], plan: Dict[str, Any], label: str) -> None:
    plan_history.append(
        {
            "label": label,
            "steps": copy.deepcopy(plan.get("steps", [])),
            "_meta": copy.deepcopy(plan.get("_meta", {})),
        }
    )


def execute_run(run: Run) -> Run:
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    log_step(
        run,
        kind="system",
        name="run.start",
        input_json={"agent_id": run.agent_id, "user_id": run.user_id},
        output_json={"status": "running"},
    )

    try:
        payload = run.input_json or {}

        tool_call = payload.get("tool_call")
        if tool_call:
            tool_name = (tool_call.get("name") or "").strip()
            args = tool_call.get("args") or {}

            if not tool_name:
                raise ValueError("tool_call.name is required")

            _ensure_tool_allowed(run, tool_name)

            tool_res, _latency_ms = invoke_tool(
                run=run,
                tool_name=tool_name,
                args=args,
                user=run.user,
            )

            result = {
                "ok": tool_res.ok,
                "tool": tool_name,
                "data": tool_res.data,
                "error": tool_res.error,
                "verification_summary": {
                    "verified": [],
                    "refuted": [],
                    "inconclusive": [],
                    "not_evaluated": [],
                    "counts": {
                        "verified": 0,
                        "refuted": 0,
                        "inconclusive": 0,
                        "not_evaluated": 0,
                    },
                },
            }

            log_step(
                run,
                kind="result",
                name="tool.result",
                input_json={"tool_call": tool_call},
                output_json=result,
            )

            run.output_json = result
            run.final_text = ""
            run.status = "succeeded" if tool_res.ok else "failed"
            run.error = "" if tool_res.ok else (tool_res.error or "tool failed")
            run.ended_at = timezone.now()
            run.save(update_fields=["output_json", "final_text", "status", "error", "ended_at"])
            persist_run_intelligence(run)

            log_step(
                run,
                kind="system",
                name="run.end",
                input_json={},
                output_json={"status": run.status},
            )
            return run

        goal = (payload.get("goal") or "").strip()
        if goal:
            plan = plan_run(run, payload)
            _enforce_plan_limits(plan)

            plan_history: List[Dict[str, Any]] = []
            _append_plan_history(plan_history, plan, "initial")

            log_step(
                run,
                kind="llm",
                name="llm.plan",
                input_json={"goal": goal, "execution_context": {}},
                output_json=plan,
            )

            executed_outputs: List[Dict[str, Any]] = []
            replan_count = 0

            while True:
                steps = plan.get("steps", [])
                start_idx = _find_resume_index(steps, executed_outputs)
                replan_triggered = False

                for idx in range(start_idx, len(steps)):
                    step = steps[idx]
                    step_type = step.get("type")

                    if step_type == "final":
                        break

                    if step_type != "tool":
                        raise ValueError(f"Unknown planner step type: {step_type}")

                    step_result = _execute_tool_step(
                        run=run,
                        step=step,
                        payload=payload,
                        executed_outputs=executed_outputs,
                    )
                    executed_outputs.append(step_result)

                    if _should_replan(
                        step=step,
                        step_result=step_result,
                        replan_count=replan_count,
                    ):
                        replan_count += 1
                        execution_context = _build_replan_execution_context(
                            payload=payload,
                            executed_outputs=executed_outputs,
                            failed_step=step_result,
                            previous_plan=plan,
                            replan_count=replan_count,
                        )

                        log_step(
                            run,
                            kind="llm",
                            name="llm.replan.request",
                            input_json={"goal": goal, "execution_context": execution_context},
                            output_json={},
                        )

                        plan = plan_run(
                            run,
                            payload,
                            execution_context=execution_context,
                        )
                        _enforce_plan_limits(plan)
                        _append_plan_history(plan_history, plan, f"replan_{replan_count}")

                        log_step(
                            run,
                            kind="llm",
                            name="llm.replan",
                            input_json={"goal": goal, "execution_context": execution_context},
                            output_json=plan,
                        )

                        replan_triggered = True
                        break

                    if not step_result.get("ok") and step_result.get("on_fail") == "abort":
                        raise ValueError(
                            f"Tool step failed with abort policy: {step_result.get('name')} -> {step_result.get('error')}"
                        )

                if not replan_triggered:
                    break

            final_text = synthesize_run(
                goal=goal,
                agent_name=run.agent.name,
                agent_profile=getattr(run.agent, "profile", "compact"),
                plan=plan,
                step_outputs=executed_outputs,
            )

            log_step(
                run,
                kind="llm",
                name="llm.synthesize",
                input_json={"goal": goal, "step_outputs": executed_outputs},
                output_json={"final_text": final_text},
            )

            verification_summary = _summarize_verification(executed_outputs)

            result = {
                "ok": True,
                "goal": goal,
                "plan": plan,
                "plan_history": plan_history,
                "replan_count": replan_count,
                "executed_outputs": executed_outputs,
                "verification_summary": verification_summary,
                "final_text": final_text,
            }

            log_step(
                run,
                kind="result",
                name="planner.result",
                input_json={"goal": goal},
                output_json=result,
            )

            run.output_json = result
            run.final_text = final_text
            run.status = "succeeded"
            run.error = ""
            run.ended_at = timezone.now()
            run.save(update_fields=["output_json", "final_text", "status", "error", "ended_at"])
            persist_run_intelligence(run)

            log_step(
                run,
                kind="system",
                name="run.end",
                input_json={},
                output_json={"status": "succeeded"},
            )
            return run

        fallback = {
            "ok": True,
            "echo": payload,
            "agent_name": run.agent.name,
            "verification_summary": {
                "verified": [],
                "refuted": [],
                "inconclusive": [],
                "not_evaluated": [],
                "counts": {
                    "verified": 0,
                    "refuted": 0,
                    "inconclusive": 0,
                    "not_evaluated": 0,
                },
            },
        }

        log_step(
            run,
            kind="result",
            name="mock.result",
            input_json={},
            output_json=fallback,
        )

        run.output_json = fallback
        run.status = "succeeded"
        run.error = ""
        run.ended_at = timezone.now()
        run.save(update_fields=["output_json", "status", "error", "ended_at"])
        persist_run_intelligence(run)

        log_step(
            run,
            kind="system",
            name="run.end",
            input_json={},
            output_json={"status": "succeeded"},
        )
        return run

    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        run.ended_at = timezone.now()
        run.save(update_fields=["status", "error", "ended_at"])
        persist_run_intelligence(run)

        log_step(
            run,
            kind="error",
            name="exception",
            input_json={},
            output_json={},
            error=str(e),
        )
        return run