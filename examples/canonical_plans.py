CANONICAL_PLANNER_EXAMPLES = [
    {
        "name": "canonical_simple_layer_query",
        "input": {
            "goal": "Explora la capa de puntos dentro de esta zona",
            "map_context": {
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
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
                        "bbox": {
                            "west": -6.06,
                            "south": 37.32,
                            "east": -6.05,
                            "north": 37.33,
                        },
                        "limit": 50,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "La capa demo_points contiene elementos dentro del bbox consultado",
                    "verification_target": "Comprobar si la consulta devuelve al menos un elemento",
                    "success_criteria": {
                        "path": "data.features",
                        "non_empty": True,
                    },
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
        "input": {
            "goal": "Busca elementos cercanos al primer punto detectado dentro de esta zona",
            "map_context": {
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
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
                        "bbox": {
                            "west": -6.06,
                            "south": 37.32,
                            "east": -6.05,
                            "north": 37.33,
                        },
                        "limit": 10,
                    },
                    "required": True,
                    "depends_on": [],
                    "on_fail": "abort",
                    "hypothesis": "Existe al menos un punto en la capa demo_points dentro del bbox",
                    "verification_target": "Comprobar si s1 devuelve al menos una feature",
                    "success_criteria": {
                        "path": "data.features",
                        "non_empty": True,
                    },
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
                        "point": "$step:s1.data.features.0.centroid",
                        "radius_m": 100,
                        "limit": 10,
                    },
                    "required": True,
                    "depends_on": ["s1"],
                    "on_fail": "continue",
                    "hypothesis": "Hay elementos cercanos al primer punto detectado en s1",
                    "verification_target": "Comprobar si s2 devuelve elementos cercanos",
                    "success_criteria": {
                        "path": "data.features",
                        "non_empty": True,
                    },
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
        "input": {
            "goal": "Comprueba si existe una ruta de red válida entre dos puntos y, si no existe, inspecciona la red disponible en la zona",
            "map_context": {
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
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
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                    "timeout_s": 0,
                    "max_retries": 1,
                    "retry_backoff_s": 0,
                    "can_replan": True,
                },
                {"type": "final"},
            ]
        },
    },
]