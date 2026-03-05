from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Agent, Run, RunStep
from .serializers import AgentSerializer, RunSerializer, RunStepSerializer

from .runner import execute_run

class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all().order_by("-id")
    serializer_class = AgentSerializer
    permission_classes = [permissions.IsAuthenticated]


class RunViewSet(viewsets.ModelViewSet):
    queryset = Run.objects.select_related("agent").all().order_by("-id")
    serializer_class = RunSerializer
    permission_classes = [permissions.IsAuthenticated]

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