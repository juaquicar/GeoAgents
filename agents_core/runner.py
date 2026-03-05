from django.utils import timezone
from .models import Run
from .steps import log_step


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

        # Step: "plan" (de momento mock)
        plan = {
            "type": "single_step",
            "next": "result",
        }
        log_step(run, kind="plan", name="mock.plan", input_json={"input": payload}, output_json=plan)

        # Step: "result" (mock)
        result = {
            "ok": True,
            "echo": payload,
            "agent_name": run.agent.name,
        }
        log_step(run, kind="result", name="mock.result", input_json={"plan": plan}, output_json=result)

        run.output_json = result
        run.status = "succeeded"
        run.ended_at = timezone.now()
        run.save(update_fields=["output_json", "status", "ended_at"])

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