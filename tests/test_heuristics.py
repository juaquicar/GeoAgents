"""
Tests de heurísticas de planificación: clasificación de dominio, selección de tools,
normalización de texto y construcción de plan context.

Ejecutar:
    python manage.py test tests.test_heuristics
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from agents_core.heuristics import (
    build_goal_signature,
    build_planner_heuristics,
    classify_goal_domain,
    infer_analysis_types,
    infer_layers,
    normalize_goal,
    select_fallback_tools,
    select_initial_tools,
    tool_sequence_signature,
)
from agents_core.models import Agent, Run


# ── Clasificación y análisis ─────────────────────────────────────────────────

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
        plan = {"steps": [{"type": "tool", "args": {"layer": "demo_lines"}}]}
        outputs = [
            {"resolved_args": {"source_layer": "demo_points"}, "data": {"target_layer": "demo_polygons"}}
        ]
        layers = infer_layers(plan, outputs)
        self.assertEqual(set(layers), {"demo_lines", "demo_points", "demo_polygons"})

    def test_tool_sequence_signature(self):
        self.assertEqual(
            tool_sequence_signature(["spatial.query_layer", "spatial.nearby"]),
            "spatial.query_layer>spatial.nearby",
        )


# ── Texto y normalización ────────────────────────────────────────────────────

class HeuristicsTextTests(SimpleTestCase):
    def test_normalize_goal_removes_accents(self):
        self.assertEqual(normalize_goal("Trázame una ruta"), "trazame una ruta")

    def test_build_goal_signature_uses_keywords(self):
        signature = build_goal_signature("Traza una ruta de red entre dos puntos")
        self.assertIn("traza", signature)
        self.assertIn("ruta", signature)


# ── Selección de herramientas ────────────────────────────────────────────────

class HeuristicsSelectionTests(SimpleTestCase):
    def test_select_initial_tools_network(self):
        tools = select_initial_tools("Traza una ruta de red")
        self.assertEqual(tools[0], "spatial.network_trace")

    def test_select_initial_tools_nearby(self):
        tools = select_initial_tools("Busca puntos cercanos")
        self.assertIn("spatial.nearby", tools)

    def test_select_initial_tools_respects_allowlist(self):
        tools = select_initial_tools("Traza una ruta de red", allowlist=["spatial.query_layer"])
        self.assertEqual(tools, ["spatial.query_layer"])

    def test_select_fallback_tools_for_network_trace(self):
        tools = select_fallback_tools("Traza una ruta de red", failed_tool="spatial.network_trace")
        self.assertIn("spatial.query_layer", tools)

    def test_select_initial_tools_route_cost(self):
        tools = select_initial_tools("Optimiza la ruta con coste y penalizaciones")
        self.assertIn("spatial.route_cost", tools)

    def test_select_initial_tools_service_area(self):
        tools = select_initial_tools("Calcula la cobertura de servicio alcanzable en red")
        self.assertIn("spatial.network_service_area", tools)


# ── Planner heuristics integrado ─────────────────────────────────────────────

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
