from __future__ import annotations

from typing import Any, Dict, List
import json

from .client import chat_completion_json, chat_completion_text


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
- spatial.dissolve: describe los grupos resultantes. Menciona la capa, el campo de disolución, el número de grupos y el área fusionada de los grupos principales.
- spatial.centroid: describe los centroides extraídos. Menciona la capa, el total de elementos y las coordenadas de muestra.
- spatial.count_within: describe cuántos elementos de target_layer hay en cada feature de source_layer. Menciona los source features con más elementos.
- spatial.spatial_join: describe qué atributos se han adjuntado y de qué capa. Menciona el join_type y si hubo features sin match (null).
- spatial.clip: describe cuántos features se recortaron y las áreas/longitudes resultantes.
- spatial.difference: describe el área original, el área residual y cuántos features se restaron.
- spatial.grid_stats: describe las celdas con mayor concentración. Menciona la resolución de celda y el número de celdas no vacías.
- spatial.cluster_dbscan: describe el número de clusters encontrados, el cluster más grande y los outliers. Menciona eps_m y min_points usados.

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

Si session_context está presente:
- Contiene los turnos anteriores de la misma conversación (goal, ok, final_text).
- Úsalo para dar continuidad narrativa cuando el usuario hace preguntas de seguimiento.
- Si el turno anterior encontró N elementos y el actual refina la búsqueda, puedes hacer referencia al análisis previo de forma natural.
- No repitas literalmente el contenido del turno anterior; sintetiza el progreso de la conversación.
- Si un turno previo tiene ok=false, no lo menciones como resultado previo válido.
"""

SYNTHESIZER_SQL_ADDENDUM = """
Además de final_text, debes generar final_sql: una sentencia SELECT PostGIS que represente
visualmente el resultado en un mapa GeoJSON.

Reglas OBLIGATORIAS para final_sql:

1. GEOMETRÍA siempre en WGS84 (EPSG:4326) para ST_AsGeoJSON:
   - Si SRID de la capa es 4326:  ST_AsGeoJSON(t.geom_col) AS geom_geojson
   - Si SRID es distinto de 4326: ST_AsGeoJSON(ST_Transform(t.geom_col, 4326)) AS geom_geojson
   NUNCA pases directamente una geometría en SRID proyectado a ST_AsGeoJSON.

2. FILTRO ESPACIAL (si hay bbox en map_context):
   El bbox del user_prompt está en WGS84 (grados). Si la capa está en SRID proyectado,
   DEBES transformar el envelope al SRID de la capa:
   - Capa en 4326:   ST_Intersects(t.geom, ST_MakeEnvelope(west, south, east, north, 4326))
   - Capa en 25830:  ST_Intersects(t.geom, ST_Transform(ST_MakeEnvelope(west, south, east, north, 4326), 25830))
   - Capa en 3857:   ST_Intersects(t.geom, ST_Transform(ST_MakeEnvelope(west, south, east, north, 4326), 3857))
   NUNCA uses ST_MakeEnvelope con coordenadas en grados y SRID proyectado.

3. COLUMNA _feature_type (siempre incluir):
   - 'result'     — feature principal del resultado
   - 'source'     — feature origen en nearest_neighbor o within_distance
   - 'neighbor'   — feature vecino/referencia
   - 'connection' — línea ST_MakeLine que une source y neighbor

4. LIMIT: usa LIMIT :limit (el backend lo sustituirá). No pongas un número fijo.

5. Solo tablas del catálogo del agente (campo gis_layers_catalog). Solo lectura.

6. Para nearest_neighbor o within_distance, genera UNION ALL con:
   - SELECT source features ... 'source' AS _feature_type
   - UNION ALL SELECT neighbor features ... 'neighbor' AS _feature_type
   - UNION ALL SELECT ST_AsGeoJSON(ST_MakeLine(...)) ... 'connection' AS _feature_type

7. Si no hay información suficiente para generar una query correcta, devuelve final_sql = "".

Catálogo de capas en gis_layers_catalog (nombre, tabla, schema, geom_col, id_col, srid).
Usa schema.tabla (ej: public.span) en el FROM.

Devuelve un JSON con exactamente dos claves:
{
  "final_text": "...",
  "final_sql": "SELECT ..."
}
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


def _facts_from_dissolve(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    dissolve_field = data.get("dissolve_field", "")
    total_groups = data.get("total_groups", 0)
    features = data.get("dissolved_features") or []

    facts.append(
        f"spatial.dissolve fusionó la capa '{layer}' por el campo '{dissolve_field}': "
        f"{total_groups} grupos resultantes."
    )
    for f in features[:5]:
        val = f.get(dissolve_field, "?")
        count = f.get("feature_count", "?")
        area = f.get("dissolved_area_m2")
        if area is not None:
            facts.append(f"Grupo '{val}': {count} features originales, área fusionada {area:.1f} m².")
        else:
            facts.append(f"Grupo '{val}': {count} features originales.")
    return facts


def _facts_from_centroid(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    count_total = data.get("count_total", 0)
    items = data.get("items") or []

    facts.append(f"spatial.centroid extrajo {count_total} centroides de la capa '{layer}'.")
    for item in items[:5]:
        lon = item.get("centroid_lon")
        lat = item.get("centroid_lat")
        fid = item.get("id") or item.get("fid")
        if lon is not None and lat is not None:
            facts.append(f"Centroide del elemento {fid}: ({lon:.5f}, {lat:.5f}).")
    return facts


def _extract_dissolve_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    features = data.get("dissolved_features") or []
    return {
        "tool": "spatial.dissolve",
        "layer": data.get("layer"),
        "dissolve_field": data.get("dissolve_field"),
        "total_groups": data.get("total_groups", len(features)),
        "groups_sample": features[:10],
    }


def _extract_centroid_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    items = data.get("items") or []
    return {
        "tool": "spatial.centroid",
        "layer": data.get("layer"),
        "count_total": data.get("count_total", len(items)),
        "items_sample": items[:10],
    }


def _facts_from_count_within(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    tgt = data.get("target_layer", "")
    items = data.get("items") or []
    facts.append(f"spatial.count_within: conteo de '{tgt}' dentro de cada feature de '{src}'.")
    for item in items[:5]:
        fid = item.get("id") or item.get("fid")
        count = item.get("count_within", 0)
        facts.append(f"Feature {fid}: {count} elementos de '{tgt}' en su interior.")
    return facts


def _facts_from_spatial_join(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    join = data.get("join_layer", "")
    join_type = data.get("join_type", "")
    count = data.get("count_total", len(data.get("items") or []))
    facts.append(
        f"spatial.spatial_join ({join_type}): adjuntó atributos de '{join}' a {count} features de '{src}'."
    )
    return facts


def _facts_from_clip(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    clip_layer = data.get("clip_layer") or "bbox"
    items = data.get("items") or []
    facts.append(f"spatial.clip recortó {len(items)} features de '{src}' a la geometría de '{clip_layer}'.")
    for item in items[:3]:
        fid = item.get("id") or item.get("fid")
        area = item.get("clipped_area_m2")
        length = item.get("clipped_length_m")
        if area and float(area) > 0:
            facts.append(f"Feature {fid}: área recortada {float(area):.1f} m².")
        elif length and float(length) > 0:
            facts.append(f"Feature {fid}: longitud recortada {float(length):.1f} m.")
    return facts


def _facts_from_difference(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    sub = data.get("subtract_layer", "")
    orig = data.get("original_area_m2")
    diff = data.get("difference_area_m2")
    sub_count = data.get("subtracted_features", 0)
    facts.append(
        f"spatial.difference: área original de '{src}' {orig:.1f} m², "
        f"área residual tras restar '{sub}': {diff:.1f} m² "
        f"({sub_count} features restados)."
        if orig is not None and diff is not None else
        f"spatial.difference ejecutado sobre '{src}' restando '{sub}'."
    )
    return facts


def _facts_from_grid_stats(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    cell_size = data.get("cell_size_m")
    non_empty = data.get("non_empty_cells", len(data.get("cells") or []))
    cells = data.get("cells") or []
    facts.append(
        f"spatial.grid_stats: {non_empty} celdas con elementos de '{layer}' "
        f"(resolución {cell_size} m)."
    )
    if cells:
        top = cells[0]
        facts.append(f"Celda más densa: col={top.get('col')}, row={top.get('row')}, count={top.get('count')}.")
    return facts


def _facts_from_cluster_dbscan(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    eps_m = data.get("eps_m")
    min_pts = data.get("min_points")
    n_clusters = data.get("cluster_count", 0)
    noise = data.get("noise_count", 0)
    total = data.get("total_features", 0)
    facts.append(
        f"spatial.cluster_dbscan en '{layer}' (eps={eps_m} m, min_points={min_pts}): "
        f"{n_clusters} clusters encontrados, {noise} outliers de {total} features totales."
    )
    summary = data.get("cluster_summary") or []
    real = [s for s in summary if s.get("cluster_id") != -1]
    if real:
        top = real[0]
        facts.append(
            f"Cluster más grande: id={top.get('cluster_id')}, "
            f"{top.get('count')} features, centroide "
            f"({top.get('centroid_lon', 0):.5f}, {top.get('centroid_lat', 0):.5f})."
        )
    return facts


def _extract_count_within_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.count_within",
        "source_layer": data.get("source_layer"),
        "target_layer": data.get("target_layer"),
        "items": (data.get("items") or [])[:10],
    }


def _extract_spatial_join_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.spatial_join",
        "source_layer": data.get("source_layer"),
        "join_layer": data.get("join_layer"),
        "join_type": data.get("join_type"),
        "count_total": data.get("count_total"),
        "items_sample": (data.get("items") or [])[:5],
    }


def _extract_clip_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.clip",
        "source_layer": data.get("source_layer"),
        "clip_layer": data.get("clip_layer"),
        "count_total": data.get("count_total"),
        "items_sample": (data.get("items") or [])[:5],
    }


def _extract_difference_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.difference",
        "source_layer": data.get("source_layer"),
        "subtract_layer": data.get("subtract_layer"),
        "original_area_m2": data.get("original_area_m2"),
        "difference_area_m2": data.get("difference_area_m2"),
        "subtracted_features": data.get("subtracted_features"),
    }


def _extract_grid_stats_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    cells = data.get("cells") or []
    return {
        "tool": "spatial.grid_stats",
        "layer": data.get("layer"),
        "cell_size_m": data.get("cell_size_m"),
        "non_empty_cells": data.get("non_empty_cells", len(cells)),
        "top_cells": cells[:10],
    }


def _extract_cluster_dbscan_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.cluster_dbscan",
        "layer": data.get("layer"),
        "eps_m": data.get("eps_m"),
        "min_points": data.get("min_points"),
        "cluster_count": data.get("cluster_count"),
        "noise_count": data.get("noise_count"),
        "total_features": data.get("total_features"),
        "cluster_summary": data.get("cluster_summary") or [],
    }


def _facts_from_convex_hull(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    count = data.get("feature_count", 0)
    area = data.get("hull_area_m2")
    lon = data.get("centroid_lon")
    lat = data.get("centroid_lat")
    area_str = f", área={area:,.0f} m²" if area else ""
    coord_str = f", centroide ({lon:.5f}, {lat:.5f})" if lon and lat else ""
    facts.append(
        f"spatial.convex_hull de '{layer}': {count} features incluidos{area_str}{coord_str}."
    )
    return facts


def _extract_convex_hull_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.convex_hull",
        "layer": data.get("layer"),
        "feature_count": data.get("feature_count"),
        "hull_area_m2": data.get("hull_area_m2"),
        "centroid_lon": data.get("centroid_lon"),
        "centroid_lat": data.get("centroid_lat"),
    }


def _facts_from_voronoi(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    count = data.get("polygon_count", 0)
    facts.append(
        f"spatial.voronoi de '{layer}': {count} polígonos de Voronoi generados."
    )
    polys = data.get("polygons") or []
    if polys:
        areas = [p.get("voronoi_area_m2", 0) for p in polys if p.get("voronoi_area_m2")]
        if areas:
            facts.append(
                f"Área media de influencia: {sum(areas)/len(areas):,.0f} m² "
                f"(rango {min(areas):,.0f}–{max(areas):,.0f} m²)."
            )
    return facts


def _extract_voronoi_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    polys = data.get("polygons") or []
    return {
        "tool": "spatial.voronoi",
        "layer": data.get("layer"),
        "polygon_count": data.get("polygon_count"),
        "polygons_sample": polys[:5],
    }


def _facts_from_measure(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    geo_type = data.get("geometry_type", "")
    group_by = data.get("group_by")
    if group_by:
        groups = data.get("groups") or []
        facts.append(
            f"spatial.measure de '{layer}' agrupado por '{group_by}': {len(groups)} grupos."
        )
        for g in groups[:3]:
            if geo_type == "line":
                val = g.get("total_length_m")
                metric = f"longitud={val:,.0f} m" if val else ""
            elif geo_type == "polygon":
                val = g.get("total_area_m2")
                metric = f"área={val:,.0f} m²" if val else ""
            else:
                val = g.get("feature_count")
                metric = f"count={val}" if val else ""
            facts.append(f"  {g.get(group_by, '?')}: {metric}")
    else:
        totals = data.get("totals") or {}
        if geo_type == "line":
            total_l = totals.get("total_length_m")
            avg_l = totals.get("avg_length_m")
            facts.append(
                f"spatial.measure de '{layer}' (líneas): "
                f"longitud total={total_l:,.0f} m, media={avg_l:,.0f} m/feature."
                if total_l else f"spatial.measure de '{layer}': sin datos de longitud."
            )
        elif geo_type == "polygon":
            total_a = totals.get("total_area_m2")
            facts.append(
                f"spatial.measure de '{layer}' (polígonos): área total={total_a:,.0f} m²."
                if total_a else f"spatial.measure de '{layer}': sin datos de área."
            )
        else:
            cnt = totals.get("feature_count", 0)
            facts.append(f"spatial.measure de '{layer}': {cnt} puntos.")
    return facts


def _extract_measure_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.measure",
        "layer": data.get("layer"),
        "geometry_type": data.get("geometry_type"),
        "group_by": data.get("group_by"),
        "totals": data.get("totals"),
        "groups_sample": (data.get("groups") or [])[:10],
    }


def _facts_from_overlay(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer_a = data.get("layer_a", "")
    layer_b = data.get("layer_b", "")
    mode = data.get("mode", "")
    area = data.get("result_area_m2", 0)
    is_empty = data.get("is_empty", False)
    if is_empty:
        facts.append(
            f"spatial.overlay ({mode}) entre '{layer_a}' y '{layer_b}': resultado vacío (sin solapamiento)."
        )
    else:
        facts.append(
            f"spatial.overlay ({mode}) entre '{layer_a}' y '{layer_b}': área resultado={area:,.0f} m²."
        )
    return facts


def _extract_overlay_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.overlay",
        "layer_a": data.get("layer_a"),
        "layer_b": data.get("layer_b"),
        "mode": data.get("mode"),
        "result_area_m2": data.get("result_area_m2"),
        "is_empty": data.get("is_empty"),
    }


def _facts_from_nearest_neighbor(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    nbr = data.get("neighbor_layer", "")
    n = data.get("pair_count", 0)
    max_d = data.get("max_distance_m")
    max_str = f" (máx {max_d} m)" if max_d else ""
    facts.append(
        f"spatial.nearest_neighbor '{src}' → '{nbr}'{max_str}: {n} pares encontrados."
    )
    pairs = data.get("pairs") or []
    if pairs:
        dists = [p.get("distance_m", 0) for p in pairs if p.get("distance_m") is not None]
        if dists:
            facts.append(
                f"Distancia media al vecino: {sum(dists)/len(dists):,.1f} m "
                f"(mín {min(dists):,.1f} m, máx {max(dists):,.1f} m)."
            )
    return facts


def _extract_nearest_neighbor_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.nearest_neighbor",
        "source_layer": data.get("source_layer"),
        "neighbor_layer": data.get("neighbor_layer"),
        "pair_count": data.get("pair_count"),
        "pairs_sample": (data.get("pairs") or [])[:5],
    }


def _facts_from_within_distance(data: Dict[str, Any]) -> List[str]:
    facts = []
    src = data.get("source_layer", "")
    ref = data.get("reference_layer", "")
    dist = data.get("distance_m", 0)
    total = data.get("total_within_distance", 0)
    facts.append(
        f"spatial.within_distance: {total} features de '{src}' a menos de {dist} m de '{ref}'."
    )
    return facts


def _extract_within_distance_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.within_distance",
        "source_layer": data.get("source_layer"),
        "reference_layer": data.get("reference_layer"),
        "distance_m": data.get("distance_m"),
        "total_within_distance": data.get("total_within_distance"),
        "features_sample": (data.get("features") or [])[:5],
    }


def _facts_from_topology_check(data: Dict[str, Any]) -> List[str]:
    facts = []
    layer = data.get("layer", "")
    total = data.get("total_features_checked", 0)
    invalid = data.get("invalid_geometry_count", 0)
    clean = data.get("is_topologically_clean", False)
    if clean:
        facts.append(f"spatial.topology_check de '{layer}': {total} features revisados, sin problemas detectados.")
    else:
        facts.append(
            f"spatial.topology_check de '{layer}': {total} features revisados, "
            f"{invalid} geometrías inválidas/vacías encontradas."
        )
        overlap_pairs = data.get("overlapping_pairs_count")
        if overlap_pairs is not None and overlap_pairs > 0:
            facts.append(f"Además, {overlap_pairs} pares con solapamiento detectados.")
    return facts


def _extract_topology_check_facts(step_output: Dict[str, Any]) -> Dict[str, Any]:
    data = step_output.get("data") or {}
    return {
        "tool": "spatial.topology_check",
        "layer": data.get("layer"),
        "total_features_checked": data.get("total_features_checked"),
        "invalid_geometry_count": data.get("invalid_geometry_count"),
        "is_topologically_clean": data.get("is_topologically_clean"),
        "invalid_features": (data.get("invalid_features") or [])[:10],
        "overlapping_pairs_count": data.get("overlapping_pairs_count"),
    }


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
        elif tool_name == "spatial.dissolve":
            facts.append(_extract_dissolve_facts(step))
        elif tool_name == "spatial.centroid":
            facts.append(_extract_centroid_facts(step))
        elif tool_name == "spatial.count_within":
            facts.append(_extract_count_within_facts(step))
        elif tool_name == "spatial.spatial_join":
            facts.append(_extract_spatial_join_facts(step))
        elif tool_name == "spatial.clip":
            facts.append(_extract_clip_facts(step))
        elif tool_name == "spatial.difference":
            facts.append(_extract_difference_facts(step))
        elif tool_name == "spatial.grid_stats":
            facts.append(_extract_grid_stats_facts(step))
        elif tool_name == "spatial.cluster_dbscan":
            facts.append(_extract_cluster_dbscan_facts(step))
        elif tool_name == "spatial.convex_hull":
            facts.append(_extract_convex_hull_facts(step))
        elif tool_name == "spatial.voronoi":
            facts.append(_extract_voronoi_facts(step))
        elif tool_name == "spatial.measure":
            facts.append(_extract_measure_facts(step))
        elif tool_name == "spatial.overlay":
            facts.append(_extract_overlay_facts(step))
        elif tool_name == "spatial.nearest_neighbor":
            facts.append(_extract_nearest_neighbor_facts(step))
        elif tool_name == "spatial.within_distance":
            facts.append(_extract_within_distance_facts(step))
        elif tool_name == "spatial.topology_check":
            facts.append(_extract_topology_check_facts(step))

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
        elif tool_name == "spatial.dissolve":
            facts.extend(_facts_from_dissolve(data))
        elif tool_name == "spatial.centroid":
            facts.extend(_facts_from_centroid(data))
        elif tool_name == "spatial.count_within":
            facts.extend(_facts_from_count_within(data))
        elif tool_name == "spatial.spatial_join":
            facts.extend(_facts_from_spatial_join(data))
        elif tool_name == "spatial.clip":
            facts.extend(_facts_from_clip(data))
        elif tool_name == "spatial.difference":
            facts.extend(_facts_from_difference(data))
        elif tool_name == "spatial.grid_stats":
            facts.extend(_facts_from_grid_stats(data))
        elif tool_name == "spatial.cluster_dbscan":
            facts.extend(_facts_from_cluster_dbscan(data))
        elif tool_name == "spatial.convex_hull":
            facts.extend(_facts_from_convex_hull(data))
        elif tool_name == "spatial.voronoi":
            facts.extend(_facts_from_voronoi(data))
        elif tool_name == "spatial.measure":
            facts.extend(_facts_from_measure(data))
        elif tool_name == "spatial.overlay":
            facts.extend(_facts_from_overlay(data))
        elif tool_name == "spatial.nearest_neighbor":
            facts.extend(_facts_from_nearest_neighbor(data))
        elif tool_name == "spatial.within_distance":
            facts.extend(_facts_from_within_distance(data))
        elif tool_name == "spatial.topology_check":
            facts.extend(_facts_from_topology_check(data))
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
    session_context: List[Dict[str, Any]] | None = None,
    gis_layers_catalog: List[Dict[str, Any]] | None = None,
    map_context: Dict[str, Any] | None = None,
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
    if session_context:
        # Solo enviamos los turnos exitosos con final_text — el synthesizer no necesita ver fallos
        prev = [
            {"goal": t["goal"], "final_text": t.get("final_text", "")}
            for t in session_context
            if t.get("ok") and t.get("final_text")
        ]
        if prev:
            payload["session_context"] = prev

    if gis_layers_catalog:
        # Resumen compacto del catálogo para orientar la generación de SQL
        catalog_summary = [
            {
                "name": layer.get("name"),
                "table": layer.get("table"),
                "schema": layer.get("schema"),
                "geom_col": layer.get("geom_col", "the_geom"),
                "id_col": layer.get("id_col", "id"),
                "srid": layer.get("srid", 4326),
            }
            for layer in gis_layers_catalog
            if layer.get("name") and layer.get("table")
        ]
        if catalog_summary:
            payload["gis_layers_catalog"] = catalog_summary

    if map_context:
        payload["map_context"] = map_context

    return json.dumps(payload, ensure_ascii=False, indent=2)


def synthesize_run(
    *,
    goal: str,
    agent_name: str,
    agent_profile: str,
    plan: Dict[str, Any],
    step_outputs: List[Dict[str, Any]],
    session_context: List[Dict[str, Any]] | None = None,
    gis_layers_catalog: List[Dict[str, Any]] | None = None,
    map_context: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """
    Devuelve un dict con 'final_text' y 'final_sql'.
    'final_sql' puede ser cadena vacía si el LLM no genera query útil.
    """
    user_prompt = build_synthesizer_user_prompt(
        goal=goal,
        agent_name=agent_name,
        agent_profile=agent_profile,
        plan=plan,
        step_outputs=step_outputs,
        session_context=session_context,
        gis_layers_catalog=gis_layers_catalog,
        map_context=map_context,
    )
    system_prompt = SYNTHESIZER_SYSTEM_PROMPT + SYNTHESIZER_SQL_ADDENDUM
    result = chat_completion_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )
    return {
        "final_text": str(result.get("final_text") or ""),
        "final_sql": str(result.get("final_sql") or ""),
    }