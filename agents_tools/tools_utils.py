from django.utils import timezone

from .base import BaseTool, ToolResult
from .registry import register_tool


@register_tool
class PingTool(BaseTool):
    name = "utils.ping"
    description = "Devuelve pong con el message dado."
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
        "required": ["message"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        return ToolResult(ok=True, data={"pong": args["message"]})


@register_tool
class NowTool(BaseTool):
    name = "utils.now"
    description = "Devuelve la fecha/hora actual (ISO)."
    input_schema = {"type": "object", "properties": {}, "required": []}

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        return ToolResult(ok=True, data={"now": timezone.now().isoformat()})