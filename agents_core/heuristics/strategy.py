from typing import Any, Dict, Sequence

from .replan import select_fallback_tools
from .selection import select_initial_tools


def recommend_strategy(
    goal: str,
    tools_used: Sequence[str],
    verification_summary: Dict[str, Any] | None,
    errors: Sequence[str] | None,
    allowlist: Sequence[str] | None = None,
) -> str:
    verification_summary = verification_summary or {}
    counts = verification_summary.get("counts") or {}
    errors = [error for error in (errors or []) if error]

    initial_tools = select_initial_tools(goal, allowlist)
    failed_tool = next((tool for tool in reversed(list(tools_used or [])) if tool), None)
    fallback_tools = select_fallback_tools(goal, failed_tool, allowlist)

    if counts.get("refuted"):
        return (
            "Hipótesis refutada: conviene replanificar con una tool alternativa. "
            f"Inicio sugerido: {', '.join(initial_tools)}. "
            f"Fallback sugerido: {', '.join(fallback_tools)}."
        )

    if counts.get("inconclusive") or errors:
        return (
            "Evidencia inconclusa o error operativo: repetir con verificación explícita y fallback controlado. "
            f"Inicio sugerido: {', '.join(initial_tools)}. "
            f"Fallback sugerido: {', '.join(fallback_tools)}."
        )

    if tools_used:
        return (
            "Secuencia efectiva detectada: "
            f"{' -> '.join(tools_used)}. "
            f"Próximo arranque recomendado: {', '.join(initial_tools)}."
        )

    return f"Arranque recomendado: {', '.join(initial_tools)}."