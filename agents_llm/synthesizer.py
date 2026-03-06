from typing import Any, Dict, List
import json

from .client import chat_completion_text


SYNTHESIZER_SYSTEM_PROMPT = """
Eres un analista de resultados de un framework de agentes GIS.

Tu trabajo es redactar una respuesta final clara, útil y estrictamente basada en las evidencias disponibles.

Reglas:
- No inventes datos.
- No hagas inferencias geométricas no demostradas explícitamente por las tools.
- Si una tool no se ejecutó, no afirmes conclusiones que dependan de ella.
- Si una tool devuelve count_total > 0, puedes afirmar que existen resultados/intersecciones/elementos encontrados.
- Si una tool devuelve count_total = 0, puedes afirmar que no se encontraron resultados en esa consulta.
- No digas que una geometría está "en la frontera", "dentro parcialmente", "contenida completamente" o similares salvo que eso haya sido demostrado explícitamente por los datos.
- Si el análisis es espacial, usa lenguaje geoespacial claro y prudente.
- Si intersection_geom_type = POINT, puedes afirmar que existe una intersección puntual, pero no debes interpretar eso como "misma ubicación", "frontera", "contenido completo" o equivalentes.
- Distingue entre "intersecta con" y "está dentro de". Solo usa "está dentro de" si el objetivo y los resultados lo justifican claramente.
- Cuando la evidencia procede de spatial.intersects, la formulación preferida es "se detectó intersección entre X e Y".
- Prioriza exactitud frente a estilo.
- La respuesta debe estar en español.
- No afirmes que no existen intersecciones salvo que se haya ejecutado explícitamente spatial.intersects y count_total sea 0.
- No afirmes que un elemento no está dentro de una zona salvo que exista evidencia explícita de una tool adecuada para esa comprobación.
- Si solo se ejecutó spatial.context_pack, limítate a describir contexto espacial general y no saques conclusiones topológicas específicas.

Reglas por perfil:
- Si agent_profile = "compact", responde de forma breve, directa y con poca ornamentación.
- Si agent_profile = "rich", ofrece algo más de detalle y contexto.
- Si agent_profile = "investigate", redacta una conclusión más analítica, comparativa y exhaustiva, pero siempre basada en evidencias.

Estructura preferida:
1. Resumen ejecutivo
2. Hallazgos principales
3. Conclusión
"""


def _facts_from_spatial_summary(data: Dict[str, Any]) -> List[str]:
    facts = []
    layers = data.get("layers", []) or []

    facts.append(
        f"spatial.summary consultó {len(layers)} capas en el bbox analizado."
    )

    for layer in layers:
        name = layer.get("name", "")
        count = layer.get("count", 0)
        facts.append(f"La capa '{name}' contiene {count} elementos dentro del bbox.")

        geom_types = layer.get("geom_types", []) or []
        for gt in geom_types:
            geom_type = gt.get("geom_type")
            n = gt.get("n")
            if geom_type is not None and n is not None:
                facts.append(f"En '{name}' hay {n} geometrías de tipo {geom_type}.")

    return facts


def _facts_from_context_pack(data: Dict[str, Any]) -> List[str]:
    facts = []
    executive = data.get("executive_summary", {}) or {}
    highlights = data.get("highlights", []) or []

    if executive:
        facts.append(
            f"spatial.context_pack detectó {executive.get('total_features_detected', 0)} elementos en total."
        )
        facts.append(
            f"Se consultaron {executive.get('total_layers_consulted', 0)} capas y {executive.get('non_empty_layers', 0)} tenían elementos."
        )

    for h in highlights[:5]:
        facts.append(f"Highlight: {h}")

    return facts


def _facts_from_intersects(data: Dict[str, Any]) -> List[str]:
    facts = []
    count_total = data.get("count_total", 0)
    source_layer = data.get("source_layer", "")
    target_layer = data.get("target_layer", "")

    facts.append(
        f"spatial.intersects encontró {count_total} intersecciones entre '{source_layer}' y '{target_layer}'."
    )

    items = data.get("items", []) or []
    for item in items[:10]:
        source_name = item.get("source_name") or item.get("source_id")
        target_name = item.get("target_name") or item.get("target_id")
        geom_type = item.get("intersection_geom_type")
        facts.append(
            f"Se detectó una intersección entre '{source_name}' y '{target_name}' con geometría de intersección tipo {geom_type}."
        )

    return facts


def _facts_from_nearby(data: Dict[str, Any]) -> List[str]:
    facts = []
    count_total = data.get("count_total", 0)
    layer = data.get("layer", "")
    point = data.get("point", {}) or {}

    facts.append(
        f"spatial.nearby encontró {count_total} elementos de la capa '{layer}' cerca del punto ({point.get('lon')}, {point.get('lat')})."
    )

    items = data.get("items", []) or []
    for item in items[:10]:
        name = item.get("name") or item.get("id")
        distance_m = item.get("distance_m")
        facts.append(f"Elemento '{name}' localizado a {distance_m} metros.")

    return facts


def _facts_from_query_layer(data: Dict[str, Any]) -> List[str]:
    facts = []
    count_total = data.get("count_total", 0)
    layer = data.get("layer", "")

    facts.append(
        f"spatial.query_layer devolvió {count_total} elementos de la capa '{layer}'."
    )

    return facts


def build_tool_facts(step_outputs: List[Dict[str, Any]]) -> List[str]:
    facts: List[str] = []

    for step in step_outputs:
        if step.get("type") != "tool":
            continue

        tool_name = step.get("name", "")
        ok = step.get("ok", False)
        data = step.get("data", {}) or {}
        error = step.get("error", "")

        if not ok:
            facts.append(f"La tool '{tool_name}' falló con error: {error}")
            continue

        if tool_name == "spatial.summary":
            facts.extend(_facts_from_spatial_summary(data))
        elif tool_name == "spatial.context_pack":
            facts.extend(_facts_from_context_pack(data))
        elif tool_name == "spatial.intersects":
            facts.extend(_facts_from_intersects(data))
        elif tool_name == "spatial.nearby":
            facts.extend(_facts_from_nearby(data))
        elif tool_name == "spatial.query_layer":
            facts.extend(_facts_from_query_layer(data))
        else:
            facts.append(f"La tool '{tool_name}' se ejecutó correctamente.")

    return facts


def build_synthesizer_user_prompt(
    *,
    goal: str,
    agent_name: str,
    agent_profile: str,
    plan: Dict[str, Any],
    step_outputs: List[Dict[str, Any]],
) -> str:
    executed_tool_names = [
        step.get("name")
        for step in step_outputs
        if step.get("type") == "tool"
    ]

    tool_facts = build_tool_facts(step_outputs)

    payload = {
        "goal": goal,
        "agent_name": agent_name,
        "agent_profile": agent_profile,
        "executed_tool_names": executed_tool_names,
        "plan_steps": plan.get("steps", []),
        "tool_facts": tool_facts,
        "step_outputs": step_outputs,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def synthesize_run(
    *,
    goal: str,
    agent_name: str,
    agent_profile: str,
    plan: Dict[str, Any],
    step_outputs: List[Dict[str, Any]],
) -> str:
    user_prompt = build_synthesizer_user_prompt(
        goal=goal,
        agent_name=agent_name,
        agent_profile=agent_profile,
        plan=plan,
        step_outputs=step_outputs,
    )
    return chat_completion_text(
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
    )