from django.utils import timezone
from django.conf import settings
import re

from .models import Run
from .steps import log_step

from agents_tools.executor import invoke_tool
from agents_llm.planner import plan_run
from agents_llm.synthesizer import synthesize_run

MAX_PLANNER_TOOL_STEPS = getattr(settings, "AGENTS_MAX_PLANNER_TOOL_STEPS", 5)

def _ensure_tool_allowed(run: Run, tool_name: str) -> None:
    allowlist = set(getattr(run.agent, "tool_allowlist", []) or [])
    if allowlist and tool_name not in allowlist:
        raise PermissionError(f"tool not allowed: {tool_name}")

def _enrich_tool_args_from_payload(tool_name: str, args: dict, payload: dict) -> dict:
    args = dict(args or {})
    map_context = payload.get("map_context") or {}

    # bbox automático para tools GIS que la necesitan
    if tool_name in {
        "spatial.summary",
        "spatial.context_pack",
        "spatial.query_layer",
        "spatial.intersects",
    }:
        if "bbox" not in args and map_context.get("bbox"):
            args["bbox"] = map_context["bbox"]

    # zoom automático si existe
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


def _compute_on_fail(required: bool, on_fail: str | None) -> str:
    if on_fail in {"abort", "continue"}:
        return on_fail
    return "abort" if required else "continue"


def _build_execution_index(executed_outputs: list[dict]) -> dict:
    index = {}
    for item in executed_outputs:
        step_id = item.get("id")
        if step_id:
            index[step_id] = item
    return index


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

        # ------------------------------------------------------------
        # MODO 1: tool_call directo
        # ------------------------------------------------------------
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

            log_step(
                run,
                kind="system",
                name="run.end",
                input_json={},
                output_json={"status": run.status},
            )
            return run

        # ------------------------------------------------------------
        # MODO 2: planner LLM
        # ------------------------------------------------------------
        goal = (payload.get("goal") or "").strip()
        if goal:
            plan = plan_run(run, payload)

            log_step(
                run,
                kind="llm",
                name="llm.plan",
                input_json={"goal": goal},
                output_json=plan,
            )

            steps = plan.get("steps", [])

            tool_steps = [s for s in steps if s.get("type") == "tool"]
            if len(tool_steps) > MAX_PLANNER_TOOL_STEPS:
                raise ValueError(
                    f"Planner produced too many tool steps: {len(tool_steps)} > {MAX_PLANNER_TOOL_STEPS}"
                )

            executed_outputs = []

            for step in steps:
                step_type = step.get("type")

                if step_type == "tool":
                    required = bool(step.get("required", True))
                    step_id = (step.get("id") or "").strip() or None
                    hypothesis = (step.get("hypothesis") or "").strip()
                    depends_on = step.get("depends_on") or []
                    on_fail = _compute_on_fail(required, step.get("on_fail"))
                    tool_name = (step.get("name") or "").strip()
                    args = _enrich_tool_args_from_payload(
                        tool_name=tool_name,
                        args=step.get("args") or {},
                        payload=payload,
                    )

                    if not tool_name:
                        raise ValueError("Planner produced a tool step without name")

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

                    args = _resolve_step_references(args, executed_outputs_by_id)

                    _ensure_tool_allowed(run, tool_name)

                    tool_res, _latency_ms = invoke_tool(
                        run=run,
                        tool_name=tool_name,
                        args=args,
                        user=run.user,
                    )

                    executed_outputs.append(
                        {
                            "id": step_id,
                            "type": "tool",
                            "name": tool_name,
                            "required": required,
                            "hypothesis": hypothesis,
                            "depends_on": depends_on,
                            "on_fail": on_fail,
                            "resolved_args": args,
                            "ok": tool_res.ok,
                            "data": tool_res.data,
                            "error": tool_res.error,
                        }
                    )

                    if not tool_res.ok and on_fail == "abort":
                        raise ValueError(f"Tool step failed with abort policy: {tool_name} -> {tool_res.error}")

                elif step_type == "final":
                    break

                else:
                    raise ValueError(f"Unknown planner step type: {step_type}")

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

            result = {
                "ok": True,
                "goal": goal,
                "plan": plan,
                "executed_outputs": executed_outputs,
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

            log_step(
                run,
                kind="system",
                name="run.end",
                input_json={},
                output_json={"status": "succeeded"},
            )
            return run

        # ------------------------------------------------------------
        # Fallback
        # ------------------------------------------------------------
        fallback = {
            "ok": True,
            "echo": payload,
            "agent_name": run.agent.name,
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

        log_step(
            run,
            kind="error",
            name="exception",
            input_json={},
            output_json={},
            error=str(e),
        )
        return run