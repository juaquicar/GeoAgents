from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agent, Run, RunFeedback, RunStep
from .serializers import (
    AgentSerializer,
    RunSerializer,
    RunStepSerializer,
    RunTraceSerializer,
)
from .runner import execute_run


def _apply_feedback_to_episode(run, rating: int) -> None:
    """
    Actualiza Episode.success con la valoración del usuario y recalcula
    EpisodePattern.success_rate para que los pattern_hints mejoren con el tiempo.
    """
    from .models import Episode, EpisodePattern
    try:
        episode = run.episode
    except Exception:
        return

    user_success = rating == 1
    episode.success = user_success
    episode.save(update_fields=["success", "updated_at"])

    matching = Episode.objects.filter(
        goal_signature=episode.goal_signature,
        domain=episode.domain,
        tool_sequence_signature=episode.tool_sequence_signature,
    )
    sample_size = matching.count()
    success_count = matching.filter(success=True).count()

    EpisodePattern.objects.filter(
        goal_signature=episode.goal_signature,
        domain=episode.domain,
        tool_sequence_signature=episode.tool_sequence_signature,
    ).update(
        sample_size=sample_size,
        success_count=success_count,
        failure_count=sample_size - success_count,
        success_rate=success_count / sample_size if sample_size else 0.0,
    )


def _run_inspect(agent):
    """
    Ejecuta la introspección GIS del agente y persiste el catálogo.
    No lanza excepciones — los errores se devuelven como string en gis_layers_catalog.
    """
    from agents_gis.inspect import inspect_agent_gis
    from django.utils import timezone
    try:
        catalog = inspect_agent_gis(agent)
        agent.gis_layers_catalog = catalog
        agent.gis_catalog_updated_at = timezone.now()
        agent.save(update_fields=["gis_layers_catalog", "gis_catalog_updated_at"])
        return None  # sin error
    except Exception as exc:
        return str(exc)


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all().order_by("-id")
    serializer_class = AgentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        agent = serializer.save()
        if agent.gis_db_connections:
            _run_inspect(agent)

    def perform_update(self, serializer):
        # Re-inspeccionar solo si el payload incluye gis_db_connections
        agent = serializer.save()
        if "gis_db_connections" in self.request.data and agent.gis_db_connections:
            _run_inspect(agent)

    @action(detail=True, methods=["post"])
    def inspect(self, request, pk=None):
        """POST /api/agents/{id}/inspect/ — Dispara la introspección GIS manualmente."""
        agent = self.get_object()
        if not agent.gis_db_connections:
            return Response(
                {"error": "El agente no tiene conexiones GIS configuradas."},
                status=400,
            )
        error = _run_inspect(agent)
        agent.refresh_from_db()
        data = AgentSerializer(agent).data
        if error:
            data["inspect_error"] = error
        return Response(data)


class RunViewSet(viewsets.ModelViewSet):
    queryset = Run.objects.select_related("agent", "memory", "episode").all().order_by("-id")
    serializer_class = RunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            Run.objects.select_related("agent", "memory", "episode")
            .filter(user=self.request.user)
            .order_by("-id")
        )

        params = self.request.query_params
        tool = (params.get("tool") or "").strip().lower()
        layer = (params.get("layer") or "").strip().lower()
        analysis_type = (params.get("analysis_type") or "").strip().lower()
        verification_status = (params.get("verification_status") or "").strip().lower()
        domain = (params.get("domain") or "").strip().lower()
        goal_signature = (params.get("goal_signature") or "").strip().lower()

        if tool:
            qs = qs.filter(memory__tools_search__icontains=tool)
        if layer:
            qs = qs.filter(memory__layers_search__icontains=layer)
        if analysis_type:
            qs = qs.filter(memory__analysis_types_search__icontains=analysis_type)
        if verification_status:
            qs = qs.filter(memory__verification_status=verification_status)
        if domain:
            qs = qs.filter(memory__domain=domain)
        if goal_signature:
            qs = qs.filter(memory__goal_signature__icontains=goal_signature)

        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        run = self.get_object()
        run = execute_run(run)
        return Response(RunSerializer(run).data)

    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        run = self.get_object()
        qs = RunStep.objects.filter(run=run).order_by("idx")
        return Response(RunStepSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"])
    def trace(self, request, pk=None):
        run = self.get_object()
        return Response(RunTraceSerializer(run).data)

    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        """
        POST /api/runs/{id}/feedback/
        Body: {"rating": 1 | -1, "comment": "..."}

        Guarda la valoración del usuario y actualiza Episode.success
        y EpisodePattern.success_rate con la señal real del usuario.
        """
        run = self.get_object()

        rating = request.data.get("rating")
        if rating not in (1, -1):
            return Response({"error": "rating must be 1 or -1"}, status=400)

        comment = (request.data.get("comment") or "").strip()

        feedback, _ = RunFeedback.objects.update_or_create(
            run=run,
            defaults={"user": request.user, "rating": rating, "comment": comment},
        )

        _apply_feedback_to_episode(run, rating)

        return Response({
            "run": run.pk,
            "rating": rating,
            "comment": comment,
        }, status=200)
