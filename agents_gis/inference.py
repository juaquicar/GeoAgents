from typing import Any, Dict, List, Optional


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
    goal = (goal or "").lower()

    point_terms = [
        "punto", "puntos", "point", "points", "nodo", "nodos",
        "cto", "cpe", "ont", "dispositivo", "dispositivos",
    ]
    line_terms = [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos",
        "cable", "cables", "ruta", "rutas",
    ]
    polygon_terms = [
        "zona", "zonas", "area", "areas", "poligono", "polígono",
        "poligonos", "polígonos", "polygon", "polygons",
        "sector", "sectores", "parcela", "parcelas",
    ]

    if any(term in goal for term in point_terms):
        layer = find_best_point_layer(gis_layers_catalog)
        if layer:
            return layer

    if any(term in goal for term in line_terms):
        layer = find_best_line_layer(gis_layers_catalog)
        if layer:
            return layer

    if any(term in goal for term in polygon_terms):
        layer = find_best_polygon_layer(gis_layers_catalog)
        if layer:
            return layer

    for finder in (find_best_point_layer, find_best_line_layer, find_best_polygon_layer):
        layer = finder(gis_layers_catalog)
        if layer:
            return layer

    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")

    return None


def infer_intersection_layers(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    goal = (goal or "").lower()

    point_terms = [
        "punto", "puntos", "point", "points", "nodo", "nodos",
    ]
    line_terms = [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos", "cable", "cables",
    ]
    polygon_terms = [
        "zona", "zonas", "area", "areas", "poligono", "polígono",
        "polygon", "polygons", "sector", "sectores", "parcela", "parcelas",
    ]

    source_layer = None
    target_layer = None

    has_points = any(term in goal for term in point_terms)
    has_lines = any(term in goal for term in line_terms)
    has_polygons = any(term in goal for term in polygon_terms)

    if has_lines and has_polygons:
        source_layer = find_best_line_layer(gis_layers_catalog)
        target_layer = find_best_polygon_layer(gis_layers_catalog)
    elif has_points and has_lines:
        source_layer = find_best_point_layer(gis_layers_catalog)
        target_layer = find_best_line_layer(gis_layers_catalog)
    elif has_points and has_polygons:
        source_layer = find_best_point_layer(gis_layers_catalog)
        target_layer = find_best_polygon_layer(gis_layers_catalog)
    else:
        source_layer = find_best_point_layer(gis_layers_catalog)
        target_layer = find_best_polygon_layer(gis_layers_catalog)

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
    goal = (goal or "").lower()

    point_terms = [
        "punto", "puntos", "point", "points", "nodo", "nodos",
        "cto", "cpe", "ont", "dispositivo", "dispositivos",
    ]
    polygon_terms = [
        "zona", "zonas", "area", "areas", "poligono", "polígono",
        "poligonos", "polígonos", "polygon", "polygons",
        "sector", "sectores", "parcela", "parcelas",
    ]
    line_terms = [
        "linea", "línea", "lineas", "líneas", "line", "lines",
        "tramo", "tramos", "segmento", "segmentos",
        "cable", "cables", "ruta", "rutas",
        "red", "network",
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

    for finder in (find_best_point_layer, find_best_polygon_layer, find_best_line_layer):
        layer = finder(gis_layers_catalog)
        if layer:
            return layer

    if gis_layers_catalog:
        return gis_layers_catalog[0].get("name")

    return None


def infer_network_layer(
    goal: str,
    gis_layers_catalog: List[Dict[str, Any]],
) -> Optional[str]:
    goal = (goal or "").lower()

    network_terms = [
        "red", "network",
        "traza", "trace",
        "camino", "path",
        "ruta", "route",
        "conecta", "connect",
        "conectividad",
        "segmento", "segmentos",
        "tramo", "tramos",
        "linea", "lineas", "línea", "líneas",
        "cable", "cables",
    ]

    if any(term in goal for term in network_terms):
        layer = find_best_line_layer(gis_layers_catalog)
        if layer:
            return layer

    return find_best_line_layer(gis_layers_catalog)