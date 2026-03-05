from django.contrib import admin
from .models import Agent, Run, RunStep


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "created_at")
    search_fields = ("name",)


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "status", "created_at", "started_at", "ended_at")
    list_filter = ("status", "agent")


@admin.register(RunStep)
class RunStepAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "idx", "kind", "name", "latency_ms", "created_at")
    list_filter = ("kind", "name")
    search_fields = ("name", "error")