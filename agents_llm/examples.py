PLANNER_EXAMPLES = [
    {
        "name": "general_spatial_summary",
        "input": {
            "goal": "Analiza espacialmente esta zona y resume los elementos detectados",
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
                    "type": "tool",
                    "name": "spatial.context_pack",
                    "args": {
                        "bbox": {
                            "west": -6.06,
                            "south": 37.32,
                            "east": -6.05,
                            "north": 37.33,
                        },
                        "zoom": 18,
                        "profile": "compact",
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "nearby_analysis",
        "input": {
            "goal": "Dime qué puntos hay cerca del centro de esta zona",
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
                    "type": "tool",
                    "name": "spatial.nearby",
                    "args": {
                        "layer": "demo_points",
                        "point": {"lon": -6.055, "lat": 37.325},
                        "radius_m": 250,
                        "limit": 10,
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "intersection_check",
        "input": {
            "goal": "Comprueba si los puntos caen dentro de polígonos en esta zona",
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
                    "type": "tool",
                    "name": "spatial.intersects",
                    "args": {
                        "source_layer": "demo_points",
                        "target_layer": "demo_polygons",
                        "bbox": {
                            "west": -6.06,
                            "south": 37.32,
                            "east": -6.05,
                            "north": 37.33,
                        },
                        "limit": 20,
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        },
    },
    {
        "name": "query_specific_layer",
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
                },
                {"type": "final"},
            ]
        },
    },
]