from rest_framework import serializers
from .models import Agent, Run, RunStep


class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "system_prompt", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = [
            "id",
            "agent",
            "user",
            "status",
            "input_json",
            "output_json",
            "final_text",
            "error",
            "created_at",
            "started_at",
            "ended_at",
        ]
        read_only_fields = ["id", "user", "status", "output_json", "final_text", "error", "created_at", "started_at", "ended_at"]


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