from rest_framework import serializers

from .models import Agent, Episode, Run, RunMemory, RunStep


def _empty_verification_item():
    return {
        "id": "",
        "tool": "",
        "hypothesis": "",
        "target": "",
        "reason": "",
        "observed": None,
        "criteria": {},
        "ok": None,
        "error": "",
        "depends_on": [],
        "resolved_args": {},
        "attempt_count": 0,
    }


def _empty_verification_summary():
    return {
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


def _normalize_verification_summary(summary, *, ensure_placeholder=False):
    base = _empty_verification_summary()
    summary = summary or {}

    normalized = {
        "verified": list(summary.get("verified") or []),
        "refuted": list(summary.get("refuted") or []),
        "inconclusive": list(summary.get("inconclusive") or []),
        "not_evaluated": list(summary.get("not_evaluated") or []),
        "counts": dict(base["counts"]),
    }

    counts = summary.get("counts") or {}
    normalized["counts"].update(
        {
            "verified": int(counts.get("verified", len(normalized["verified"])) or 0),
            "refuted": int(counts.get("refuted", len(normalized["refuted"])) or 0),
            "inconclusive": int(
                counts.get("inconclusive", len(normalized["inconclusive"])) or 0
            ),
            "not_evaluated": int(
                counts.get("not_evaluated", len(normalized["not_evaluated"])) or 0
            ),
        }
    )

    normalized["counts"]["verified"] = len(normalized["verified"])
    normalized["counts"]["refuted"] = len(normalized["refuted"])
    normalized["counts"]["inconclusive"] = len(normalized["inconclusive"])
    normalized["counts"]["not_evaluated"] = len(normalized["not_evaluated"])

    has_any_items = any(
        normalized["counts"][key] > 0
        for key in ("verified", "refuted", "inconclusive", "not_evaluated")
    )

    if ensure_placeholder and not has_any_items:
        normalized["not_evaluated"] = [_empty_verification_item()]
        normalized["counts"]["not_evaluated"] = 1

    return normalized


class AgentSerializer(serializers.ModelSerializer):
    gis_layers_count = serializers.SerializerMethodField()

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
            # GIS connections & catalog
            "gis_db_connections",
            "gis_layers_catalog",
            "gis_catalog_updated_at",
            "gis_layers_count",
        ]
        read_only_fields = ["id", "created_at", "gis_layers_catalog", "gis_catalog_updated_at", "gis_layers_count"]

    def get_gis_layers_count(self, obj):
        return len(obj.gis_layers_catalog or [])


class RunMemorySerializer(serializers.ModelSerializer):
    verification_summary = serializers.SerializerMethodField()

    class Meta:
        model = RunMemory
        fields = [
            "normalized_goal",
            "goal_signature",
            "domain",
            "analysis_types",
            "layers",
            "tools_used",
            "tool_sequence_signature",
            "final_plan",
            "plan_history",
            "structured_results",
            "verification_summary",
            "verification_status",
            "outcome",
            "errors",
            "failure_modes",
            "replans",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_verification_summary(self, obj):
        return _normalize_verification_summary(obj.verification_summary)


class EpisodeSerializer(serializers.ModelSerializer):
    verification_summary = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = [
            "normalized_goal",
            "goal_signature",
            "domain",
            "analysis_types",
            "tools_used",
            "tool_sequence",
            "tool_sequence_signature",
            "outcome_status",
            "verification_status",
            "success",
            "failure_mode",
            "failure_modes",
            "recommended_strategy",
            "verification_summary",
            "evidence",
            "replan_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_verification_summary(self, obj):
        return _normalize_verification_summary(obj.verification_summary)


def _safe_memory(obj):
    try:
        return obj.memory
    except Run.memory.RelatedObjectDoesNotExist:
        return None


def _safe_episode(obj):
    try:
        return obj.episode
    except Run.episode.RelatedObjectDoesNotExist:
        return None


class RunSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.name", read_only=True)
    verification_summary = serializers.SerializerMethodField()
    replan_count = serializers.SerializerMethodField()
    plan_history = serializers.SerializerMethodField()
    executed_outputs = serializers.SerializerMethodField()
    run_memory = serializers.SerializerMethodField()
    episode = serializers.SerializerMethodField()

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
            "run_memory",
            "episode",
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
            "run_memory",
            "episode",
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

    def get_run_memory(self, obj):
        memory = _safe_memory(obj)
        if not memory:
            return None
        return RunMemorySerializer(memory).data

    def get_episode(self, obj):
        episode = _safe_episode(obj)
        if not episode:
            return None
        return EpisodeSerializer(episode).data

    def get_verification_summary(self, obj):
        memory = _safe_memory(obj)
        if memory and memory.verification_summary:
            return _normalize_verification_summary(memory.verification_summary)

        output_summary = self._output(obj).get("verification_summary")
        if output_summary:
            return _normalize_verification_summary(output_summary)

        executed_outputs = self.get_executed_outputs(obj)
        summary = _empty_verification_summary()

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

        return _normalize_verification_summary(summary)


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

    def _build_verification_from_outputs(self, executed_outputs):
        summary = _empty_verification_summary()

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

    def get_steps(self, obj):
        qs = RunStep.objects.filter(run=obj).order_by("idx")
        return RunStepSerializer(qs, many=True).data

    def get_trace(self, obj):
        output = obj.output_json or {}
        raw_executed_outputs = output.get("executed_outputs", [])
        executed_outputs = self._normalize_executed_outputs(raw_executed_outputs)
        plan_history = output.get("plan_history", [])
        memory = _safe_memory(obj)
        episode = _safe_episode(obj)

        verification_source = None
        if memory and memory.verification_summary:
            verification_source = memory.verification_summary
        elif output.get("verification_summary"):
            verification_source = output.get("verification_summary")
        else:
            verification_source = self._build_verification_from_outputs(executed_outputs)

        verification = _normalize_verification_summary(
            verification_source,
            ensure_placeholder=True,
        )

        total_attempts = 0
        total_latency_ms = 0

        for step in executed_outputs:
            if step.get("type") != "tool":
                continue
            total_attempts += step.get("attempt_count", 0) or 0
            total_latency_ms += step.get("latency_ms_total", 0) or 0

        return {
            "goal": (obj.input_json or {}).get("goal", ""),
            "plan": output.get("plan", {}),
            "plan_history": plan_history,
            "replan_count": output.get("replan_count", 0),
            "executed_outputs": executed_outputs,
            "verification_summary": verification,
            "run_memory": RunMemorySerializer(memory).data if memory else None,
            "episode": EpisodeSerializer(episode).data if episode else None,
            "stats": {
                "tool_steps_executed": len(
                    [s for s in executed_outputs if s.get("type") == "tool"]
                ),
                "total_attempts": total_attempts,
                "total_latency_ms": total_latency_ms,
                "persisted_steps": RunStep.objects.filter(run=obj).count(),
            },
        }