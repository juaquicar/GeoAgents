from typing import Any, Dict, List, Optional


POINT_HINTS = [
    "point", "points", "pto", "ptos", "node", "nodes",
    "cpe", "cto", "ont", "device", "devices", "marker", "markers",
]

POLYGON_HINTS = [
    "polygon", "polygons", "zona", "zonas", "area", "areas",
    "sector", "sectors", "parcel", "parcela", "parcelas",
]

LINE_HINTS = [
    "line", "lines", "linea", "lineas", "segment", "segments",
    "tramo", "tramos", "link", "links", "cable", "cables",
]


def _text_blob(layer: Dict[str, Any]) -> str:
    parts = [
        str(layer.get("name", "")),
        str(layer.get("table", "")),
        " ".join(layer.get("fields", []) or []),
        " ".join(layer.get("filter_fields", []) or []),
    ]
    return " ".join(parts).lower()


def score_layer_kind(layer: Dict[str, Any]) -> Dict[str, int]:
    text = _text_blob(layer)

    point_score = sum(1 for hint in POINT_HINTS if hint in text)
    polygon_score = sum(1 for hint in POLYGON_HINTS if hint in text)
    line_score = sum(1 for hint in LINE_HINTS if hint in text)

    return {
        "point": point_score,
        "polygon": polygon_score,
        "line": line_score,
    }


def classify_layer_kind(layer: Dict[str, Any]) -> str:
    scores = score_layer_kind(layer)

    best_kind = max(scores, key=scores.get)
    best_score = scores[best_kind]

    if best_score <= 0:
        return "unknown"

    return best_kind


def find_best_point_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    candidates = []
    for layer in gis_layers_catalog:
        scores = score_layer_kind(layer)
        candidates.append((scores["point"], layer.get("name")))

    candidates.sort(reverse=True, key=lambda x: (x[0], x[1] or ""))
    if not candidates or candidates[0][0] <= 0:
        return None
    return candidates[0][1]


def find_best_polygon_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    candidates = []
    for layer in gis_layers_catalog:
        scores = score_layer_kind(layer)
        candidates.append((scores["polygon"], layer.get("name")))

    candidates.sort(reverse=True, key=lambda x: (x[0], x[1] or ""))
    if not candidates or candidates[0][0] <= 0:
        return None
    return candidates[0][1]


def infer_nearby_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Para nearby, por defecto preferimos capas de puntos.
    """
    goal = (goal or "").lower()

    # Regla futura: si el goal menciona algo concreto, refinar aquí.
    best_point = find_best_point_layer(gis_layers_catalog)
    if best_point:
        return best_point

    # Fallback: primera capa si no hay mejor pista
    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")

    return None


def infer_intersection_layers(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """
    Para intersects, por defecto:
    - source_layer -> capa de puntos
    - target_layer -> capa de polígonos
    """
    goal = (goal or "").lower()

    source_layer = find_best_point_layer(gis_layers_catalog)
    target_layer = find_best_polygon_layer(gis_layers_catalog)

    # Evitar elegir la misma si solo hay una capa rara
    if source_layer and target_layer and source_layer == target_layer:
        target_layer = None

    return {
        "source_layer": source_layer,
        "target_layer": target_layer,
    }