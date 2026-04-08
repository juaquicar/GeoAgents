from django.conf import settings
from django.db import models


class Agent(models.Model):
    """
    Definición de un agente.
    Cada agente puede tener sus propias conexiones a BBDDs GIS remotas
    y un catálogo de capas auto-generado mediante introspección.
    """
    PROFILE_CHOICES = [
        ("compact", "Compact"),
        ("rich", "Rich"),
        ("investigate", "Investigate"),
    ]

    name = models.CharField(max_length=120, unique=True)
    system_prompt = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    profile = models.CharField(
        max_length=20,
        choices=PROFILE_CHOICES,
        default="compact",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    tool_allowlist = models.JSONField(default=list, blank=True)  # ["utils.ping","utils.now"]

    # Conexiones GIS propias del agente.
    # Formato de cada elemento:
    # {
    #   "alias": "main",          # nombre interno corto
    #   "host": "...",
    #   "port": 5432,
    #   "db_name": "...",
    #   "user": "...",
    #   "password": "...",
    #   "schema": "public",
    #   "sslmode": "",            # opcional: "require", "disable", etc.
    #   "is_default": true        # la conexión principal del agente
    # }
    gis_db_connections = models.JSONField(
        default=list,
        blank=True,
        help_text="Conexiones a BBDDs GIS remotas de este agente.",
    )

    # Catálogo de capas GIS (auto-generado por introspección al guardar).
    # Si está vacío, se usan las capas de settings.AGENTS_GIS_LAYERS como fallback.
    gis_layers_catalog = models.JSONField(
        default=list,
        blank=True,
        help_text="Catálogo de capas GIS. Se regenera automáticamente al guardar conexiones.",
    )

    gis_catalog_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Última vez que se ejecutó la introspección del catálogo.",
    )

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

    final_text = models.TextField(blank=True, default="")
    final_sql = models.TextField(blank=True, default="")

    # Identificador de sesión conversacional.
    # Runs con el mismo session_id forman una conversación multi-turno.
    # El planner recibe el historial condensado de la sesión como contexto.
    session_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Sesión conversacional. Runs con el mismo session_id reciben contexto de turnos anteriores.",
    )

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


class RunMemory(models.Model):
    """
    Memoria operacional persistida de un run para búsqueda y debugging.
    """

    run = models.OneToOneField(Run, on_delete=models.CASCADE, related_name="memory")
    normalized_goal = models.TextField(blank=True, default="")
    goal_signature = models.CharField(max_length=255, blank=True, default="", db_index=True)
    domain = models.CharField(max_length=64, blank=True, default="", db_index=True)
    analysis_types = models.JSONField(default=list, blank=True)
    analysis_types_search = models.TextField(blank=True, default="")
    layers = models.JSONField(default=list, blank=True)
    layers_search = models.TextField(blank=True, default="")
    tools_used = models.JSONField(default=list, blank=True)
    tools_search = models.TextField(blank=True, default="")
    tool_sequence_signature = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )
    final_plan = models.JSONField(default=dict, blank=True)
    plan_history = models.JSONField(default=list, blank=True)
    structured_results = models.JSONField(default=dict, blank=True)
    verification_summary = models.JSONField(default=dict, blank=True)
    verification_status = models.CharField(max_length=32, blank=True, default="", db_index=True)
    outcome = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    failure_modes = models.JSONField(default=list, blank=True)
    failure_modes_search = models.TextField(blank=True, default="")
    replans = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["domain", "verification_status"]),
            models.Index(fields=["goal_signature", "tool_sequence_signature"]),
        ]

    def __str__(self):
        return f"RunMemory(run={self.run_id}, domain={self.domain}, verification={self.verification_status})"


class Episode(models.Model):
    """
    Episodio reutilizable extraído de un run.
    """

    run = models.OneToOneField(Run, on_delete=models.CASCADE, related_name="episode")
    normalized_goal = models.TextField(blank=True, default="")
    goal_signature = models.CharField(max_length=255, blank=True, default="", db_index=True)
    domain = models.CharField(max_length=64, blank=True, default="", db_index=True)
    analysis_types = models.JSONField(default=list, blank=True)
    tools_used = models.JSONField(default=list, blank=True)
    tool_sequence = models.JSONField(default=list, blank=True)
    tool_sequence_signature = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )
    outcome_status = models.CharField(max_length=32, blank=True, default="", db_index=True)
    verification_status = models.CharField(max_length=32, blank=True, default="", db_index=True)
    success = models.BooleanField(default=False)
    failure_mode = models.CharField(max_length=255, blank=True, default="")
    failure_modes = models.JSONField(default=list, blank=True)
    recommended_strategy = models.TextField(blank=True, default="")
    verification_summary = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    replan_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["goal_signature", "domain"]),
            models.Index(fields=["tool_sequence_signature", "success"]),
        ]

    def __str__(self):
        return f"Episode(run={self.run_id}, goal_signature={self.goal_signature}, success={self.success})"


class EpisodePattern(models.Model):
    """
    Agregado de episodios similares para sugerir estrategias recurrentes.
    """

    goal_signature = models.CharField(max_length=255, blank=True, default="", db_index=True)
    domain = models.CharField(max_length=64, blank=True, default="", db_index=True)
    tool_sequence_signature = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )
    tool_sequence = models.JSONField(default=list, blank=True)
    sample_size = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    success_rate = models.FloatField(default=0.0)
    last_outcome_status = models.CharField(max_length=32, blank=True, default="")
    last_failure_mode = models.CharField(max_length=255, blank=True, default="")
    recommended_strategy = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("goal_signature", "domain", "tool_sequence_signature")]
        indexes = [
            models.Index(fields=["domain", "success_rate"]),
            models.Index(fields=["goal_signature", "success_rate"]),
        ]

    def __str__(self):
        return (
            "EpisodePattern("
            f"goal_signature={self.goal_signature}, domain={self.domain}, "
            f"success_rate={self.success_rate:.2f})"
        )


class RunFeedback(models.Model):
    """
    Valoración del usuario sobre el resultado de un run.
    rating=1 → útil, rating=-1 → no útil.
    Actualiza Episode.success y recalcula EpisodePattern.success_rate.
    """
    RATING_CHOICES = [
        (1, "Útil"),
        (-1, "No útil"),
    ]

    run = models.OneToOneField(Run, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    rating = models.SmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["run", "rating"]),
        ]

    def __str__(self):
        return f"RunFeedback(run={self.run_id}, rating={self.rating})"
