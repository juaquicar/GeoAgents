from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from agents_core.models import Agent, Run
from agents_core.runner import execute_run


class PlannerExecutionControlTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="secret123",
        )
        self.agent = Agent.objects.create(
            name="exec-control-agent",
            profile="investigate",
            tool_allowlist=["spatial.query_layer", "spatial.nearby"],
        )

    @patch("agents_core.runner.synthesize_run", return_value="ok")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_references_and_dependencies_are_resolved(self, mock_plan_run, mock_invoke_tool, _mock_synthesize):
        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points", "limit": 1},
                    "required": True,
                    "hypothesis": "Existe al menos un punto en la capa",
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.nearby",
                    "depends_on": ["s1"],
                    "args": {
                        "layer": "demo_points",
                        "point": "$step:s1.data.features.0.centroid",
                        "radius_m": 100,
                    },
                    "required": False,
                    "on_fail": "continue",
                },
                {"type": "final"},
            ]
        }

        class ToolRes:
            def __init__(self, ok, data=None, error=""):
                self.ok = ok
                self.data = data or {}
                self.error = error

        mock_invoke_tool.side_effect = [
            (ToolRes(True, data={"features": [{"centroid": {"lon": 1.2, "lat": 3.4}}]}), 10),
            (ToolRes(True, data={"features": []}), 12),
        ]

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "analiza puntos cercanos"},
        )

        run = execute_run(run)

        self.assertEqual(run.status, "succeeded")
        outputs = run.output_json["executed_outputs"]
        self.assertEqual(outputs[0]["id"], "s1")
        self.assertEqual(outputs[1]["depends_on"], ["s1"])
        self.assertEqual(outputs[1]["resolved_args"]["point"], {"lon": 1.2, "lat": 3.4})

    @patch("agents_core.runner.synthesize_run", return_value="ok")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_on_fail_continue_does_not_abort(self, mock_plan_run, mock_invoke_tool, _mock_synthesize):
        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points"},
                    "required": False,
                    "on_fail": "continue",
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.nearby",
                    "args": {"layer": "demo_points", "point": {"lon": 0, "lat": 0}},
                    "required": True,
                },
                {"type": "final"},
            ]
        }

        class ToolRes:
            def __init__(self, ok, data=None, error=""):
                self.ok = ok
                self.data = data or {}
                self.error = error

        mock_invoke_tool.side_effect = [
            (ToolRes(False, error="temporary failure"), 5),
            (ToolRes(True, data={"features": []}), 8),
        ]

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "consulta"},
        )

        run = execute_run(run)
        self.assertEqual(run.status, "succeeded")
        outputs = run.output_json["executed_outputs"]
        self.assertFalse(outputs[0]["ok"])
        self.assertEqual(outputs[0]["on_fail"], "continue")
        self.assertTrue(outputs[1]["ok"])
