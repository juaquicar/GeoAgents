from __future__ import annotations
from typing import Any, Dict, Tuple

from agents_core.steps import log_step, timed
from agents_core.models import Run

from .registry import REGISTRY
from .base import ToolResult


def invoke_tool(
    *,
    run: Run,
    tool_name: str,
    args: Dict[str, Any],
    user=None,
) -> Tuple[ToolResult, int]:
    """
    Ejecuta una tool:
    - valida args
    - mide latencia
    - registra RunStep(kind='tool')
    """
    tool = REGISTRY.get(tool_name)

    err = tool.validate(args)
    if err:
        log_step(
            run,
            kind="tool",
            name=tool_name,
            input_json={"args": args},
            output_json={},
            latency_ms=0,
            error=err,
        )
        return ToolResult(ok=False, error=err), 0

    def _call():
        return tool.invoke(args=args, run=run, user=user)

    result, latency_ms = timed(_call)

    log_step(
        run,
        kind="tool",
        name=tool_name,
        input_json={"args": args},
        output_json={"ok": result.ok, "data": result.data, "error": result.error},
        latency_ms=latency_ms,
        error=result.error if not result.ok else "",
    )

    return result, latency_ms