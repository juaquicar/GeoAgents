"""
Selección heurística de herramientas GIS a partir del goal en lenguaje natural.

Estrategia de scoring:
- Cada tool tiene una lista de (keyword_fragment, weight).
- Se normaliza el goal y se suman los pesos de todos los fragmentos que aparecen.
- Se devuelven las tools ordenadas por puntuación descendente (sólo las que puntúan > 0).
- Las frases multi-palabra reciben mayor peso que los tokens simples.
"""
from typing import Dict, List, Sequence, Tuple

from .text import normalize_goal


# ---------------------------------------------------------------------------
# Reglas de keyword → peso por tool
# Peso 1 = señal débil/genérica  |  2 = señal media  |  3 = señal fuerte/específica
# Las frases de más de una palabra siempre pesan ≥ 2 porque son más discriminativas.
# ---------------------------------------------------------------------------
_TOOL_KEYWORDS: Dict[str, List[Tuple[str, int]]] = {

    # ── Red / topología ────────────────────────────────────────────────────
    "spatial.network_trace": [
        ("traza", 2), ("trace", 2),
        ("camino de red", 3), ("conexion de red", 3),
        ("recorre la red", 3), ("siguiendo la red", 3),
        ("ruta de red", 3), ("camino topolog", 3),
        ("conectividad", 2), ("grafo", 2),
        ("propaga", 2), ("flujo de red", 3),
        ("red desde", 2), ("conecta con", 2),
        ("conecta a", 2),
        # "ruta" y "camino" solos pesan poco para no colisionar con route_cost
        ("ruta", 1), ("camino", 1),
    ],

    "spatial.route_cost": [
        ("coste", 2), ("costo", 2),
        ("penaliz", 2), ("restric", 2),
        ("ruta optima", 3), ("ruta minima", 3),
        ("menor coste", 3), ("camino optimo", 3),
        ("evitar tramo", 3), ("ruta evit", 2),
        ("ruta con coste", 3), ("peso de red", 3),
        ("ponderado", 2), ("con restriccion", 3),
        ("segmento prohibido", 3), ("tramo prohibido", 3),
    ],

    "spatial.network_service_area": [
        ("area de servicio", 3), ("service area", 3),
        ("isocron", 3), ("area alcanzable", 3),
        ("zona alcanzable", 3), ("hasta donde llega", 3),
        ("cuanto se puede alcanzar", 3), ("desde un punto hasta", 2),
        ("cobertura de red", 3), ("alcanzable por red", 3),
        ("alcanzable", 2), ("servicio", 1),
    ],

    # ── Relaciones espaciales entre capas ─────────────────────────────────
    "spatial.intersects": [
        ("interse", 2), ("solap", 2),
        ("cruce", 1), ("contiene", 1),
        ("donde se cruzan", 3), ("que cruzan", 2),
        ("que intersectan", 3), ("que se solapan", 3),
        ("que caen en", 2), ("que coinciden con", 2),
        ("superpone con", 2), ("dentro de la zona", 2),
    ],

    "spatial.overlay": [
        ("superposicion", 3), ("overlay", 3),
        ("zona comun entre", 3), ("zona comun de", 3),
        ("interseccion de capas", 3), ("union de capas", 3),
        ("diferencia de capas", 3), ("combina capas", 3),
        ("superpone capas", 3), ("une capas", 2),
        ("superpone", 2),
    ],

    "spatial.spatial_join": [
        ("adjunta", 2), ("enriquece", 2),
        ("añade atributo", 3), ("incorpora datos de", 3),
        ("en que zona", 3), ("en que barrio", 3),
        ("a que barrio", 3), ("a que zona", 3),
        ("pertenece a", 3), ("asigna zona", 3),
        ("a que pertenece", 3), ("join espacial", 3),
        ("atributo de la zona", 3),
    ],

    # ── Proximidad / distancia ────────────────────────────────────────────
    "spatial.nearby": [
        ("cerca", 2), ("proxim", 2),
        ("nearby", 3), ("alrededor de", 2),
        ("en torno a", 2), ("junto a", 2),
        ("junto al", 2), ("puntos cercanos", 3),
        ("elementos cercanos", 3), ("busca cerca", 2),
        ("entorno de", 2), ("adyacente", 1),
    ],

    "spatial.within_distance": [
        ("a menos de", 3), ("dentro de un radio", 3),
        ("en un radio de", 3), ("a distancia de", 3),
        ("within distance", 3), ("cerca de otra capa", 3),
        ("metros de otra", 2), ("a x metros", 2),
        ("en el radio de", 3), ("a menos de x", 3),
        ("elementos a ", 2), ("features a ", 2),
    ],

    "spatial.nearest_neighbor": [
        ("mas cercano", 3), ("mas cercana", 3),
        ("mas proximo", 3), ("mas proxima", 3),
        ("vecino mas", 3), ("vecino cercano", 3),
        ("nearest neighbor", 3), ("nearest neighbour", 3),
        ("feature mas cercano", 3), ("feature mas cercana", 3),
        ("punto mas proximo", 3), ("punto mas cercano", 3),
        ("asigna el mas cercano", 3), ("parea con", 2),
        ("enlaza con el mas cercano", 3),
        ("cual es la", 1),  # "¿cuál es la farola más cercana?"
    ],

    "spatial.buffer": [
        ("buffer", 3), ("zona de influencia de metros", 3),
        ("area de influencia de metros", 3),
        ("ampliar geomet", 2), ("expandir geomet", 2),
        ("expandir poligon", 2), ("offset de", 2),
        ("radio de metros", 2), ("a metros de", 2),
        ("radio", 2),  # "en un radio de 100 metros"
    ],

    # ── Análisis de clustering / densidad ────────────────────────────────
    "spatial.cluster_dbscan": [
        ("cluster", 3), ("agrupacion", 2),
        ("concentracion", 2), ("foco", 2),
        ("hotspot", 3), ("donde se concentran", 3),
        ("zonas de alta", 2), ("puntos agrupados", 3),
        ("grupos de", 2), ("patron espacial", 2),
        ("nucleos de", 2), ("aglomeracion", 2),
        ("densidad de", 2), ("concentran los", 2),
    ],

    "spatial.grid_stats": [
        ("cuadricula", 3), ("grid", 2),
        ("densidad espacial", 3), ("mapa de calor", 3),
        ("heatmap", 3), ("distribucion espacial", 3),
        ("rejilla", 3), ("celda", 2),
        ("calor espacial", 3),
    ],

    # ── Estadística / agregación ──────────────────────────────────────────
    "spatial.aggregate": [
        ("por categoria", 3), ("por tipo", 2),
        ("predomina", 2), ("agrup", 2),
        ("suma de", 2), ("total de", 2),
        ("promedio", 2), ("estadistic", 2),
        ("distribucion de", 2), ("recuento por", 3),
        ("media de", 2), ("cuantos hay", 2),
    ],

    "spatial.count_within": [
        ("cuantos hay en", 3), ("cuantos por", 3),
        ("por zona", 2), ("por parcela", 2),
        ("por rodal", 2), ("contenidos en", 3),
        ("dentro de cada", 3), ("contar dentro", 3),
        ("numero de por", 2), ("cuantos elementos", 2),
        ("conteo por", 3), ("cuenta por", 3),
    ],

    # ── Consulta / inventario ─────────────────────────────────────────────
    "spatial.query_layer": [
        ("inventario", 2), ("lista", 1),
        ("listar", 2), ("tipos de", 1),
        ("que campos", 3), ("que atributos", 3),
        ("muestra los", 2), ("consulta la capa", 3),
        ("dame los", 1), ("obten los", 2),
        ("registros de", 2), ("detalle de", 2),
        ("elementos de la capa", 3),
    ],

    "spatial.summary": [
        ("resumen", 1), ("summary", 2),
        ("estadisticas de capas", 3), ("capas disponibles", 3),
        ("que capas hay", 3), ("cuantos registros tiene", 3),
        ("describe la capa", 3), ("info de capa", 2),
    ],

    "spatial.context_pack": [
        ("contexto espacial", 3), ("entorno", 2),
        ("overview", 3), ("que hay en", 2),
        ("resumen general", 3), ("descripcion general", 3),
        ("que existe en", 3), ("que contiene esta zona", 3),
        ("vision general", 3), ("analisis general", 2),
    ],

    # ── Operaciones geométricas ───────────────────────────────────────────
    "spatial.dissolve": [
        ("fusiona", 3), ("fusionar", 3),
        ("disuelve", 3), ("disolver", 3),
        ("dissolve", 3), ("une las", 2),
        ("combina geomet", 3), ("merge geomet", 3),
        ("agrega geomet", 3), ("unir poligonos", 3),
        ("unir por campo", 3),
    ],

    "spatial.centroid": [
        ("centroide", 3), ("centroid", 3),
        ("punto central", 3), ("coordenadas central", 3),
        ("punto representativo", 3), ("representativ", 2),
        ("centro de cada", 3), ("centro del poligon", 3),
    ],

    "spatial.convex_hull": [
        ("envolvente", 3), ("convex hull", 3),
        ("casco convexo", 3), ("hull", 2),
        ("contorno que envuelve", 3), ("extension de", 2),
        ("area que ocupa", 3), ("perimetro externo", 3),
        ("forma que engloba", 3),
    ],

    "spatial.voronoi": [
        ("voronoi", 3), ("thiessen", 3),
        ("diagrama de voronoi", 3), ("region mas cercana", 3),
        ("zona de influencia", 3), ("zonas de influencia", 3),
        ("area de influencia", 3), ("areas de influencia", 3),
        ("zona de cobertura", 3), ("zonas de cobertura", 3),
        ("tesela", 3), ("teselacion", 3),
    ],

    "spatial.measure": [
        ("longitud total", 3), ("area total", 3),
        ("perimetro", 3), ("cuantos metros", 3),
        ("longitud media", 3), ("superficie total", 3),
        ("metros lineales", 3), ("km de red", 3),
        ("extension total", 3), ("metros de red", 3),
        ("calcular longitud", 3), ("calcular area", 3),
        ("calcular superficie", 3), ("mide la", 2),
        ("cuanto mide", 3), ("cuanto ocupa", 2),
    ],

    "spatial.difference": [
        ("area libre", 3), ("zona libre", 3),
        ("no cubierto", 3), ("diferencia geomet", 3),
        ("resta geomet", 3), ("suelo disponible", 3),
        ("espacio disponible", 2), ("hueco", 2),
        ("lo que no esta", 3), ("zona sin cobertura", 3),
        ("area sin", 2),
    ],

    # ── Calidad / validación ──────────────────────────────────────────────
    "spatial.topology_check": [
        ("topolog", 2), ("invalida", 2),
        ("geometria invalida", 3), ("geometrias invalidas", 3),
        ("solapamiento", 3), ("solapamientos", 3),
        ("integridad", 2), ("integridad geomet", 3), ("validez", 2),
        ("errores geomet", 3), ("geometrias rotas", 3),
        ("inconsistencia geomet", 3), ("duplicados geomet", 3),
        ("calidad geomet", 3), ("invalidas", 2),
    ],
}

# ---------------------------------------------------------------------------
# Fallback genérico cuando no hay score suficiente
# ---------------------------------------------------------------------------
_DEFAULT_TOOL = "spatial.query_layer"

# Umbral mínimo de score para incluir una tool en los resultados
_MIN_SCORE = 1


def select_initial_tools(goal: str, allowlist: Sequence[str] | None = None) -> List[str]:
    normalized = normalize_goal(goal)
    scores: Dict[str, int] = {}

    for tool, rules in _TOOL_KEYWORDS.items():
        score = 0
        for keyword, weight in rules:
            if keyword in normalized:
                score += weight
        if score >= _MIN_SCORE:
            scores[tool] = score

    # Ordenar por puntuación descendente
    ranked = sorted(scores.keys(), key=lambda t: scores[t], reverse=True)

    if not ranked:
        ranked = [_DEFAULT_TOOL]

    # Eliminar duplicados (no debería haberlos, pero por seguridad)
    seen: set = set()
    deduped: List[str] = []
    for item in ranked:
        if item not in seen:
            deduped.append(item)
            seen.add(item)

    if allowlist:
        filtered = [t for t in deduped if t in allowlist]
        if not filtered:
            # Si ninguna tool sugerida está en la allowlist, devolver la primera de la allowlist
            filtered = list(allowlist)[:1]
        return filtered

    return deduped
