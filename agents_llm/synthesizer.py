from __future__ import annotations

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

Reglas adicionales obligatorias:
- No afirmes contención, inclusión o que un elemento "está dentro" de otro salvo que exista una herramienta o evidencia explícita de contención.
- Si la evidencia procede de spatial.intersects, habla únicamente de intersección, cruce o relación espacial detectada.
- Si spatial.network_trace devuelve path_found = false, deja claro que no se encontró ruta.
- Si existe un campo reason, úsalo literalmente como motivo técnico cuando sea útil.
- No inventes capas, entidades, distancias, áreas, longitudes o recuentos que no aparezcan en los hechos estructurados.
- Sé prudente: si una relación topológica no está demostrada, indícalo expresamente.

Reglas por perfil:
- Si agent_profile = "compact", responde de forma breve, directa y con poca ornamentación.
- Si agent_profile = "rich", ofrece algo más de detalle y contexto.
- Si agent_profile = "investigate", redacta una conclusión más analítica, comparativa y exhaustiva, pero siempre basada en evidencias.

Estructura preferida:
1. Resumen ejecutivo
2. Hallazgos principales
3. Conclusión
"""


def _safe_get(data: Any, path: List[Any], default=None):
    cur = data
    for key in path:
        try:
            if isinstance(cur, list) and isinstance(key, int):
                cur = cur[key]
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return default
        except Exception:
            return default
        if cur is None:
            return default
    return cur


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

    items = data.get("items", []) or data.get("features", []) or []
    for item in items[:10]:
        name = item.get("name") or item.get("id")
        geom_type = item.get("geometry_type") or item.get("geom_type")
        centroid = item.get("centroid")
        if centroid and isinstance(centroid, dict):
            facts.append(
                f"Elemento '{name}' de tipo {geom_type} con centroide aproximado en ({centroid.get('lon')}, {centroid.get('lat')})."
            )
        else:
            facts.append(f"Elemento '{name}' de tipo {geom_type}.")

    return facts


def _facts_from_network_trace(data: Dict[str, Any]) -> List[str]:
    facts = []

    path_found = bool(
        data.get("path_found")
        or data.get("ok_path")
        or len(data.get("segments", []) or data.get("features", []) or []) > 0
    )
    reason = data.get("reason") or data.get("status_reason")
    node_count = data.get("node_count")
    total_length_m = data.get("total_length_m") or data.get("length_m")
    start_snap_distance_m = data.get("start_snap_distance_m") or data.get("start_snap_m")
    end_snap_distance_m = data.get("end_snap_distance_m") or data.get("end_snap_m")

    if path_found:
        facts.append("spatial.network_trace encontró una ruta válida.")
    else:
        facts.append("spatial.network_trace no encontró una ruta válida.")

    if reason:
        facts.append(f"Motivo técnico reportado por spatial.network_trace: {reason}.")

    if node_count is not None:
        facts.append(f"El recuento de nodos de red fue {node_count}.")

    if total_length_m is not None:
        facts.append(f"La longitud total estimada de la ruta es {total_length_m} metros.")

    if start_snap_distance_m is not None:
        facts.append(f"La distancia de snap inicial fue {start_snap_distance_m} metros.")

    if end_snap_distance_m is not None:
        facts.append(f"La distancia de snap final fue {end_snap_distance_m} metros.")

    segments = data.get("segments", []) or data.get("features", []) or []
    if segments:
        facts.append(f"Se generaron {len(segments)} segmentos de ruta.")

    for seg in segments[:10]:
        name = seg.get("name") or seg.get("segment_name") or seg.get("label")
        if name:
            facts.append(f"Segmento de ruta detectado: '{name}'.")

    return facts


def _extract_intersects_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    features = data.get("features") or data.get("items") or data.get("results") or []
    total = data.get("count_total")
    if total is None:
        total = data.get("count")
    if total is None:
        total = len(features)

    pairs = []
    for feat in features[:10]:
        source_name = feat.get("source_name") or feat.get("source_label") or feat.get("left_name") or feat.get("source_id")
        target_name = feat.get("target_name") or feat.get("target_label") or feat.get("right_name") or feat.get("target_id")
        geom_type = feat.get("intersection_geom_type") or feat.get("geom_type") or feat.get("geometry_type")
        pairs.append(
            {
                "source": source_name,
                "target": target_name,
                "intersection_geom_type": geom_type,
            }
        )

    return {
        "tool": "spatial.intersects",
        "total_matches": total,
        "source_layer": data.get("source_layer"),
        "target_layer": data.get("target_layer"),
        "pairs": pairs,
        "supports_intersection": True,
        "supports_containment": False,
    }


def _extract_query_layer_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    features = data.get("features") or data.get("items") or data.get("results") or []
    total = data.get("count_total")
    if total is None:
        total = data.get("count")
    if total is None:
        total = len(features)

    sample = []
    for feat in features[:10]:
        centroid = feat.get("centroid")
        sample.append(
            {
                "id": feat.get("id"),
                "name": feat.get("name"),
                "geometry_type": feat.get("geometry_type") or feat.get("geom_type"),
                "centroid": centroid,
                "length_m": feat.get("length_m"),
                "area_m2": feat.get("area_m2"),
            }
        )

    return {
        "tool": "spatial.query_layer",
        "layer": data.get("layer"),
        "total_features": total,
        "sample": sample,
    }


def _extract_nearby_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    features = data.get("features") or data.get("items") or data.get("results") or []
    total = data.get("count_total")
    if total is None:
        total = data.get("count")
    if total is None:
        total = len(features)

    sample = []
    for feat in features[:10]:
        sample.append(
            {
                "id": feat.get("id"),
                "name": feat.get("name"),
                "distance_m": feat.get("distance_m"),
                "geometry_type": feat.get("geometry_type") or feat.get("geom_type"),
            }
        )

    return {
        "tool": "spatial.nearby",
        "layer": data.get("layer"),
        "point": data.get("point"),
        "total_features": total,
        "sample": sample,
    }


def _extract_context_pack_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    executive = data.get("executive_summary", {}) or {}
    layers = data.get("layers") or data.get("layer_summaries") or []
    highlights = data.get("highlights") or []

    normalized_layers = []
    total_features = executive.get("total_features_detected")
    if total_features is None:
        total_features = 0

    if not total_features:
        for layer in layers:
            total_features += layer.get("count") or layer.get("feature_count") or 0

    for layer in layers[:20]:
        count = layer.get("count") or layer.get("feature_count") or 0
        normalized_layers.append(
            {
                "name": layer.get("name"),
                "count": count,
                "geometry_type": layer.get("geometry_type") or layer.get("dominant_geometry_type"),
                "sample_names": layer.get("sample_names") or [],
            }
        )

    return {
        "tool": "spatial.context_pack",
        "total_layers": executive.get("total_layers_consulted", len(layers)),
        "non_empty_layers": executive.get("non_empty_layers"),
        "total_features": total_features,
        "layers": normalized_layers,
        "highlights": highlights[:10],
    }


def _extract_network_trace_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}

    segments = data.get("segments") or data.get("features") or []
    total_segments = len(segments)

    path_found = bool(
        data.get("path_found")
        or data.get("ok_path")
        or total_segments > 0
    )

    reason = data.get("reason") or data.get("status_reason")
    node_count = data.get("node_count")
    total_length_m = data.get("total_length_m") or data.get("length_m")
    start_snap_distance_m = data.get("start_snap_distance_m") or data.get("start_snap_m")
    end_snap_distance_m = data.get("end_snap_distance_m") or data.get("end_snap_m")

    segment_names = []
    for seg in segments[:20]:
        name = seg.get("name") or seg.get("segment_name") or seg.get("label")
        if name:
            segment_names.append(name)

    return {
        "tool": "spatial.network_trace",
        "path_found": path_found,
        "reason": reason,
        "node_count": node_count,
        "total_segments": total_segments,
        "total_length_m": total_length_m,
        "start_snap_distance_m": start_snap_distance_m,
        "end_snap_distance_m": end_snap_distance_m,
        "segment_names": segment_names,
    }


def extract_structured_facts(step_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    facts = []

    for step in step_outputs:
        if step.get("type") != "tool":
            continue
        if not step.get("ok"):
            continue

        tool_name = step.get("name", "")
        if tool_name == "spatial.intersects":
            facts.append(_extract_intersects_facts(step))
        elif tool_name == "spatial.query_layer":
            facts.append(_extract_query_layer_facts(step))
        elif tool_name == "spatial.nearby":
            facts.append(_extract_nearby_facts(step))
        elif tool_name == "spatial.context_pack":
            facts.append(_extract_context_pack_facts(step))
        elif tool_name == "spatial.network_trace":
            facts.append(_extract_network_trace_facts(step))

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
        elif tool_name == "spatial.network_trace":
            facts.extend(_facts_from_network_trace(data))
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
    structured_facts = extract_structured_facts(step_outputs)

    payload = {
        "goal": goal,
        "agent_name": agent_name,
        "agent_profile": agent_profile,
        "executed_tool_names": executed_tool_names,
        "plan_steps": plan.get("steps", []),
        "tool_facts": tool_facts,
        "structured_facts": structured_facts,
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