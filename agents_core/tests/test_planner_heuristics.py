from django.test import TestCase
from django.contrib.auth import get_user_model

from agents_core.models import Agent, Run
from agents_core.heuristics import build_planner_heuristics


class PlannerHeuristicsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u1", password="x")
        self.agent = Agent.objects.create(
            name="a1",
            system_prompt="",
            is_active=True,
            profile="investigate",
            tool_allowlist=["spatial.network_trace", "spatial.query_layer", "spatial.context_pack"],
        )
        self.run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="queued",
            input_json={},
        )

    def test_build_planner_heuristics(self):
        payload = {"goal": "Traza una ruta de red entre dos puntos"}
        result = build_planner_heuristics(self.run, payload)

        self.assertEqual(result["domain"], "network")
        self.assertIn("spatial.network_trace", result["initial_tools"])
        self.assertIn("fallback_tools", result)
        self.assertIn("goal_signature", result)