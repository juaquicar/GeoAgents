from rest_framework import serializers

from .models import Agent, Run, RunStep


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = [
            "id",
            "name",
            "system_prompt",
            "is_active",
            "tool_allowlist",
            "profile",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class RunSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    verification_summary = serializers.SerializerMethodField()
    replan_count = serializers.SerializerMethodField()
    plan_history = serializers.SerializerMethodField()
    executed_outputs = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = [
            "id",
            "agent",
            "agent_name",
            "user",
            "status",
            "input_json",
            "output_json",
            "final_text",
            "error",
            "verification_summary",
            "replan_count",
            "plan_history",
            "executed_outputs",
            "created_at",
            "started_at",
            "ended_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "status",
            "output_json",
            "final_text",
            "error",
            "verification_summary",
            "replan_count",
            "plan_history",
            "executed_outputs",
            "created_at",
            "started_at",
            "ended_at",
        ]

    def _output(self, obj):
        return obj.output_json or {}

    def _normalize_executed_outputs(self, raw_steps):
        normalized = []

        for step in raw_steps:
            verification = step.get("verification") or {}
            success_criteria = step.get("success_criteria") or {}

            normalized.append(
                {
                    "id": step.get("id"),
                    "type": step.get("type"),
                    "name": step.get("name"),
                    "ok": step.get("ok"),
                    "data": step.get("data", {}),
                    "error": step.get("error", ""),
                    "required": step.get("required", True),
                    "depends_on": step.get("depends_on", []),
                    "resolved_args": step.get("resolved_args", {}),
                    "attempts": step.get("attempts", []),
                    "attempt_count": step.get("attempt_count", 0),
                    "latency_ms": step.get("latency_ms", 0),
                    "latency_ms_total": step.get("latency_ms_total", 0),
                    "success_criteria": success_criteria,
                    "verification": {
                        "status": verification.get("status", "not_evaluated"),
                        "reason": verification.get("reason", ""),
                        "target": verification.get("target", ""),
                        "criteria": verification.get("criteria", success_criteria),
                        "observed": verification.get("observed"),
                        "hypothesis": verification.get(
                            "hypothesis",
                            step.get("hypothesis", ""),
                        ),
                    },
                }
            )

        return normalized

    def get_replan_count(self, obj):
        return self._output(obj).get("replan_count", 0)

    def get_plan_history(self, obj):
        return self._output(obj).get("plan_history", [])

    def get_executed_outputs(self, obj):
        raw_steps = self._output(obj).get("executed_outputs", [])
        return self._normalize_executed_outputs(raw_steps)

    def get_verification_summary(self, obj):
        executed_outputs = self.get_executed_outputs(obj)

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


class RunStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunStep
        fields = [
            "id",
            "run",
            "idx",
            "kind",
            "name",
            "input_json",
            "output_json",
            "latency_ms",
            "error",
            "created_at",
        ]
        read_only_fields = fields


class RunTraceSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    steps = serializers.SerializerMethodField()
    trace = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = [
            "id",
            "agent",
            "agent_name",
            "user",
            "status",
            "input_json",
            "output_json",
            "final_text",
            "error",
            "created_at",
            "started_at",
            "ended_at",
            "steps",
            "trace",
        ]
        read_only_fields = fields

    def _normalize_executed_outputs(self, raw_steps):
        normalized = []

        for step in raw_steps:
            verification = step.get("verification") or {}
            success_criteria = step.get("success_criteria") or {}

            normalized.append(
                {
                    "id": step.get("id"),
                    "type": step.get("type"),
                    "name": step.get("name"),
                    "ok": step.get("ok"),
                    "data": step.get("data", {}),
                    "error": step.get("error", ""),
                    "required": step.get("required", True),
                    "depends_on": step.get("depends_on", []),
                    "resolved_args": step.get("resolved_args", {}),
                    "attempts": step.get("attempts", []),
                    "attempt_count": step.get("attempt_count", 0),
                    "latency_ms": step.get("latency_ms", 0),
                    "latency_ms_total": step.get("latency_ms_total", 0),
                    "success_criteria": success_criteria,
                    "verification": {
                        "status": verification.get("status", "not_evaluated"),
                        "reason": verification.get("reason", ""),
                        "target": verification.get("target", ""),
                        "criteria": verification.get("criteria", success_criteria),
                        "observed": verification.get("observed"),
                        "hypothesis": verification.get(
                            "hypothesis",
                            step.get("hypothesis", ""),
                        ),
                    },
                }
            )

        return normalized

    def get_steps(self, obj):
        qs = RunStep.objects.filter(run=obj).order_by("idx")
        return RunStepSerializer(qs, many=True).data

    def get_trace(self, obj):
        output = obj.output_json or {}
        raw_executed_outputs = output.get("executed_outputs", [])
        executed_outputs = self._normalize_executed_outputs(raw_executed_outputs)
        plan_history = output.get("plan_history", [])

        verification = {
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

        total_attempts = 0
        total_latency_ms = 0

        for step in executed_outputs:
            if step.get("type") != "tool":
                continue

            total_attempts += step.get("attempt_count", 0) or 0
            total_latency_ms += step.get("latency_ms_total", 0) or 0

            v = step.get("verification") or {}
            status = v.get("status") or "not_evaluated"
            if status not in verification:
                status = "not_evaluated"

            item = {
                "id": step.get("id"),
                "tool": step.get("name"),
                "ok": step.get("ok"),
                "hypothesis": v.get("hypothesis") or "",
                "target": v.get("target") or "",
                "criteria": v.get("criteria") or {},
                "observed": v.get("observed"),
                "reason": v.get("reason") or "",
                "depends_on": step.get("depends_on", []),
                "resolved_args": step.get("resolved_args", {}),
                "attempt_count": step.get("attempt_count", 0),
                "latency_ms": step.get("latency_ms", 0),
                "latency_ms_total": step.get("latency_ms_total", 0),
                "error": step.get("error", ""),
            }
            verification[status].append(item)
            verification["counts"][status] += 1

        return {
            "goal": (obj.input_json or {}).get("goal", ""),
            "plan": output.get("plan", {}),
            "plan_history": plan_history,
            "replan_count": output.get("replan_count", 0),
            "executed_outputs": executed_outputs,
            "verification_summary": verification,
            "stats": {
                "tool_steps_executed": len(
                    [s for s in executed_outputs if s.get("type") == "tool"]
                ),
                "total_attempts": total_attempts,
                "total_latency_ms": total_latency_ms,
                "persisted_steps": RunStep.objects.filter(run=obj).count(),
            },
        }