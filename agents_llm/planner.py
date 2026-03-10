import json
from typing import Any, Dict

from agents_tools.introspection import export_tools_catalog
from agents_gis.introspection import export_gis_layers_catalog

from .client import chat_completion_json
from .examples import PLANNER_EXAMPLES
from .plan_postprocessor import normalize_plan

PLANNER_SYSTEM_PROMPT = """
Eres un planificador de un framework de agentes.

Tu trabajo es devolver SIEMPRE un JSON válido con una clave "steps".

- Debes tener en cuenta agent_profile.
- Si agent_profile = "compact", prioriza planes muy cortos, normalmente con una sola tool.
- Si agent_profile = "rich", puedes usar planes algo más detallados, pero evita redundancia.
- Si agent_profile = "investigate", puedes proponer varios pasos si aportan valor real y no son redundantes.

Reglas generales:
- Devuelve solo JSON.
- Cada step debe tener "type".
- Si type == "tool", debe tener "name" y "args".
- Los nombres de tools deben salir EXCLUSIVAMENTE de tools_catalog.
- No inventes tools.
- El último step debe ser {"type": "final"}.
- En los steps de type="tool", puedes incluir "required": true o false.
- Si no estás seguro de que un step sea imprescindible, usa "required": false.
- Cada step de type="tool" debe incluir un "id" único y corto (ej: "s1", "s2").
- Puedes incluir "hypothesis" en cada tool step: una hipótesis verificable en lenguaje natural.
- Puedes incluir "depends_on" (lista de ids de steps previos) para declarar dependencias explícitas.
- Puedes incluir "on_fail" con valores "abort" o "continue" para controlar ejecución.
- Si una herramienta necesita datos de un step anterior, referencia args con el patrón
  "$step:<step_id>.<campo>", por ejemplo "$step:s1.data.features".

Reglas de contexto:
- Si una tool requiere bbox y existe map_context.bbox, debes incluirlo en args.
- Si una tool acepta zoom y existe map_context.zoom, debes incluirlo en args cuando sea útil.
- No generes pasos redundantes.
- Si el objetivo es un resumen espacial general de una zona, prioriza un único step con spatial.context_pack.

Reglas GIS:
- Si usas una tool que requiere una capa (layer, source_layer, target_layer), debes elegir nombres EXCLUSIVAMENTE de gis_layers_catalog.
- No inventes nombres de capas.
- Si necesitas filtros, usa solo campos presentes en filter_fields de la capa correspondiente.
- Si el objetivo menciona proximidad, suele ser adecuado usar spatial.nearby.
- Si el objetivo menciona intersección, solape, cruce o elementos contenidos entre capas, suele ser adecuado usar spatial.intersects.
- Si el objetivo es explorar una capa concreta dentro de un bbox, suele ser adecuado usar spatial.query_layer.

Uso de ejemplos:
- Usa planning_examples como referencia de estilo y estructura.
- No copies literalmente los ejemplos si no aplican, pero mantén el mismo formato de salida.
- Prioriza planes cortos, claros y no redundantes.
"""

def filter_planner_examples_by_allowlist(examples, allowlist):
    allowed = set(allowlist or [])
    if not allowed:
        return examples

    out = []
    for ex in examples:
        steps = ex.get("output", {}).get("steps", [])
        ok = True
        for step in steps:
            if step.get("type") == "tool" and step.get("name") not in allowed:
                ok = False
                break
        if ok:
            out.append(ex)
    return out

def build_planner_user_prompt(run, payload: Dict[str, Any]) -> str:
    goal = payload.get("goal", "")
    map_context = payload.get("map_context", {})
    allowlist = getattr(run.agent, "tool_allowlist", []) or []
    agent_profile = getattr(run.agent, "profile", "compact")

    tools_catalog = export_tools_catalog(allowlist)
    gis_layers_catalog = export_gis_layers_catalog()
    filtered_examples = filter_planner_examples_by_allowlist(PLANNER_EXAMPLES, allowlist)

    extra = {
        "goal": goal,
        "map_context": map_context,
        "agent_name": run.agent.name,
        "agent_system_prompt": run.agent.system_prompt,
        "agent_profile": agent_profile,
        "tool_allowlist": allowlist,
        "tools_catalog": tools_catalog,
        "gis_layers_catalog": gis_layers_catalog,
        "planning_examples": filtered_examples,
    }
    return json.dumps(extra, ensure_ascii=False, indent=2)

def validate_plan_gis_references(plan: dict, gis_layers_catalog: list) -> dict:
    valid_layer_names = {layer.get("name") for layer in gis_layers_catalog}

    for i, step in enumerate(plan.get("steps", [])):
        if step.get("type") != "tool":
            continue

        name = step.get("name")
        args = step.get("args") or {}

        # tools con un layer
        if name in {"spatial.query_layer", "spatial.nearby"}:
            layer = args.get("layer")
            if layer and layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown GIS layer at step {i}: {layer}")

        # tools con dos layers
        if name == "spatial.intersects":
            source_layer = args.get("source_layer")
            target_layer = args.get("target_layer")

            if source_layer and source_layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown source_layer at step {i}: {source_layer}")
            if target_layer and target_layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown target_layer at step {i}: {target_layer}")

        # context_pack puede llevar nearby / intersections internas
        if name == "spatial.context_pack":
            nearby = args.get("nearby") or []
            intersections = args.get("intersections") or []

            for j, item in enumerate(nearby):
                layer = item.get("layer")
                if layer and layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown nearby.layer at step {i}, item {j}: {layer}"
                    )

            for j, item in enumerate(intersections):
                source_layer = item.get("source_layer")
                target_layer = item.get("target_layer")

                if source_layer and source_layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown intersections.source_layer at step {i}, item {j}: {source_layer}"
                    )
                if target_layer and target_layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown intersections.target_layer at step {i}, item {j}: {target_layer}"
                    )

    return plan


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
            if not step.get("id"):
                step["id"] = f"s{i+1}"
            if not step.get("name"):
                raise ValueError(f"Planner tool step {i} missing name")
            if "args" not in step:
                step["args"] = {}
            if "required" not in step:
                step["required"] = True
            if "depends_on" not in step:
                step["depends_on"] = []
            if not isinstance(step.get("depends_on"), list):
                raise ValueError(f"Planner tool step {i} has invalid depends_on")
            if "on_fail" not in step:
                step["on_fail"] = "abort" if step["required"] else "continue"
            if step.get("on_fail") not in {"abort", "continue"}:
                raise ValueError(f"Planner tool step {i} has invalid on_fail")

        if step_type == "final":
            step.pop("required", None)
            step.pop("depends_on", None)
            step.pop("on_fail", None)

    tool_step_ids = [s.get("id") for s in steps if s.get("type") == "tool"]
    if len(tool_step_ids) != len(set(tool_step_ids)):
        raise ValueError("Planner tool steps must have unique id")

    seen_ids = set()
    for i, step in enumerate(steps):
        if step.get("type") != "tool":
            continue
        step_id = step.get("id")
        for dep in step.get("depends_on", []):
            if dep not in seen_ids:
                raise ValueError(
                    f"Planner step {i} depends on unknown or future step id: {dep}"
                )
        seen_ids.add(step_id)

    if steps[-1].get("type") != "final":
        raise ValueError("Planner must end with a final step")

    return plan

def plan_run(run, payload: Dict[str, Any]) -> Dict[str, Any]:
    user_prompt = build_planner_user_prompt(run, payload)

    raw_result = chat_completion_json(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
    )

    validated_result = validate_plan(raw_result)
    gis_layers_catalog = export_gis_layers_catalog()

    normalized_result = normalize_plan(
        validated_result,
        payload=payload,
        agent_profile=getattr(run.agent, "profile", "compact"),
        gis_layers_catalog=gis_layers_catalog,
    )

    allowed = set(getattr(run.agent, "tool_allowlist", []) or [])
    for i, step in enumerate(normalized_result.get("steps", [])):
        if step.get("type") == "tool":
            name = step.get("name")
            if allowed and name not in allowed:
                raise ValueError(
                    f"Planner proposed a non-allowed tool at step {i}: {name}"
                )

    gis_layers_catalog = export_gis_layers_catalog()
    normalized_result = validate_plan_gis_references(
        normalized_result,
        gis_layers_catalog,
    )

    return {
        "steps": normalized_result.get("steps", []),
        "_meta": {
            "raw_plan": raw_result,
            "validated_plan": validated_result,
            "normalized_plan": normalized_result,
        },
    }
