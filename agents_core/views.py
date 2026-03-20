from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agent, Run, RunStep
from .serializers import (
    AgentSerializer,
    RunSerializer,
    RunStepSerializer,
    RunTraceSerializer,
)
from .runner import execute_run


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all().order_by("-id")
    serializer_class = AgentSerializer
    permission_classes = [permissions.IsAuthenticated]


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
