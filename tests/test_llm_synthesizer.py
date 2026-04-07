"""
Tests del sintetizador LLM: extracción de hechos estructurados desde outputs de tools.

Ejecutar:
    python manage.py test tests.test_llm_synthesizer
"""
from django.test import SimpleTestCase

from agents_llm.synthesizer import (
    extract_structured_facts,
    build_tool_facts,
)


class SynthesizerFactsExtractionTests(SimpleTestCase):
    def test_extracts_intersection_facts_without_claiming_containment(self):
        executed_outputs = [
            {
                "type": "tool",
                "ok": True,
                "name": "spatial.intersects",
                "data": {
                    "count_total": 2,
                    "source_layer": "demo_points",
                    "target_layer": "demo_polygons",
                    "items": [
                        {"source_name": "A", "target_name": "Zona 1", "intersection_geom_type": "POINT"},
                        {"source_name": "B", "target_name": "Zona 1", "intersection_geom_type": "POINT"},
                    ],
                },
            }
        ]
        facts = extract_structured_facts(executed_outputs)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["tool"], "spatial.intersects")
        self.assertEqual(facts[0]["total_matches"], 2)
        self.assertTrue(facts[0]["supports_intersection"])
        self.assertFalse(facts[0]["supports_containment"])

    def test_extracts_network_trace_failure_facts(self):
        executed_outputs = [
            {
                "type": "tool",
                "ok": True,
                "name": "spatial.network_trace",
                "data": {
                    "path_found": False,
                    "reason": "no_valid_network_nodes",
                    "node_count": 0,
                    "segments": [],
                },
            }
        ]
        facts = extract_structured_facts(executed_outputs)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["tool"], "spatial.network_trace")
        self.assertFalse(facts[0]["path_found"])
        self.assertEqual(facts[0]["reason"], "no_valid_network_nodes")
        self.assertEqual(facts[0]["node_count"], 0)

    def test_extracts_query_layer_counts(self):
        executed_outputs = [
            {
                "type": "tool",
                "ok": True,
                "name": "spatial.query_layer",
                "data": {
                    "count_total": 2,
                    "layer": "demo_points",
                    "items": [
                        {"id": 1, "name": "A", "geom_type": "POINT", "lon": -6.0, "lat": 37.0},
                        {"id": 2, "name": "B", "geom_type": "POINT", "lon": -6.001, "lat": 37.001},
                    ],
                },
            }
        ]
        facts = extract_structured_facts(executed_outputs)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["tool"], "spatial.query_layer")
        self.assertEqual(facts[0]["total_features"], 2)
        self.assertEqual(len(facts[0]["sample"]), 2)
        # lon/lat deben aparecer en la muestra (no centroid anidado)
        self.assertEqual(facts[0]["sample"][0]["lon"], -6.0)
        self.assertEqual(facts[0]["sample"][0]["lat"], 37.0)

    def test_query_layer_facts_text_uses_lon_lat(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.query_layer",
            "data": {
                "count_total": 1,
                "layer": "tramos",
                "items": [
                    {"id": 5, "name": "tramo_5", "geom_type": "LINESTRING",
                     "lon": -6.055, "lat": 37.321, "length_m": 123.4},
                ],
            },
        }
        facts = build_tool_facts([step])
        combined = " ".join(facts)
        self.assertIn("tramo_5", combined)
        self.assertIn("123", combined)

    def test_extracts_nearby_with_closest(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.nearby",
            "data": {
                "layer": "struct",
                "point": {"lon": -6.0, "lat": 37.0},
                "radius_m": 100,
                "count_total": 2,
                "items": [
                    {"id": 1, "name": "Cabinet-1", "distance_m": 12.3, "geom_type": "POINT"},
                    {"id": 2, "name": "Cabinet-2", "distance_m": 45.6, "geom_type": "POINT"},
                ],
            },
        }
        facts = extract_structured_facts([step])
        self.assertEqual(facts[0]["tool"], "spatial.nearby")
        self.assertEqual(facts[0]["closest"]["name"], "Cabinet-1")
        self.assertAlmostEqual(facts[0]["closest"]["distance_m"], 12.3)
        self.assertEqual(facts[0]["radius_m"], 100)

        text_facts = build_tool_facts([step])
        combined = " ".join(text_facts)
        self.assertIn("Cabinet-1", combined)
        self.assertIn("12.3", combined)

    def test_extracts_aggregate_facts(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.aggregate",
            "data": {
                "layer": "span",
                "group_by": ["category_n"],
                "aggs": [],
                "total_groups": 3,
                "groups": [
                    {"category_n": "Fiber", "count": 120},
                    {"category_n": "Duct", "count": 45},
                    {"category_n": "Copper", "count": 8},
                ],
            },
        }
        facts = extract_structured_facts([step])
        self.assertEqual(facts[0]["tool"], "spatial.aggregate")
        self.assertEqual(facts[0]["total_groups"], 3)
        self.assertEqual(facts[0]["top_group"]["category_n"], "Fiber")
        self.assertEqual(facts[0]["top_group"]["count"], 120)

        text_facts = build_tool_facts([step])
        combined = " ".join(text_facts)
        self.assertIn("span", combined)
        self.assertIn("3", combined)
        self.assertIn("Fiber", combined)

    def test_extracts_buffer_facts(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.buffer",
            "data": {
                "target_layer": "struct",
                "buffer_m": 50.0,
                "source": {"type": "point", "lon": -6.0, "lat": 37.0},
                "count_total": 2,
                "items": [
                    {"id": 1, "name": "Junction-A", "distance_m": 10.5},
                    {"id": 2, "name": "Cabinet-B", "distance_m": 38.2},
                ],
            },
        }
        facts = extract_structured_facts([step])
        self.assertEqual(facts[0]["tool"], "spatial.buffer")
        self.assertEqual(facts[0]["count_total"], 2)
        self.assertEqual(facts[0]["buffer_m"], 50.0)
        self.assertEqual(facts[0]["closest"]["name"], "Junction-A")

        text_facts = build_tool_facts([step])
        combined = " ".join(text_facts)
        self.assertIn("struct", combined)
        self.assertIn("50", combined)
        self.assertIn("Junction-A", combined)

    def test_extracts_route_cost_facts_success(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.route_cost",
            "data": {
                "layer": "span",
                "metric": "cost",
                "path_found": True,
                "total_cost": 2.345,
                "total_length_m": 412.0,
                "segment_ids": [1, 2, 3],
                "start_snap_m": 5.0,
                "end_snap_m": 8.0,
            },
        }
        facts = extract_structured_facts([step])
        self.assertEqual(facts[0]["tool"], "spatial.route_cost")
        self.assertTrue(facts[0]["path_found"])
        self.assertAlmostEqual(facts[0]["total_cost"], 2.345)
        self.assertEqual(facts[0]["segment_count"], 3)

        text_facts = build_tool_facts([step])
        combined = " ".join(text_facts)
        self.assertIn("2.3450", combined)
        self.assertIn("412", combined)
        self.assertIn("3 segmentos", combined)

    def test_extracts_route_cost_facts_failure(self):
        step = {
            "type": "tool",
            "ok": True,
            "name": "spatial.route_cost",
            "data": {
                "layer": "span",
                "metric": "cost",
                "path_found": False,
                "reason": "no_path",
            },
        }
        facts = extract_structured_facts([step])
        self.assertFalse(facts[0]["path_found"])
        self.assertEqual(facts[0]["reason"], "no_path")

        text_facts = build_tool_facts([step])
        combined = " ".join(text_facts)
        self.assertIn("no encontró ruta", combined)
        self.assertIn("no_path", combined)

    def test_failed_step_produces_error_fact(self):
        step = {
            "type": "tool",
            "ok": False,
            "name": "spatial.aggregate",
            "error": "group_by field not allowed: secret",
        }
        text_facts = build_tool_facts([step])
        self.assertEqual(len(text_facts), 1)
        self.assertIn("falló", text_facts[0])
        self.assertIn("secret", text_facts[0])

    def test_non_tool_steps_are_ignored(self):
        steps = [
            {"type": "final"},
            {"type": "system", "ok": True, "name": "run.start", "data": {}},
        ]
        self.assertEqual(extract_structured_facts(steps), [])
        self.assertEqual(build_tool_facts(steps), [])
