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


def find_best_point_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    candidates = _sorted_candidates(gis_layers_catalog, "point")
    return candidates[0] if candidates else None


def find_best_polygon_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    candidates = _sorted_candidates(gis_layers_catalog, "polygon")
    return candidates[0] if candidates else None


def find_best_line_layer(gis_layers_catalog: List[Dict[str, Any]]) -> Optional[str]:
    candidates = _sorted_candidates(gis_layers_catalog, "line")
    return candidates[0] if candidates else None


def infer_nearby_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Para nearby, por defecto preferimos capas de puntos.
    """
    goal = (goal or "").lower()

    best_point = find_best_point_layer(gis_layers_catalog)
    if best_point:
        return best_point

    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")

    return None


def infer_intersection_layers(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """
    Para intersects:
    - intenta detectar el tipo de geometría mencionado en el goal
    - permite combinaciones punto/polígono, línea/polígono y punto/línea
    - fallback conservador: punto -> polígono
    """
    goal = (goal or "").lower()

    point_layer = find_best_point_layer(gis_layers_catalog)
    line_layer = find_best_line_layer(gis_layers_catalog)
    polygon_layer = find_best_polygon_layer(gis_layers_catalog)

    point_terms = [
        "punto", "puntos", "point", "points", "nodo", "nodos",
        "cto", "cpe", "ont", "dispositivo", "dispositivos",
    ]
    line_terms = [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos", "cable", "cables",
    ]
    polygon_terms = [
        "zona", "zonas", "area", "areas", "poligono", "poligonos", "polígonos",
        "polygon", "polygons", "sector", "sectores", "parcela", "parcelas",
    ]

    has_point_terms = any(term in goal for term in point_terms)
    has_line_terms = any(term in goal for term in line_terms)
    has_polygon_terms = any(term in goal for term in polygon_terms)

    source_layer = point_layer
    target_layer = polygon_layer

    if has_line_terms and has_polygon_terms and line_layer and polygon_layer:
        source_layer = line_layer
        target_layer = polygon_layer
    elif has_point_terms and has_polygon_terms and point_layer and polygon_layer:
        source_layer = point_layer
        target_layer = polygon_layer
    elif has_point_terms and has_line_terms:
        source_layer = point_layer or line_layer
        target_layer = line_layer or point_layer
    elif has_line_terms and line_layer:
        source_layer = line_layer
        target_layer = polygon_layer or point_layer
    elif has_polygon_terms and polygon_layer:
        source_layer = point_layer or line_layer
        target_layer = polygon_layer

    if source_layer and target_layer and source_layer == target_layer:
        target_layer = None

    return {
        "source_layer": source_layer,
        "target_layer": target_layer,
    }


def infer_query_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Intenta inferir la mejor capa para spatial.query_layer a partir del goal.
    Reglas:
    - si el goal parece hablar de puntos -> capa de puntos
    - si habla de zonas/polígonos -> capa poligonal
    - si habla de líneas/tramos -> capa lineal
    - si no hay pistas, prioriza punto, luego polígono, luego línea
    """
    goal = (goal or "").lower()

    point_terms = [
        "punto", "puntos", "point", "points", "nodo", "nodos",
        "cto", "cpe", "ont", "dispositivo", "dispositivos",
    ]
    polygon_terms = [
        "zona", "zonas", "area", "areas", "poligono", "polígonos",
        "polygon", "polygons", "sector", "sectores", "parcela", "parcelas",
    ]
    line_terms = [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos", "cable", "cables",
    ]

    if any(term in goal for term in point_terms):
        layer = find_best_point_layer(gis_layers_catalog)
        if layer:
            return layer

    if any(term in goal for term in polygon_terms):
        layer = find_best_polygon_layer(gis_layers_catalog)
        if layer:
            return layer

    if any(term in goal for term in line_terms):
        layer = find_best_line_layer(gis_layers_catalog)
        if layer:
            return layer

    # fallback general
    for finder in (find_best_point_layer, find_best_polygon_layer, find_best_line_layer):
        layer = finder(gis_layers_catalog)
        if layer:
            return layer

    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")

    return None
