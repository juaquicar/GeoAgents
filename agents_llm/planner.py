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
- Si usas spatial.summary, spatial.context_pack, spatial.query_layer o spatial.intersects, y existe map_context.bbox, debes incluir bbox en args.
- No generes pasos redundantes. Si usas spatial.context_pack para un resumen general, normalmente no hace falta añadir spatial.summary después salvo que haya una razón clara.
- Si el objetivo es un resumen espacial general de una zona, prioriza un único step con spatial.context_pack.
- En los steps de type="tool", puedes incluir "required": true o false.
- Si no estás seguro de que un step sea imprescindible, usa "required": false.
- Para análisis espaciales generales, el step principal suele ser required=true.
- El step final debe ser {"type": "final"}.
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



def validate_plan(plan: dict) -> dict:
    steps = plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise ValueError("Planner returned invalid or empty steps")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Planner step {i} is not an object")

        step_type = step.get("type")
        if step_type not in {"tool", "final"}:
            raise ValueError(f"Planner step {i} has invalid type: {step_type}")

        if step_type == "tool":
            if not step.get("name"):
                raise ValueError(f"Planner tool step {i} missing name")
            if "args" not in step:
                step["args"] = {}
            if "required" not in step:
                step["required"] = True

        if step_type == "final":
            step.pop("required", None)

    if steps[-1].get("type") != "final":
        raise ValueError("Planner must end with a final step")

    return plan


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

    result = validate_plan(result)
    return result

