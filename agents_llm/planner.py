import json
from typing import Any, Dict, List, Optional

from agents_tools.introspection import export_tools_catalog
from agents_gis.introspection import export_gis_layers_catalog
from agents_core.heuristics import build_planner_heuristics

from .client import chat_completion_json
from .examples import PLANNER_EXAMPLES
from examples.canonical_plans import CANONICAL_PLANNER_EXAMPLES
from .plan_postprocessor import normalize_plan
from .plan_validation import validate_plan, validate_plan_gis_references

PLANNER_SYSTEM_PROMPT = """
Eres un planificador de un framework de agentes GIS de propósito general.

Tu trabajo es devolver SIEMPRE un JSON válido con una clave "steps".

Contexto temático del agente:
- El campo agent_system_prompt define el dominio temático del agente: infraestructura, catastro, vegetación, activos, redes viarias, etc.
- Usa agent_system_prompt para entender a qué entidades reales se refiere el objetivo y adaptar tu interpretación del vocabulario del usuario.
- Los nombres de capas deben salir EXCLUSIVAMENTE de gis_layers_catalog, nunca de conocimiento previo.
  Ejemplo: si agent_system_prompt dice "capas disponibles: parcelas, edificios, viales" y el objetivo
  menciona "parcelas", busca en gis_layers_catalog la capa cuyo nombre coincida semánticamente.
- Si el objetivo usa terminología específica del dominio (p.ej. "tramo" en infraestructura, "parcela"
  en catastro, "rodal" en vegetación), interpreta esa terminología usando agent_system_prompt y
  mapea al nombre de capa correcto en gis_layers_catalog.
- Si agent_system_prompt no informa sobre el dominio, razona solo con gis_layers_catalog.

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

Guía de selección de herramienta — sigue este orden de prioridad:
1. Si el objetivo menciona ruta, camino, trazado, conexión entre dos puntos, o recorrido por un grafo topológico → usa spatial.network_trace o spatial.route_cost.
2. Si el objetivo menciona área alcanzable, cobertura de servicio, zona de influencia desde un origen en una red → usa spatial.network_service_area.
3. Si el objetivo menciona elementos cercanos a un punto → usa spatial.nearby.
   Si el objetivo menciona "a X metros de este elemento" donde ese elemento es una geometría de capa (línea, polígono…) → usa spatial.buffer con source_layer+source_id.
4. Si el objetivo menciona intersección, solape, relación espacial entre dos capas, o elementos contenidos en otra capa → usa spatial.intersects.
5. Si el objetivo menciona cuántos hay por tipo/categoría, distribución, agrupaciones, predominancia, o suma/promedio de un campo → usa spatial.aggregate.
6. Si el objetivo menciona inventario, listado, campos específicos de una capa, o nombra explícitamente una capa del catálogo → usa spatial.query_layer o spatial.summary.
7. SOLO si el objetivo es verdaderamente genérico ("qué hay en esta zona", "resume el entorno", "dame contexto general") y NO menciona ninguna capa, operación, ni término del dominio → usa spatial.context_pack.

Para spatial.aggregate:
- Úsalo cuando el objetivo pide recuentos por tipo, categoría, distribución estadística o suma de un campo.
- group_by acepta hasta 4 campos de filter_fields de la capa.
- aggs es opcional; sin él devuelve solo COUNT(*) por grupo.
- success_criteria recomendada: {"path": "data.groups", "non_empty": true}

NUNCA uses spatial.context_pack cuando:
- El objetivo menciona una capa por nombre (cualquiera que aparezca en gis_layers_catalog o en agent_system_prompt).
- El objetivo menciona una operación específica (inventario, ruta, cobertura, conteo, tipos, buffer…).
- El objetivo menciona un análisis de red o grafo aunque no dé puntos de origen/destino.
- heuristics.initial_tools contiene una herramienta distinta a context_pack.

Reglas GIS:
- Si usas una tool que requiere una capa (layer, source_layer, target_layer), debes elegir nombres EXCLUSIVAMENTE de gis_layers_catalog.
- No inventes nombres de capas.
- Si necesitas filtros, usa solo campos presentes en filter_fields de la capa correspondiente.
- Usa agent_system_prompt para interpretar terminología del dominio y mapearla al nombre de capa correcto en gis_layers_catalog.
- Si el objetivo menciona proximidad a un punto, suele ser adecuado usar spatial.nearby.
- Si el objetivo menciona elementos dentro del área de influencia de una geometría de capa (línea, polígono, elemento de cualquier tipo), usa spatial.buffer con source_layer+source_id.
- Para spatial.buffer: source_point y (source_layer+source_id) son mutuamente excluyentes. Si la fuente es un punto usa source_point; si es un elemento de capa usa source_layer+source_id.
- Si el objetivo menciona intersección, solape, cruce o elementos contenidos entre capas, suele ser adecuado usar spatial.intersects.
- Si el objetivo es explorar una capa concreta dentro de un bbox, suele ser adecuado usar spatial.query_layer.
- Si el objetivo habla de una red o grafo topológico sin dar puntos concretos, usa spatial.summary para obtener recuento por capas y spatial.query_layer para listar elementos; reserva network_trace/route_cost para cuando haya origen y destino explícitos.

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

Si session_context está presente:
- session_context contiene los turnos anteriores de la misma conversación: goal, final_text y tools_used de cada run previo.
- Úsalo para entender el hilo conversacional y evitar repetir análisis ya realizados.
- Si el usuario hace una pregunta de seguimiento ("¿y los de tipo X?", "ahora filtra por…", "usa el mismo bbox"), infiere el contexto del turno anterior.
- No menciones explícitamente que tienes un historial; simplemente planifica teniendo en cuenta lo que ya se sabe.
- Si el turno anterior usó un bbox concreto y el nuevo goal no especifica uno diferente, reutiliza ese bbox.
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


def _build_session_context(run) -> Optional[List[Dict[str, Any]]]:
    """
    Recupera los últimos runs de la misma sesión (excluyendo el actual)
    y devuelve un resumen condensado para el planner.
    """
    session_id = getattr(run, "session_id", "") or ""
    if not session_id:
        return None

    try:
        from agents_core.models import Run as RunModel
        previous = (
            RunModel.objects.filter(
                agent=run.agent,
                session_id=session_id,
                status="succeeded",
            )
            .exclude(pk=run.pk)
            .order_by("-created_at")[:5]
        )
        history = []
        for prev in reversed(list(previous)):
            entry: Dict[str, Any] = {
                "run_id": prev.pk,
                "goal": (prev.input_json or {}).get("goal", ""),
                "final_text": (prev.final_text or "")[:500],
            }
            out = prev.output_json or {}
            tools_used = [
                s.get("name") for s in out.get("executed_outputs", [])
                if s.get("type") == "tool" and s.get("ok")
            ]
            if tools_used:
                entry["tools_used"] = tools_used
            history.append(entry)
        return history if history else None
    except Exception:
        return None


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

    session_context = _build_session_context(run)
    if session_context:
        extra["session_context"] = session_context

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