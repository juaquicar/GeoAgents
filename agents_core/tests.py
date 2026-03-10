from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from agents_core.models import Agent, Run
from agents_core.runner import execute_run
from agents_llm.planner import plan_run
from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from agents_core.models import Agent, Run
from agents_core.runner import execute_run
from agents_llm.planner import plan_run

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