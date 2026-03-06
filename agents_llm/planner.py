import json
from typing import Any, Dict

from .client import chat_completion_json


PLANNER_SYSTEM_PROMPT = """
Eres un planificador de un framework de agentes.
Tu trabajo es devolver SIEMPRE un JSON válido con una clave "steps".

Reglas:
- Devuelve solo JSON.
- Cada step debe tener "type".
- Si type == "tool", debe tener "name" y "args".
- El último step debe ser {"type": "final"}.
- Usa herramientas GIS cuando el objetivo implique análisis espacial, proximidad, intersección o contexto de mapa.
- Si existe map_context con bbox, suele ser útil usar spatial.context_pack.
- No inventes tools que no existan.
- Tools disponibles:
  - spatial.summary
  - spatial.query_layer
  - spatial.nearby
  - spatial.intersects
  - spatial.context_pack
  - utils.ping
  - utils.now
"""

def build_planner_user_prompt(run, payload: Dict[str, Any]) -> str:
    goal = payload.get("goal", "")
    map_context = payload.get("map_context", {})
    extra = {
        "goal": goal,
        "map_context": map_context,
        "agent_name": run.agent.name,
        "agent_system_prompt": run.agent.system_prompt,
        "tool_allowlist": getattr(run.agent, "tool_allowlist", []),
    }
    return json.dumps(extra, ensure_ascii=False, indent=2)


def plan_run(run, payload: Dict[str, Any]) -> Dict[str, Any]:
    user_prompt = build_planner_user_prompt(run, payload)
    result = chat_completion_json(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
    )

    if not isinstance(result, dict):
        raise ValueError("Planner did not return a JSON object")

    steps = result.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Planner returned invalid or empty steps")

    return result