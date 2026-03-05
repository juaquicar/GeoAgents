from django.utils import timezone

from .models import Run
from .steps import log_step

from agents_tools.executor import invoke_tool


def execute_run(run: Run) -> Run:
    # --- start ---
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

        # ============================================================
        # 10.7 Tool-call path (MVP)
        # Si el input trae {"tool_call": {"name": "...", "args": {...}}}
        # ejecutamos la tool y devolvemos su salida como resultado.
        # ============================================================
        tool_call = payload.get("tool_call")
        if tool_call:
            tool_name = (tool_call.get("name") or "").strip()
            args = tool_call.get("args") or {}

            if not tool_name:
                raise ValueError("tool_call.name is required")

            # Allowlist (si existe el campo en Agent)
            allowlist = set(getattr(run.agent, "tool_allowlist", []) or [])
            if allowlist and tool_name not in allowlist:
                raise PermissionError(f"tool not allowed: {tool_name}")

            # Ejecutar tool (esto ya crea RunStep(kind='tool') con latency y output)
            tool_res, _latency_ms = invoke_tool(
                run=run,
                tool_name=tool_name,
                args=args,
                user=run.user,
            )

            # Resultado final del run basado en la tool
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
            run.status = "succeeded" if tool_res.ok else "failed"
            run.error = "" if tool_res.ok else (tool_res.error or "tool failed")
            run.ended_at = timezone.now()
            run.save(update_fields=["output_json", "status", "error", "ended_at"])

            log_step(
                run,
                kind="system",
                name="run.end",
                input_json={},
                output_json={"status": run.status},
            )
            return run

        # ============================================================
        # Fallback: comportamiento previo (mock plan + mock result)
        # ============================================================

        # Step: "plan" (de momento mock)
        plan = {
            "type": "single_step",
            "next": "result",
        }
        log_step(
            run,
            kind="plan",
            name="mock.plan",
            input_json={"input": payload},
            output_json=plan,
        )

        # Step: "result" (mock)
        result = {
            "ok": True,
            "echo": payload,
            "agent_name": run.agent.name,
        }
        log_step(
            run,
            kind="result",
            name="mock.result",
            input_json={"plan": plan},
            output_json=result,
        )

        run.output_json = result
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