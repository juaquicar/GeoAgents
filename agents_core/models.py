from django.conf import settings
from django.db import models


class Agent(models.Model):
    """
    Definición de un agente (MVP).
    Más adelante: versionado, tool_allowlist, policies, etc.
    """
    name = models.CharField(max_length=120, unique=True)
    system_prompt = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Run(models.Model):
    """
    Ejecución de un agente sobre un input.
    """
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="runs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")

    # Inputs y outputs en JSON (sin schema rígido en MVP)
    input_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)

    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    step_seq = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Run#{self.pk} agent={self.agent.pk} status={self.status}"


class RunStep(models.Model):
    """
    Un paso atómico dentro de un Run:
    - planner (plan)
    - tool call
    - llm call
    - synthesis (respuesta final)
    etc.
    """
    KIND_CHOICES = [
        ("system", "System"),
        ("plan", "Plan"),
        ("llm", "LLM"),
        ("tool", "Tool"),
        ("result", "Result"),
        ("error", "Error"),
    ]

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="steps")
    idx = models.PositiveIntegerField(default=0)

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    name = models.CharField(max_length=120, blank=True, default="")  # ej: tool name, modelo LLM, etc.

    input_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)

    latency_ms = models.IntegerField(default=0)
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["run", "idx"]),
            models.Index(fields=["run", "kind"]),
        ]
        ordering = ["run_id", "idx"]

    def __str__(self):
        return f"RunStep#{self.pk} run={self.run.pk} idx={self.idx} kind={self.kind} name={self.name}"