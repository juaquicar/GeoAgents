from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional, Sequence


POINT_HINTS = [
    "point", "points", "pto", "ptos", "node", "nodes",
    "cpe", "cto", "ont", "device", "devices", "marker", "markers",
    "punto", "puntos", "nodo", "nodos",
]

POLYGON_HINTS = [
    "polygon", "polygons", "zona", "zonas", "area", "areas",
    "sector", "sectors", "parcel", "parcela", "parcelas",
    "poligono", "poligonos", "polígono", "polígonos",
]

LINE_HINTS = [
    "line", "lines",
    "linea", "lineas", "línea", "líneas",
    "segment", "segments",
    "tramo", "tramos",
    "link", "links",
    "cable", "cables",
    "route", "routes",
    "ruta", "rutas",
    "red", "network",
]

GOAL_TERMS = {
    "point": [
        "punto", "puntos", "point", "points", "nodo", "nodos",
        "cto", "cpe", "ont", "dispositivo", "dispositivos",
    ],
    "line": [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos",
        "cable", "cables", "ruta", "rutas",
        "red", "network",
    ],
    "polygon": [
        "zona", "zonas", "area", "areas", "poligono", "polígono",
        "poligonos", "polígonos", "polygon", "polygons",
        "sector", "sectores", "parcela", "parcelas",
    ],
}


EXPLICIT_GEOMETRY_KEYS = (
    "geometry_kind",
    "geom_family",
    "geometry_family",
    "geometry_type",
    "geometry_types",
    "geom_type",
    "geom_types",
    "kind",
)


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _text_blob(layer: Dict[str, Any]) -> str:
    parts = [
        layer.get("name", ""),
        layer.get("table", ""),
        " ".join(layer.get("fields", []) or []),
        " ".join(layer.get("filter_fields", []) or []),
    ]
    return " ".join(_normalize_text(part) for part in parts if part)


def _map_geometry_token_to_kind(token: Any) -> Optional[str]:
    token = _normalize_text(token)
    if not token:
        return None

    if any(part in token for part in ("point", "multipoint")):
        return "point"
    if any(part in token for part in ("line", "linestring", "multiline", "edge", "arc")):
        return "line"
    if any(part in token for part in ("polygon", "multipolygon", "area", "surface")):
        return "polygon"
    return None


def extract_explicit_layer_kind(layer: Dict[str, Any]) -> Optional[str]:
    for key in EXPLICIT_GEOMETRY_KEYS:
        value = layer.get(key)
        if value is None:
            continue

        if isinstance(value, (list, tuple, set)):
            for item in value:
                kind = _map_geometry_token_to_kind(item)
                if kind:
                    return kind
            continue

        kind = _map_geometry_token_to_kind(value)
        if kind:
            return kind

    return None


def score_layer_kind(layer: Dict[str, Any]) -> Dict[str, int]:
    explicit_kind = extract_explicit_layer_kind(layer)
    if explicit_kind:
        return {
            "point": 100 if explicit_kind == "point" else 0,
            "polygon": 100 if explicit_kind == "polygon" else 0,
            "line": 100 if explicit_kind == "line" else 0,
        }

    text = _text_blob(layer)
    name = _normalize_text(layer.get("name", ""))
    table = _normalize_text(layer.get("table", ""))

    def _score(hints: Sequence[str]) -> int:
        score = 0
        for hint in hints:
            hint = _normalize_text(hint)
            if hint in text:
                score += 1
            if hint and hint in name:
                score += 2
            if hint and hint in table:
                score += 1
        return score

    return {
        "point": _score(POINT_HINTS),
        "polygon": _score(POLYGON_HINTS),
        "line": _score(LINE_HINTS),
    }


def classify_layer_kind(layer: Dict[str, Any]) -> str:
    explicit_kind = extract_explicit_layer_kind(layer)
    if explicit_kind:
        return explicit_kind

    scores = score_layer_kind(layer)
    best_kind = max(scores, key=scores.get)
    best_score = scores[best_kind]

    if best_score <= 0:
        return "unknown"

    return best_kind


def _sorted_candidates(
    gis_layers_catalog: List[Dict[str, Any]],
    kind: str,
) -> List[str]:
    candidates = []
    for layer in gis_layers_catalog:
        scores = score_layer_kind(layer)
        candidates.append((scores.get(kind, 0), layer.get("name")))

    candidates.sort(reverse=True, key=lambda x: (x[0], x[1] or ""))
    return [name for score, name in candidates if score > 0 and name]


def _goal_kind_mentions(goal: str) -> List[str]:
    normalized_goal = _normalize_text(goal)
    hits = []
    for kind, terms in GOAL_TERMS.items():
        positions = [normalized_goal.find(_normalize_text(term)) for term in terms]
        positions = [pos for pos in positions if pos >= 0]
        if positions:
            hits.append((min(positions), kind))
    hits.sort(key=lambda item: item[0])
    return [kind for _, kind in hits]


def _available_kinds(gis_layers_catalog: List[Dict[str, Any]]) -> List[str]:
    kinds = []
    for kind in ("point", "line", "polygon"):
        if _sorted_candidates(gis_layers_catalog, kind):
            kinds.append(kind)
    return kinds


def _find_best_layer_of_kind(gis_layers_catalog: List[Dict[str, Any]], kind: str) -> Optional[str]:
    candidates = _sorted_candidates(gis_layers_catalog, kind)
    return candidates[0] if candidates else None


def _choose_best_layer_for_goal(goal: str, gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    requested_kinds = _goal_kind_mentions(goal)
    fallback_order = [kind for kind in ("point", "line", "polygon") if kind not in requested_kinds]

    for kind in requested_kinds + fallback_order:
        layer = _find_best_layer_of_kind(gis_layers_catalog, kind)
        if layer:
            return layer

    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")
    return None


def find_best_point_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    return _find_best_layer_of_kind(gis_layers_catalog, "point")


def find_best_polygon_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    return _find_best_layer_of_kind(gis_layers_catalog, "polygon")


def find_best_line_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    return _find_best_layer_of_kind(gis_layers_catalog, "line")


def infer_nearby_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    return _choose_best_layer_for_goal(goal, gis_layers_catalog)


def infer_intersection_layers(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    requested_kinds = _goal_kind_mentions(goal)

    if len(requested_kinds) < 2:
        default_pair = ["point", "polygon"]
        requested_kinds = requested_kinds + [kind for kind in default_pair if kind not in requested_kinds]

    requested_kinds = requested_kinds[:2]

    source_layer = _find_best_layer_of_kind(gis_layers_catalog, requested_kinds[0]) if requested_kinds else None
    target_layer = _find_best_layer_of_kind(gis_layers_catalog, requested_kinds[1]) if len(requested_kinds) > 1 else None

    if source_layer == target_layer:
        available_kinds = _available_kinds(gis_layers_catalog)
        for kind in available_kinds:
            if kind != requested_kinds[0]:
                target_layer = _find_best_layer_of_kind(gis_layers_catalog, kind)
                if target_layer and target_layer != source_layer:
                    break

    return {
        "source_layer": source_layer,
        "target_layer": target_layer,
    }


def infer_query_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    return _choose_best_layer_for_goal(goal, gis_layers_catalog)


def infer_network_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    layer = find_best_line_layer(gis_layers_catalog)
    if layer:
        return layer
    return _choose_best_layer_for_goal(goal, gis_layers_catalog)