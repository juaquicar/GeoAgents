from django.test import SimpleTestCase

from agents_llm.synthesizer import extract_structured_facts


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
                        {
                            "source_name": "A",
                            "target_name": "Zona 1",
                            "intersection_geom_type": "POINT",
                        },
                        {
                            "source_name": "B",
                            "target_name": "Zona 1",
                            "intersection_geom_type": "POINT",
                        },
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
                        {"id": 1, "name": "A", "geometry_type": "POINT"},
                        {"id": 2, "name": "B", "geometry_type": "POINT"},
                    ],
                },
            }
        ]

        facts = extract_structured_facts(executed_outputs)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["tool"], "spatial.query_layer")
        self.assertEqual(facts[0]["total_features"], 2)
        self.assertEqual(len(facts[0]["sample"]), 2)