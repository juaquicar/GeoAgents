from __future__ import annotations

from typing import Any, Dict, List
import json

from .client import chat_completion_text


SYNTHESIZER_SYSTEM_PROMPT = """
Eres un analista de resultados de un framework de agentes GIS.

Tu trabajo es redactar una respuesta final clara, útil y estrictamente basada en las evidencias disponibles.

Reglas generales:
- No inventes datos.
- No hagas inferencias geométricas no demostradas explícitamente por las tools.
- Si una tool no se ejecutó, no afirmes conclusiones que dependan de ella.
- Si una tool devuelve count_total > 0, puedes afirmar que existen elementos encontrados.
- Si una tool devuelve count_total = 0, puedes afirmar que no se encontraron resultados en esa consulta.
- No digas que una geometría está "en la frontera", "dentro parcialmente", "contenida completamente" o similares salvo que eso haya sido demostrado explícitamente por los datos.
- Si el análisis es espacial, usa lenguaje geoespacial claro y prudente.
- Prioriza exactitud frente a estilo.
- La respuesta debe estar en español.
- No inventes capas, entidades, distancias, áreas, longitudes o recuentos que no aparezcan en los hechos estructurados.
- Sé prudente: si una relación topológica no está demostrada, indícalo expresamente.

Reglas por tool:
- spatial.intersects: usa "se detectó intersección entre X e Y". No afirmes contención ni inclusión. Si intersection_geom_type = POINT, es una intersección puntual, no una coincidencia de ubicación.
- spatial.nearby: habla de proximidad y distancias. Menciona el elemento más cercano y su distancia si está disponible.
- spatial.query_layer: describe el inventario/consulta. Menciona la capa, el total de elementos y los nombres o IDs de muestra.
- spatial.summary: describe el recuento por capa y tipos geométricos detectados.
- spatial.context_pack: limítate a describir contexto espacial general. No saques conclusiones topológicas específicas.
- spatial.network_trace: si path_found = false, deja claro que no se encontró ruta y menciona el motivo técnico (reason) si existe.
- spatial.route_cost: si path_found = true, describe el coste total, longitud y número de segmentos. Si path_found = false, indica que no existe ruta y el motivo.
- spatial.aggregate: describe la distribución por grupos. Menciona el grupo dominante (mayor count), el total de grupos y los campos de agrupación.
- spatial.buffer: describe los elementos encontrados dentro del radio. Menciona el radio, la fuente (punto o elemento de capa), el total encontrado y el más cercano si hay items.

Reglas de verificación:
- Si existe verification_summary, debes respetar el estado de verificación.
- Si una hipótesis está "refuted", no la presentes como hallazgo confirmado.
- Si una hipótesis está "inconclusive", dilo explícitamente.
- Si una hipótesis está "verified", puedes usarla como evidencia resumida.
- Prioriza verification_summary frente a cualquier interpretación narrativa libre.
- No afirmes que no existen intersecciones salvo que se haya ejecutado explícitamente spatial.intersects y count_total sea 0.

Reglas por perfil:
- Si agent_profile = "compact", responde de forma breve, directa y con poca ornamentación. Una sola sección.
- Si agent_profile = "rich", ofrece algo más de detalle y contexto.
- Si agent_profile = "investigate", redacta una conclusión más analítica, comparativa y exhaustiva, pero siempre basada en evidencias.

Estructura preferida para "rich" e "investigate":
1. Resumen ejecutivo (1-2 frases)
2. Hallazgos principales (lista)
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
        source_name = item.get("source_name") or item.get("source_label") or item.get("left_name") or item.get("source_id")
        target_name = item.get("target_name") or item.get("target_label") or item.get("right_name") or item.get("target_id")
        geom_type = item.get("intersection_geom_type") or item.get("geom_type") or item.get("geometry_type")
        if source_name and target_name:
            if geom_type:
                facts.append(
                    f"Se detectó intersección entre '{source_name}' y '{target_name}' con geometría resultante {geom_type}."
                )
            else:
                facts.append(
                    f"Se detectó intersección entre '{source_name}' y '{target_name}'."
                )

    return facts


def _facts_from_nearby(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    point = data.get("point", {}) or {}
    radius_m = data.get("radius_m")
    count_total = data.get("count_total")
    if count_total is None:
        count_total = data.get("count")
    items = data.get("items") or data.get("features") or data.get("results") or []
    if count_total is None:
        count_total = len(items)

    radio_str = f" (radio {radius_m} m)" if radius_m is not None else ""
    facts.append(
        f"spatial.nearby encontró {count_total} elementos en la capa '{layer}'{radio_str} "
        f"alrededor del punto ({point.get('lon')}, {point.get('lat')})."
    )

    if items:
        closest = items[0]
        closest_name = closest.get("name") or closest.get("label") or str(closest.get("id", ""))
        closest_dist = closest.get("distance_m")
        if closest_dist is not None:
            facts.append(f"Elemento más cercano: '{closest_name}' a {closest_dist:.1f} m.")

    for item in items[1:5]:
        name = item.get("name") or item.get("label") or str(item.get("id", ""))
        distance_m = item.get("distance_m")
        if distance_m is not None:
            facts.append(f"Elemento cercano '{name}' a {distance_m:.1f} m.")
        else:
            facts.append(f"Elemento cercano '{name}'.")

    return facts


def _facts_from_query_layer(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    items = data.get("items") or data.get("features") or data.get("results") or []
    count_total = data.get("count_total")
    if count_total is None:
        count_total = data.get("count")
    if count_total is None:
        count_total = len(items)

    facts.append(
        f"spatial.query_layer devolvió {count_total} elementos de la capa '{layer}'."
    )

    for item in items[:5]:
        name = item.get("name") or item.get("label") or str(item.get("id", ""))
        geom_type = item.get("geom_type") or item.get("geometry_type")
        lon = item.get("lon")
        lat = item.get("lat")
        length_m = item.get("length_m")
        area_m2 = item.get("area_m2")

        parts = [f"Elemento '{name}'"]
        if geom_type:
            parts.append(f"tipo {geom_type}")
        if lon is not None and lat is not None:
            parts.append(f"en ({lon:.5f}, {lat:.5f})")
        if length_m and float(length_m) > 0:
            parts.append(f"longitud {float(length_m):.1f} m")
        if area_m2 and float(area_m2) > 0:
            parts.append(f"área {float(area_m2):.1f} m²")
        facts.append(", ".join(parts) + ".")

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


def _facts_from_aggregate(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    group_by = data.get("group_by") or []
    total_groups = data.get("total_groups", 0)
    groups = data.get("groups") or []
    aggs = data.get("aggs") or []

    group_by_str = ", ".join(group_by) if group_by else "?"
    facts.append(
        f"spatial.aggregate agrupó la capa '{layer}' por [{group_by_str}]: {total_groups} grupos distintos."
    )

    if aggs:
        agg_desc = ", ".join(f"{a['func']}({a['field']})" for a in aggs)
        facts.append(f"Agregaciones calculadas: {agg_desc}.")

    if groups:
        top = groups[0]
        top_key = {k: top.get(k) for k in group_by if k in top}
        top_count = top.get("count")
        facts.append(
            f"Grupo dominante: {top_key} con {top_count} elementos."
        )

    for g in groups[1:5]:
        key = {k: g.get(k) for k in group_by if k in g}
        count = g.get("count")
        facts.append(f"Grupo {key}: {count} elementos.")

    return facts


def _facts_from_buffer(data: Dict[str, Any]) -> List[str]:
    facts = []
    target_layer = data.get("target_layer", "")
    buffer_m = data.get("buffer_m")
    source = data.get("source") or {}
    count_total = data.get("count_total", 0)
    items = data.get("items") or []

    if source.get("type") == "point":
        src_str = f"el punto ({source.get('lon')}, {source.get('lat')})"
    else:
        src_str = f"el elemento {source.get('id')} de la capa '{source.get('layer')}'"

    facts.append(
        f"spatial.buffer encontró {count_total} elementos de '{target_layer}' "
        f"en un radio de {buffer_m} m alrededor de {src_str}."
    )

    if items:
        closest = items[0]
        closest_name = closest.get("name") or closest.get("label") or str(closest.get("id", ""))
        closest_dist = closest.get("distance_m")
        if closest_dist is not None:
            facts.append(f"Elemento más cercano al buffer: '{closest_name}' a {closest_dist:.1f} m.")

    for item in items[1:5]:
        name = item.get("name") or item.get("label") or str(item.get("id", ""))
        dist = item.get("distance_m")
        if dist is not None:
            facts.append(f"Elemento '{name}' a {dist:.1f} m.")
        else:
            facts.append(f"Elemento '{name}' dentro del buffer.")

    return facts


def _facts_from_route_cost(data: Dict[str, Any]) -> List[str]:
    facts = []
    path_found = bool(data.get("path_found"))
    reason = data.get("reason")
    layer = data.get("layer", "")
    metric = data.get("metric", "cost")
    total_cost = data.get("total_cost")
    total_length_m = data.get("total_length_m")
    segment_ids = data.get("segment_ids") or []
    start_snap_m = data.get("start_snap_m")
    end_snap_m = data.get("end_snap_m")

    if path_found:
        facts.append(f"spatial.route_cost encontró una ruta en la capa '{layer}' (métrica: {metric}).")
        if total_cost is not None:
            facts.append(f"Coste total de la ruta: {total_cost:.4f}.")
        if total_length_m is not None:
            facts.append(f"Longitud total de la ruta: {total_length_m:.1f} m.")
        if segment_ids:
            facts.append(f"La ruta atraviesa {len(segment_ids)} segmentos (IDs: {segment_ids[:10]}).")
        if start_snap_m is not None:
            facts.append(f"Distancia de snap inicial: {start_snap_m:.1f} m.")
        if end_snap_m is not None:
            facts.append(f"Distancia de snap final: {end_snap_m:.1f} m.")
    else:
        facts.append(f"spatial.route_cost no encontró ruta en la capa '{layer}'.")
        if reason:
            facts.append(f"Motivo: {reason}.")

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
    items = data.get("items") or data.get("features") or data.get("results") or []
    total = data.get("count_total")
    if total is None:
        total = data.get("count")
    if total is None:
        total = len(items)

    sample = []
    for feat in items[:10]:
        lon = feat.get("lon")
        lat = feat.get("lat")
        sample.append(
            {
                "id": feat.get("id"),
                "name": feat.get("name"),
                "geom_type": feat.get("geom_type") or feat.get("geometry_type"),
                "lon": lon,
                "lat": lat,
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
    items = data.get("items") or data.get("features") or data.get("results") or []
    total = data.get("count_total")
    if total is None:
        total = data.get("count")
    if total is None:
        total = len(items)

    sample = []
    for feat in items[:10]:
        sample.append(
            {
                "id": feat.get("id"),
                "name": feat.get("name"),
                "distance_m": feat.get("distance_m"),
                "geom_type": feat.get("geom_type") or feat.get("geometry_type"),
            }
        )

    closest = None
    if items:
        f = items[0]
        closest = {
            "name": f.get("name") or str(f.get("id", "")),
            "distance_m": f.get("distance_m"),
        }

    return {
        "tool": "spatial.nearby",
        "layer": data.get("layer"),
        "radius_m": data.get("radius_m"),
        "point": data.get("point"),
        "total_features": total,
        "closest": closest,
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


def _extract_aggregate_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    groups = data.get("groups") or []
    group_by = data.get("group_by") or []
    aggs = data.get("aggs") or []

    top_group = None
    if groups:
        g = groups[0]
        top_group = {k: g.get(k) for k in group_by if k in g}
        top_group["count"] = g.get("count")
        for a in aggs:
            alias = a.get("alias") or f"{a.get('func')}_{a.get('field')}"
            if alias in g:
                top_group[alias] = g[alias]

    return {
        "tool": "spatial.aggregate",
        "layer": data.get("layer"),
        "group_by": group_by,
        "aggs": [{"func": a.get("func"), "field": a.get("field")} for a in aggs],
        "total_groups": data.get("total_groups", len(groups)),
        "top_group": top_group,
        "groups_sample": groups[:10],
    }


def _extract_buffer_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    items = data.get("items") or []
    source = data.get("source") or {}

    closest = None
    if items:
        f = items[0]
        closest = {
            "name": f.get("name") or str(f.get("id", "")),
            "distance_m": f.get("distance_m"),
        }

    return {
        "tool": "spatial.buffer",
        "target_layer": data.get("target_layer"),
        "buffer_m": data.get("buffer_m"),
        "source": source,
        "count_total": data.get("count_total", 0),
        "closest": closest,
        "items_sample": items[:10],
    }


def _extract_route_cost_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    path_found = bool(data.get("path_found"))
    segment_ids = data.get("segment_ids") or []

    return {
        "tool": "spatial.route_cost",
        "layer": data.get("layer"),
        "metric": data.get("metric"),
        "path_found": path_found,
        "reason": data.get("reason"),
        "total_cost": data.get("total_cost"),
        "total_length_m": data.get("total_length_m"),
        "segment_count": len(segment_ids),
        "start_snap_m": data.get("start_snap_m"),
        "end_snap_m": data.get("end_snap_m"),
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
        elif tool_name == "spatial.aggregate":
            facts.append(_extract_aggregate_facts(step))
        elif tool_name == "spatial.buffer":
            facts.append(_extract_buffer_facts(step))
        elif tool_name == "spatial.route_cost":
            facts.append(_extract_route_cost_facts(step))

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
        elif tool_name == "spatial.aggregate":
            facts.extend(_facts_from_aggregate(data))
        elif tool_name == "spatial.buffer":
            facts.extend(_facts_from_buffer(data))
        elif tool_name == "spatial.route_cost":
            facts.extend(_facts_from_route_cost(data))
        else:
            facts.append(f"La tool '{tool_name}' se ejecutó correctamente.")

    return facts


def build_verification_summary(step_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "verified": [],
        "refuted": [],
        "inconclusive": [],
        "not_evaluated": [],
    }

    for step in step_outputs:
        if step.get("type") != "tool":
            continue

        verification = step.get("verification") or {}
        status = verification.get("status") or "not_evaluated"

        item = {
            "id": step.get("id"),
            "tool": step.get("name"),
            "hypothesis": verification.get("hypothesis") or step.get("hypothesis"),
            "target": verification.get("target") or step.get("verification_target"),
            "reason": verification.get("reason"),
            "observed": verification.get("observed"),
            "criteria": verification.get("criteria") or step.get("success_criteria") or {},
            "ok": step.get("ok"),
            "error": step.get("error"),
        }

        if status not in summary:
            status = "not_evaluated"
        summary[status].append(item)

    summary["counts"] = {
        key: len(value)
        for key, value in summary.items()
        if isinstance(value, list)
    }
    return summary


_LARGE_DATA_KEYS = {"items", "features", "results", "segments", "layers", "highlights", "pairs"}
_STEP_SAMPLE_SIZE = 5  # items máximos por array en step_outputs enviados al LLM


def _truncate_step_output(step: Dict[str, Any]) -> Dict[str, Any]:
    """Elimina arrays masivos del output de una tool, conservando metadatos y muestra pequeña."""
    import copy
    step = copy.deepcopy(step)
    data = step.get("data")
    if not isinstance(data, dict):
        return step

    for key in list(data.keys()):
        if key in _LARGE_DATA_KEYS and isinstance(data[key], list):
            original_len = len(data[key])
            data[key] = data[key][:_STEP_SAMPLE_SIZE]
            if original_len > _STEP_SAMPLE_SIZE:
                data[f"{key}_total"] = original_len
                data[f"{key}_truncated"] = True
    step["data"] = data
    return step


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
    verification_summary = build_verification_summary(step_outputs)

    payload = {
        "goal": goal,
        "agent_name": agent_name,
        "agent_profile": agent_profile,
        "executed_tool_names": executed_tool_names,
        "plan_steps": plan.get("steps", []),
        "tool_facts": tool_facts,
        "structured_facts": structured_facts,
        "verification_summary": verification_summary,
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