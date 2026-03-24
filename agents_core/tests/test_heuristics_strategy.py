from django.test import SimpleTestCase

from agents_core.heuristics import (
    classify_goal_domain,
    infer_analysis_types,
    infer_layers,
    tool_sequence_signature,
)


class HeuristicsClassificationTests(SimpleTestCase):
    def test_classify_goal_domain_network(self):
        self.assertEqual(classify_goal_domain("Traza una ruta de red"), "network")

    def test_infer_analysis_types_from_goal_and_plan(self):
        plan = {
            "steps": [
                {
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "success_criteria": {"path": "data.path_found", "equals": True},
                    "can_replan": True,
                }
            ]
        }
        result = infer_analysis_types("Traza una ruta", plan, ["spatial.network_trace"])
        self.assertIn("network_trace", result)
        self.assertIn("verification_driven", result)
        self.assertIn("replanning", result)

    def test_infer_layers_from_plan_and_outputs(self):
        plan = {
            "steps": [
                {"type": "tool", "args": {"layer": "demo_lines"}}
            ]
        }
        outputs = [
            {"resolved_args": {"source_layer": "demo_points"}, "data": {"target_layer": "demo_polygons"}}
        ]
        layers = infer_layers(plan, outputs)
        self.assertEqual(set(layers), {"demo_lines", "demo_points", "demo_polygons"})

    def test_tool_sequence_signature(self):
        self.assertEqual(
            tool_sequence_signature(["spatial.query_layer", "spatial.nearby"]),
            "spatial.query_layer>spatial.nearby"
        )