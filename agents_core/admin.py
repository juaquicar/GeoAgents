from django.contrib import admin

from .models import Agent, Episode, EpisodePattern, Run, RunMemory, RunStep


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


@admin.register(RunMemory)
class RunMemoryAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "domain", "verification_status", "updated_at")
    list_filter = ("domain", "verification_status")
    search_fields = (
        "normalized_goal",
        "goal_signature",
        "tools_search",
        "layers_search",
        "analysis_types_search",
        "failure_modes_search",
    )


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "domain", "success", "verification_status", "updated_at")
    list_filter = ("domain", "success", "verification_status")
    search_fields = ("normalized_goal", "goal_signature", "recommended_strategy")


@admin.register(EpisodePattern)
class EpisodePatternAdmin(admin.ModelAdmin):
    list_display = ("id", "goal_signature", "domain", "sample_size", "success_rate")
    list_filter = ("domain",)
    search_fields = ("goal_signature", "recommended_strategy", "tool_sequence_signature")
