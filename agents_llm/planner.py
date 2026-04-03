import json
from typing import Any, Dict, Optional

from agents_tools.introspection import export_tools_catalog
from agents_gis.introspection import export_gis_layers_catalog
from agents_core.heuristics import build_planner_heuristics

from .client import chat_completion_json
from .examples import PLANNER_EXAMPLES
from examples.canonical_plans import CANONICAL_PLANNER_EXAMPLES
from .plan_postprocessor import normalize_plan
from .plan_validation import validate_plan, validate_plan_gis_references

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

Capacidades adicionales obligatorias para pasos tool:
- Puedes incluir "verification_target": qué pretende comprobar exactamente el paso.
- Puedes incluir "success_criteria": un objeto simple para verificar la evidencia devuelta.
- success_criteria debe usar una forma simple como:
  {"path": "data.layers", "non_empty": true}
  {"path": "data.path_found", "equals": true}
  {"path": "data.features", "non_empty": true}
  {"path": "data.features", "non_empty": true}
- Puedes incluir "timeout_s", "max_retries", "retry_backoff_s" y "can_replan".
- Usa can_replan=true solo si el paso puede justificar un replanteamiento del plan tras un fallo o evidencia insuficiente.

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

Reglas específicas por tool:
- Para spatial.network_trace, si verificas éxito de ruta, usa:
  {"path": "data.path_found", "equals": true}
- Para spatial.route_cost, si verificas que se ha calculado una ruta con coste, usa:
  {"path": "data.total_cost", "gt": 0}
- Para spatial.route_cost, si verificas existencia de ruta, también puedes usar:
  {"path": "data.path_found", "equals": true}
- No uses "data.cost" para spatial.route_cost, porque esa tool devuelve "data.total_cost".
- Para spatial.summary, evita usar data.count_total; usa preferentemente:
  {"path": "data.layers", "non_empty": true}
- Para spatial.query_layer: los resultados están en "data.items" (NO en "data.features").
  Cada item incluye siempre "lon" y "lat" con las coordenadas del centroide del elemento.
  Para referenciar coordenadas de un item en un step posterior usa:
    "$step:s1.data.items.0.lon"  y  "$step:s1.data.items.0.lat"
  Para verificar que se encontraron resultados usa:
    {"path": "data.items", "non_empty": true}
  No uses campos de la tabla (como gps_lon, x, y) para obtener coordenadas; usa siempre lon/lat del item.
  bbox es OPCIONAL en spatial.query_layer: omítelo cuando busques elementos por id o atributo
  sin restricción espacial (por ejemplo, localizar un elemento concreto por su fid).
  Solo incluye bbox cuando quieras limitar la búsqueda a una zona geográfica concreta.
  Los valores de filters deben ser SIEMPRE escalares (string, number, boolean) o listas de escalares.
  NUNCA uses objetos {"gt": ...}, {"gte": ...} etc. como valores de filtro — no están soportados.
  Si quieres filtrar por rango, usa solo un valor escalar exacto o una lista de valores exactos.

Uso de ejemplos:
- Usa planning_examples como referencia de estilo y estructura.
- No copies literalmente los ejemplos si no aplican, pero mantén el mismo formato de salida.
- Prioriza planes cortos, claros y no redundantes.

Si execution_context está presente:
- Ten en cuenta steps ya ejecutados, sus resultados y verificaciones.
- Evita repetir pasos ya ejecutados correctamente salvo que sea imprescindible.
- Si hubo un fallo o una hipótesis refutada, puedes proponer una estrategia alternativa con nuevas tools o nuevos args.
- Mantén el plan reparado lo más corto posible.
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


def build_planner_user_prompt(
    run,
    payload: Dict[str, Any],
    execution_context: Optional[Dict[str, Any]] = None,
) -> str:
    goal = payload.get("goal", "")
    map_context = payload.get("map_context", {})
    allowlist = getattr(run.agent, "tool_allowlist", []) or []
    agent_profile = getattr(run.agent, "profile", "compact")

    tools_catalog = export_tools_catalog(allowlist)
    gis_layers_catalog = export_gis_layers_catalog(compact_for_planner=True)
    filtered_examples = filter_planner_examples_by_allowlist(
        PLANNER_EXAMPLES + CANONICAL_PLANNER_EXAMPLES,
        allowlist,
    )
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
        "heuristics": build_planner_heuristics(run, payload),
    }
    if execution_context:
        extra["execution_context"] = execution_context

    return json.dumps(extra, ensure_ascii=False, indent=2)


def _normalize_success_criteria(criteria: Any) -> Dict[str, Any]:
    if criteria is None:
        return {}

    if not isinstance(criteria, dict):
        raise ValueError("Planner success_criteria must be an object")

    normalized = dict(criteria)

    path = normalized.get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("Planner success_criteria.path must be a string")

    supported_ops = {
        "equals",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "non_empty",
        "in",
    }
    present_ops = [op for op in supported_ops if op in normalized]
    if normalized and not path:
        raise ValueError("Planner success_criteria requires path when operators are present")
    if len(present_ops) > 1:
        raise ValueError("Planner success_criteria supports only one operator per step")

    return normalized



def plan_run(
    run,
    payload: Dict[str, Any],
    execution_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user_prompt = build_planner_user_prompt(
        run,
        payload,
        execution_context=execution_context,
    )

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
        execution_context=execution_context,
    )

    normalized_result = validate_plan(normalized_result)

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
            "execution_context": execution_context or {},
        },
    }