"""
Ejemplos canónicos para el planner.

Estos ejemplos ilustran el ESTILO y ESTRUCTURA correcto de un plan,
no los nombres de capa reales (que provienen de gis_layers_catalog).
Los nombres de capa usados aquí ("demo_lines", "demo_points", "demo_polygons")
son placeholders genéricos — el planner debe sustituirlos por las capas
correctas de gis_layers_catalog según el dominio del agente.
"""

CANONICAL_PLANNER_EXAMPLES = [
    {
        "name": "canonical_simple_layer_query",
        "description": "Consulta básica de una capa dentro de un bbox: usa query_layer, NO context_pack",
        "input": {
            "goal": "Explora los elementos de esta zona",
            "map_context": {
                "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                "zoom": 18,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "demo_points",
                        "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                        "limit": 50,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existen elementos en la capa dentro del bbox consultado",
                    "verification_target": "Comprobar si la consulta devuelve al menos un elemento",
                    "success_criteria": {"path": "data.items", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_multi_tool_with_references",
        "description": "Plan de dos pasos: query_layer para localizar un elemento, luego nearby usando sus coordenadas",
        "input": {
            "goal": "Busca elementos cercanos al primer punto detectado dentro de esta zona",
            "map_context": {
                "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                "zoom": 18,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "demo_points",
                        "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                        "limit": 10,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existe al menos un elemento en la capa dentro del bbox",
                    "verification_target": "Comprobar si s1 devuelve al menos un elemento",
                    "success_criteria": {"path": "data.items", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.nearby",
                    "args": {
                        "layer": "demo_points",
                        "point": {
                            "lon": "$step:s1.data.items.0.lon",
                            "lat": "$step:s1.data.items.0.lat",
                        },
                        "radius_m": 100,
                        "limit": 10,
                    },
                    "required": True,
                    "depends_on": ["s1"],
                    "on_fail": "continue",
                    "hypothesis": "Hay elementos cercanos al primer elemento localizado en s1",
                    "verification_target": "Comprobar si s2 devuelve elementos cercanos",
                    "success_criteria": {"path": "data.items", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_refuted_hypothesis_with_replan",
        "description": "Plan con hipótesis verificable y can_replan=true: si falla, el planner replantea",
        "input": {
            "goal": "Comprueba si existe una ruta de red válida entre dos puntos y, si no existe, inspecciona la red disponible",
            "map_context": {
                "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                "zoom": 18,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": {"lon": -6.055, "lat": 37.325},
                        "end_point": {"lon": -6.056, "lat": 37.326},
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "continue",
                    "hypothesis": "Existe una ruta de red válida entre ambos puntos",
                    "verification_target": "Comprobar si path_found es true",
                    "success_criteria": {"path": "data.path_found", "equals": True},
                    "timeout_s": 0,
                    "max_retries": 1,
                    "retry_backoff_s": 0,
                    "can_replan": True,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_network_inventory_no_route",
        "description": "Inventario de red sin origen/destino: summary + query_layer. NO context_pack ni network_trace",
        "input": {
            "goal": "Hazme un inventario de los elementos de red de aquí",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.summary",
                    "args": {
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "continue",
                    "hypothesis": "Existen elementos de red en la zona consultada",
                    "verification_target": "Comprobar si hay capas con elementos",
                    "success_criteria": {"path": "data.layers", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "demo_lines",
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                        "limit": 50,
                    },
                    "required": False,
                    "depends_on": ["s1"],
                    "on_fail": "continue",
                    "hypothesis": "La capa de elementos lineales contiene geometrías en la zona",
                    "verification_target": "Comprobar si hay elementos en la capa de líneas",
                    "success_criteria": {"path": "data.items", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_spatial_inventory",
        "description": "Inventario espacial genérico: usa summary para recuento por capas. NO context_pack",
        "input": {
            "goal": "¿Cuántos elementos hay en esta zona? Muestra su distribución por capa",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.summary",
                    "args": {
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Hay elementos espaciales en la zona",
                    "verification_target": "Comprobar si el resumen devuelve capas con elementos",
                    "success_criteria": {"path": "data.layers", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_layer_field_query",
        "description": "Consulta de elementos de una capa concreta con sus campos: usa query_layer. NO context_pack",
        "input": {
            "goal": "Lista los elementos de la capa de líneas de esta zona con su tipo y categoría",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "demo_lines",
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                        "limit": 50,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existen elementos en la capa de líneas dentro del bbox",
                    "verification_target": "Comprobar si la consulta devuelve elementos",
                    "success_criteria": {"path": "data.items", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_aggregate_count_by_field",
        "description": "Recuento agrupado por campo: usa spatial.aggregate. NO query_layer ni context_pack",
        "input": {
            "goal": "¿Cuántos elementos hay por categoría? ¿Qué tipo predomina?",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.aggregate",
                    "args": {
                        "layer": "demo_lines",
                        "group_by": ["category_n", "type_name"],
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                        "order_by": "count_desc",
                        "limit": 50,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existen elementos agrupables por categoría y tipo en la zona",
                    "verification_target": "Comprobar si el agregado devuelve grupos",
                    "success_criteria": {"path": "data.groups", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_aggregate_sum_field",
        "description": "Suma de campo numérico agrupado: usa spatial.aggregate con aggs",
        "input": {
            "goal": "¿Cuál es la longitud total por tipo de elemento en esta zona?",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.aggregate",
                    "args": {
                        "layer": "demo_lines",
                        "group_by": ["type_name"],
                        "aggs": [
                            {"field": "length_m", "func": "sum", "alias": "longitud_total"},
                            {"field": "length_m", "func": "avg", "alias": "longitud_media"},
                        ],
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                        "order_by": "count_desc",
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "La capa tiene elementos con tipo y longitud agrupables",
                    "verification_target": "Comprobar si el agregado devuelve grupos con totales",
                    "success_criteria": {"path": "data.groups", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_buffer_from_element",
        "description": "Buffer alrededor de un elemento de capa: usa spatial.buffer con source_layer+source_id",
        "input": {
            "goal": "¿Qué puntos hay a menos de 100 metros del elemento 5 de la capa de líneas?",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.buffer",
                    "args": {
                        "target_layer": "demo_points",
                        "buffer_m": 100,
                        "source_layer": "demo_lines",
                        "source_id": 5,
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existen puntos dentro del área de influencia del elemento 5",
                    "verification_target": "Comprobar si el buffer devuelve elementos",
                    "success_criteria": {"path": "data.count_total", "gt": 0},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "canonical_true_generic_overview",
        "description": "Overview genuinamente genérico sin capa ni operación mencionada: aquí SÍ se usa context_pack",
        "input": {
            "goal": "¿Qué hay en esta zona?",
            "map_context": {
                "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                "zoom": 17,
            },
        },
        "output": {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.context_pack",
                    "args": {
                        "bbox": {"west": -6.008, "south": 37.377, "east": -5.999, "north": 37.386},
                        "zoom": 17,
                        "profile": "compact",
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Hay elementos espaciales en la zona",
                    "verification_target": "Comprobar si el contexto contiene capas",
                    "success_criteria": {"path": "data.layers", "non_empty": True},
                    "timeout_s": 0,
                    "max_retries": 0,
                    "retry_backoff_s": 0,
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        },
    },
]
