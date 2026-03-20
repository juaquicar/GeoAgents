from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from agents_core.models import Agent, Run
from agents_core.runner import execute_run
from agents_llm.planner import plan_run, validate_plan


def _tool_ok(data):
    return SimpleNamespace(ok=True, data=data, error="")


def _tool_fail(error):
    return SimpleNamespace(ok=False, data={}, error=error)


class PlannerGISNormalizationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="planner_tester",
            email="planner_tester@example.com",
            password="secret123",
        )
        self.agent = Agent.objects.create(
            name="planner-gis-agent",
            profile="rich",
            tool_allowlist=[
                "spatial.query_layer",
                "spatial.intersects",
                "spatial.network_trace",
            ],
        )

        self.catalog = [
            {
                "name": "demo_points",
                "table": "demo_points",
                "geom_col": "the_geom",
                "id_col": "id",
                "fields": ["name"],
                "filter_fields": ["name"],
                "geometry_kind": "point",
            },
            {
                "name": "demo_lines",
                "table": "demo_lines",
                "geom_col": "the_geom",
                "id_col": "id",
                "fields": ["name"],
                "filter_fields": ["name"],
                "geometry_kind": "line",
            },
            {
                "name": "demo_polygons",
                "table": "demo_polygons",
                "geom_col": "the_geom",
                "id_col": "id",
                "fields": ["name"],
                "filter_fields": ["name"],
                "geometry_kind": "polygon",
            },
        ]

        self.map_context = {
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33,
            },
            "zoom": 18,
        }

    @patch("agents_llm.planner.export_gis_layers_catalog")
    @patch("agents_llm.planner.chat_completion_json")
    def test_plan_run_replaces_invalid_query_layer_with_valid_line_layer(
        self,
        mock_chat_completion_json,
        mock_export_gis_layers_catalog,
    ):
        mock_export_gis_layers_catalog.return_value = self.catalog
        mock_chat_completion_json.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {
                        "layer": "invented_lines_layer",
                        "limit": 50,
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        }

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={
                "goal": "Explora la capa de lineas en esta zona",
                "map_context": self.map_context,
            },
        )

        result = plan_run(run, run.input_json)
        step = result["steps"][0]

        self.assertEqual(step["name"], "spatial.query_layer")
        self.assertEqual(step["args"]["layer"], "demo_lines")
        self.assertEqual(step["args"]["bbox"], self.map_context["bbox"])

    @patch("agents_llm.planner.export_gis_layers_catalog")
    @patch("agents_llm.planner.chat_completion_json")
    def test_plan_run_replaces_invalid_intersection_layers_with_valid_layers(
        self,
        mock_chat_completion_json,
        mock_export_gis_layers_catalog,
    ):
        mock_export_gis_layers_catalog.return_value = self.catalog
        mock_chat_completion_json.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.intersects",
                    "args": {
                        "source_layer": "fake_source",
                        "target_layer": "fake_target",
                        "limit": 20,
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        }

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={
                "goal": "Comprueba la relación espacial entre las lineas y las zonas en esta área",
                "map_context": self.map_context,
            },
        )

        result = plan_run(run, run.input_json)
        step = result["steps"][0]

        self.assertEqual(step["name"], "spatial.intersects")
        self.assertEqual(step["args"]["source_layer"], "demo_lines")
        self.assertEqual(step["args"]["target_layer"], "demo_polygons")
        self.assertEqual(step["args"]["bbox"], self.map_context["bbox"])

    @patch("agents_llm.planner.export_gis_layers_catalog")
    @patch("agents_llm.planner.chat_completion_json")
    def test_plan_run_replaces_invalid_network_layer_with_valid_line_layer(
        self,
        mock_chat_completion_json,
        mock_export_gis_layers_catalog,
    ):
        mock_export_gis_layers_catalog.return_value = self.catalog
        mock_chat_completion_json.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "fake_network_layer",
                        "start_point": {"lon": -6.0550, "lat": 37.3250},
                        "end_point": {"lon": -6.0560, "lat": 37.3260},
                        "include_geom": True,
                    },
                    "required": True,
                },
                {"type": "final"},
            ]
        }

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={
                "goal": "Traza una ruta por la red",
                "map_context": self.map_context,
            },
        )

        result = plan_run(run, run.input_json)
        step = result["steps"][0]

        self.assertEqual(step["name"], "spatial.network_trace")
        self.assertEqual(step["args"]["layer"], "demo_lines")
        self.assertEqual(step["args"]["max_snap_distance_m"], 250.0)


class PlannerValidationTests(TestCase):
    def test_validate_plan_adds_new_defaults_for_tool_steps(self):
        plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_lines"},
                },
                {"type": "final"},
            ]
        }

        result = validate_plan(plan)
        step = result["steps"][0]

        self.assertEqual(step["required"], True)
        self.assertEqual(step["depends_on"], [])
        self.assertEqual(step["on_fail"], "abort")
        self.assertEqual(step["success_criteria"], {})
        self.assertEqual(step["timeout_s"], 0)
        self.assertEqual(step["max_retries"], 0)
        self.assertEqual(step["retry_backoff_s"], 0)
        self.assertEqual(step["can_replan"], False)

    def test_validate_plan_accepts_simple_success_criteria(self):
        plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {"layer": "demo_lines"},
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        result = validate_plan(plan)
        step = result["steps"][0]

        self.assertEqual(
            step["success_criteria"],
            {"path": "data.path_found", "equals": True},
        )

    def test_validate_plan_rejects_success_criteria_without_path(self):
        plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {"layer": "demo_lines"},
                    "success_criteria": {
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        with self.assertRaisesMessage(ValueError, "requires path"):
            validate_plan(plan)

    def test_validate_plan_rejects_multiple_success_criteria_operators(self):
        plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {"layer": "demo_lines"},
                    "success_criteria": {
                        "path": "data.count_total",
                        "equals": 0,
                        "gt": 1,
                    },
                },
                {"type": "final"},
            ]
        }

        with self.assertRaisesMessage(ValueError, "only one operator"):
            validate_plan(plan)

    def test_validate_plan_rejects_future_dependency(self):
        plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_lines"},
                    "depends_on": ["s2"],
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_polygons"},
                },
                {"type": "final"},
            ]
        }

        with self.assertRaisesMessage(ValueError, "unknown or future step id"):
            validate_plan(plan)


class RunnerReasoningTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="runner_tester",
            email="runner_tester@example.com",
            password="secret123",
        )
        self.agent = Agent.objects.create(
            name="runner-agent",
            profile="investigate",
            tool_allowlist=[
                "spatial.query_layer",
                "spatial.network_trace",
            ],
        )

    @patch("agents_core.runner.synthesize_run", return_value="síntesis final")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_resolves_references_between_steps(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "encadena tools"},
        )

        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points"},
                    "required": True,
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": "$step:s1.data.features.0.centroid",
                        "end_point": {"lon": -6.056, "lat": 37.326},
                    },
                    "depends_on": ["s1"],
                    "required": True,
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        captured_args = []

        def _invoke_side_effect(*, run, tool_name, args, user):
            captured_args.append({"tool_name": tool_name, "args": args})
            if tool_name == "spatial.query_layer":
                return (
                    _tool_ok(
                        {
                            "features": [
                                {
                                    "id": 1,
                                    "name": "P1",
                                    "centroid": {"lon": -6.055, "lat": 37.325},
                                }
                            ]
                        }
                    ),
                    10,
                )

            if tool_name == "spatial.network_trace":
                return (
                    _tool_ok(
                        {
                            "path_found": True,
                            "segments": [{"name": "seg-1"}],
                        }
                    ),
                    12,
                )

            raise AssertionError(f"tool inesperada: {tool_name}")

        mock_invoke_tool.side_effect = _invoke_side_effect

        result_run = execute_run(run)
        executed = result_run.output_json["executed_outputs"]

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(len(executed), 2)
        self.assertEqual(captured_args[1]["args"]["start_point"], {"lon": -6.055, "lat": 37.325})
        self.assertEqual(executed[1]["verification"]["status"], "verified")

    @patch("agents_core.runner.synthesize_run", return_value="síntesis verificada")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_marks_verified_when_success_criteria_matches(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "verifica ruta"},
        )

        mock_plan_run.return_value = {
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
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        mock_invoke_tool.return_value = (
            _tool_ok({"path_found": True, "segments": [{"name": "seg-1"}]}),
            15,
        )

        result_run = execute_run(run)
        step = result_run.output_json["executed_outputs"][0]

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(step["verification"]["status"], "verified")
        self.assertEqual(step["verification"]["observed"], True)

    @patch("agents_core.runner.synthesize_run", return_value="síntesis refutada")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_marks_refuted_when_success_criteria_fails(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "verifica ruta fallida"},
        )

        mock_plan_run.return_value = {
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
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                    "on_fail": "continue",
                },
                {"type": "final"},
            ]
        }

        mock_invoke_tool.return_value = (
            _tool_ok({"path_found": False, "reason": "network disconnected"}),
            11,
        )

        result_run = execute_run(run)
        step = result_run.output_json["executed_outputs"][0]

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(step["ok"], True)
        self.assertEqual(step["verification"]["status"], "refuted")
        self.assertEqual(step["verification"]["observed"], False)

    @patch("agents_core.runner.MAX_REPLANS", 1)
    @patch("agents_core.runner.synthesize_run", return_value="síntesis con replan")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_replans_when_step_allows_it(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "replanifica si falla la hipótesis"},
        )

        first_plan = {
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
                    "can_replan": True,
                    "on_fail": "continue",
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        second_plan = {
            "steps": [
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points"},
                    "required": True,
                },
                {"type": "final"},
            ]
        }

        mock_plan_run.side_effect = [first_plan, second_plan]
        mock_invoke_tool.side_effect = [
            (_tool_ok({"path_found": False, "reason": "disconnected"}), 8),
            (_tool_ok({"features": [{"id": 1, "name": "fallback"}]}), 6),
        ]

        result_run = execute_run(run)
        output = result_run.output_json

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(output["replan_count"], 1)
        self.assertEqual(len(output["plan_history"]), 2)
        self.assertEqual(output["executed_outputs"][0]["verification"]["status"], "refuted")
        self.assertEqual(output["executed_outputs"][1]["name"], "spatial.query_layer")
        self.assertEqual(mock_plan_run.call_count, 2)

    @patch("agents_core.runner.MAX_REPLANS", 0)
    @patch("agents_core.runner.synthesize_run", return_value="síntesis sin replan")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_does_not_replan_when_max_replans_is_zero(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "no replanifiques"},
        )

        mock_plan_run.return_value = {
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
                    "can_replan": True,
                    "on_fail": "continue",
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        mock_invoke_tool.return_value = (
            _tool_ok({"path_found": False, "reason": "disconnected"}),
            9,
        )

        result_run = execute_run(run)
        output = result_run.output_json

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(output["replan_count"], 0)
        self.assertEqual(len(output["plan_history"]), 1)
        self.assertEqual(mock_plan_run.call_count, 1)
        self.assertEqual(output["executed_outputs"][0]["verification"]["status"], "refuted")

    @patch("agents_core.runner.synthesize_run", return_value="síntesis con retry")
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_execute_run_retries_tool_until_success(
        self,
        mock_plan_run,
        mock_invoke_tool,
        _mock_synthesize_run,
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "reintenta la tool"},
        )

        mock_plan_run.return_value = {
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
                    "max_retries": 1,
                    "retry_backoff_s": 0,
                    "success_criteria": {
                        "path": "data.path_found",
                        "equals": True,
                    },
                },
                {"type": "final"},
            ]
        }

        mock_invoke_tool.side_effect = [
            (_tool_fail("temporary network error"), 5),
            (_tool_ok({"path_found": True}), 7),
        ]

        result_run = execute_run(run)
        step = result_run.output_json["executed_outputs"][0]

        self.assertEqual(result_run.status, "succeeded")
        self.assertEqual(step["attempt_count"], 2)
        self.assertEqual(len(step["attempts"]), 2)
        self.assertEqual(step["attempts"][0]["ok"], False)
        self.assertEqual(step["attempts"][1]["ok"], True)
        self.assertEqual(step["verification"]["status"], "verified")