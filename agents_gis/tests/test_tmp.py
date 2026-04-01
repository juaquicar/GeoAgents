
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from agents_core.models import Agent, Run


def _tool_ok(data):
    return SimpleNamespace(ok=True, data=data, error="")


def _tool_fail(error):
    return SimpleNamespace(ok=False, data={}, error=error)


class NetworkServiceAreaApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="service_area_api_user",
            email="service_area_api_user@example.com",
            password="secret123",
        )
        self.other_user = User.objects.create_user(
            username="service_area_api_other",
            email="service_area_api_other@example.com",
            password="secret123",
        )

        self.token = Token.objects.create(user=self.user)
        self.other_token = Token.objects.create(user=self.other_user)

        self.agent = Agent.objects.create(
            name="service-area-api-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=[
                "spatial.network_service_area",
                "spatial.network_trace",
                "spatial.route_cost",
            ],
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def _direct_tool_payload(self, args=None, goal="calcular area de servicio de red"):
        args = args or {
            "layer": "demo_lines",
            "origin_point": {"lon": -6.055, "lat": 37.325},
            "max_cost": 300,
            "metric": "cost",
            "include_geom": True,
            "max_snap_distance_m": 250,
            "bbox": {
                "west": -6.06,
                "south": 37.32,
                "east": -6.05,
                "north": 37.33,
            },
        }
        return {
            "agent": self.agent.id,
            "input_json": {
                "goal": goal,
                "tool_call": {
                    "name": "spatial.network_service_area",
                    "args": args,
                },
            },
        }

    def _create_run_via_api(self, payload):
        url = reverse("runs-list")
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 201)
        return response

    def _execute_run_via_api(self, run_id):
        url = reverse("runs-execute", kwargs={"pk": run_id})
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        return response

    @patch("agents_core.runner.invoke_tool")
    def test_create_and_execute_direct_network_service_area_run_via_api(self, mock_invoke_tool):
        mock_invoke_tool.return_value = (
            _tool_ok(
                {
                    "layer": "demo_lines",
                    "reachable": True,
                    "origin_point": {"lon": -6.055, "lat": 37.325},
                    "origin_snap_node": {"lon": -6.0555, "lat": 37.325},
                    "origin_snap_m": 44.21,
                    "metric": "cost",
                    "limits": {
                        "max_cost": 300.0,
                        "max_distance_m": None,
                    },
                    "reachable_node_count": 3,
                    "reachable_segment_count": 2,
                    "reachable_segment_ids": [3, 4],
                    "reachable_segment_types": [None, None],
                    "total_reachable_length_m": 471.78,
                    "total_reachable_cost": 471.78,
                    "coverage_summary": {
                        "total_network_nodes": 5,
                        "total_network_segments": 4,
                        "total_network_length_m": 826.86,
                        "total_network_cost": 826.86,
                        "node_coverage_ratio": 0.6,
                        "segment_coverage_ratio": 0.5,
                        "length_coverage_ratio": 0.5705,
                        "cost_coverage_ratio": 0.5705,
                    },
                    "reachable_nodes": [
                        {"lon": -6.0555, "lat": 37.325, "cost_from_origin": 0.0},
                        {"lon": -6.0570, "lat": 37.3235, "cost_from_origin": 213.04},
                        {"lon": -6.0540, "lat": 37.3270, "cost_from_origin": 258.73},
                    ],
                    "coverage_bbox": {
                        "west": -6.0570,
                        "south": 37.3235,
                        "east": -6.0540,
                        "north": 37.3270,
                    },
                    "service_segments": [
                        {
                            "segment_id": 3,
                            "segment_name": "Tramo 3",
                            "segment_type": None,
                            "length_m": 213.04,
                            "edge_cost": 213.04,
                            "geom_geojson": "{\"type\":\"LineString\",\"coordinates\":[[-6.057,37.3235],[-6.0555,37.325]]}",
                        },
                        {
                            "segment_id": 4,
                            "segment_name": "Tramo 4",
                            "segment_type": None,
                            "length_m": 258.73,
                            "edge_cost": 258.73,
                            "geom_geojson": "{\"type\":\"LineString\",\"coordinates\":[[-6.0555,37.325],[-6.054,37.327]]}",
                        },
                    ],
                }
            ),
            12,
        )

        create_response = self._create_run_via_api(self._direct_tool_payload())
        run_id = create_response.data["id"]

        self.assertEqual(create_response.data["status"], "queued")
        self.assertEqual(
            create_response.data["input_json"]["tool_call"]["name"],
            "spatial.network_service_area",
        )

        execute_response = self._execute_run_via_api(run_id)

        self.assertEqual(execute_response.data["status"], "succeeded")
        self.assertEqual(execute_response.data["output_json"]["ok"], True)
        self.assertEqual(
            execute_response.data["output_json"]["tool"],
            "spatial.network_service_area",
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_segment_ids"],
            [3, 4],
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_segment_count"],
            2,
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_node_count"],
            3,
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["coverage_summary"]["segment_coverage_ratio"],
            0.5,
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["limits"]["max_cost"],
            300.0,
        )
        self.assertEqual(execute_response.data["final_text"], "")
        self.assertEqual(execute_response.data["error"], "")

        run = Run.objects.get(id=run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.output_json["tool"], "spatial.network_service_area")
        self.assertTrue(run.output_json["data"]["reachable"])

        # Comportamiento actual del flujo directo: sin executed_outputs enriquecido.
        self.assertEqual(execute_response.data["executed_outputs"], [])
        self.assertEqual(execute_response.data["verification_summary"]["counts"]["verified"], 0)
        self.assertEqual(execute_response.data["verification_summary"]["counts"]["refuted"], 0)

        self.assertIsNotNone(execute_response.data["run_memory"])
        self.assertIsNotNone(execute_response.data["episode"])
        self.assertEqual(execute_response.data["run_memory"]["domain"], "network")
        self.assertIn(
            "network_service_area",
            execute_response.data["run_memory"]["analysis_types"],
        )
        self.assertEqual(
            execute_response.data["episode"]["outcome_status"],
            "succeeded",
        )

    @patch("agents_core.runner.invoke_tool")
    def test_direct_network_service_area_snap_distance_exceeded_via_api(self, mock_invoke_tool):
        mock_invoke_tool.return_value = (
            _tool_ok(
                {
                    "layer": "demo_lines",
                    "reachable": False,
                    "reason": "snap_distance_exceeded",
                    "origin_point": {"lon": -6.20, "lat": 37.10},
                    "origin_snap_node": {"lon": -6.0555, "lat": 37.325},
                    "origin_snap_m": 4021.55,
                    "metric": "cost",
                    "limits": {
                        "max_cost": 300.0,
                        "max_distance_m": None,
                    },
                    "reachable_node_count": 0,
                    "reachable_segment_count": 0,
                    "reachable_segment_ids": [],
                    "reachable_segment_types": [],
                    "total_reachable_length_m": 0.0,
                    "total_reachable_cost": 0.0,
                    "coverage_summary": {
                        "total_network_nodes": 5,
                        "total_network_segments": 4,
                        "total_network_length_m": 826.86,
                        "total_network_cost": 826.86,
                        "node_coverage_ratio": 0.0,
                        "segment_coverage_ratio": 0.0,
                        "length_coverage_ratio": 0.0,
                        "cost_coverage_ratio": 0.0,
                    },
                    "reachable_nodes": [],
                    "coverage_bbox": None,
                    "service_segments": [],
                }
            ),
            9,
        )

        payload = self._direct_tool_payload(
            args={
                "layer": "demo_lines",
                "origin_point": {"lon": -6.20, "lat": 37.10},
                "max_cost": 300,
                "metric": "cost",
                "include_geom": False,
                "max_snap_distance_m": 20,
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
            },
            goal="calcular area de servicio con origen fuera de red",
        )

        create_response = self._create_run_via_api(payload)
        run_id = create_response.data["id"]

        execute_response = self._execute_run_via_api(run_id)

        self.assertEqual(execute_response.data["status"], "succeeded")
        self.assertEqual(execute_response.data["output_json"]["ok"], True)
        self.assertEqual(
            execute_response.data["output_json"]["tool"],
            "spatial.network_service_area",
        )
        self.assertFalse(execute_response.data["output_json"]["data"]["reachable"])
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reason"],
            "snap_distance_exceeded",
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_segment_ids"],
            [],
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_segment_count"],
            0,
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["coverage_bbox"],
            None,
        )

        run = Run.objects.get(id=run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.error, "")
        self.assertEqual(
            run.output_json["data"]["reason"],
            "snap_distance_exceeded",
        )

        self.assertIsNotNone(execute_response.data["run_memory"])
        self.assertEqual(execute_response.data["run_memory"]["domain"], "network")
        self.assertIn(
            "network_service_area",
            execute_response.data["run_memory"]["analysis_types"],
        )

    @patch("agents_core.runner.invoke_tool")
    def test_direct_network_service_area_default_limit_and_trace_visibility_via_api(self, mock_invoke_tool):
        mock_invoke_tool.return_value = (
            _tool_ok(
                {
                    "layer": "demo_lines",
                    "reachable": True,
                    "origin_point": {"lon": -6.055, "lat": 37.325},
                    "origin_snap_node": {"lon": -6.0555, "lat": 37.325},
                    "origin_snap_m": 44.21,
                    "metric": "cost",
                    "limits": {
                        "max_cost": 1500.0,
                        "max_distance_m": None,
                    },
                    "reachable_node_count": 5,
                    "reachable_segment_count": 4,
                    "reachable_segment_ids": [1, 2, 3, 4],
                    "reachable_segment_types": [None, None, None, None],
                    "total_reachable_length_m": 826.86,
                    "total_reachable_cost": 826.86,
                    "coverage_summary": {
                        "total_network_nodes": 5,
                        "total_network_segments": 4,
                        "total_network_length_m": 826.86,
                        "total_network_cost": 826.86,
                        "node_coverage_ratio": 1.0,
                        "segment_coverage_ratio": 1.0,
                        "length_coverage_ratio": 1.0,
                        "cost_coverage_ratio": 1.0,
                    },
                    "reachable_nodes": [],
                    "coverage_bbox": {
                        "west": -6.0600,
                        "south": 37.3200,
                        "east": -6.0500,
                        "north": 37.3300,
                    },
                    "service_segments": [],
                }
            ),
            11,
        )

        payload = self._direct_tool_payload(
            args={
                "layer": "demo_lines",
                "origin_point": {"lon": -6.055, "lat": 37.325},
                "metric": "cost",
                "include_geom": False,
                "bbox": {
                    "west": -6.06,
                    "south": 37.32,
                    "east": -6.05,
                    "north": 37.33,
                },
            },
            goal="calcular cobertura de red desde un origen",
        )

        create_response = self._create_run_via_api(payload)
        run_id = create_response.data["id"]

        execute_response = self._execute_run_via_api(run_id)
        self.assertEqual(execute_response.data["status"], "succeeded")
        self.assertEqual(
            execute_response.data["output_json"]["data"]["limits"]["max_cost"],
            1500.0,
        )
        self.assertEqual(
            execute_response.data["output_json"]["data"]["reachable_segment_count"],
            4,
        )

        detail_url = reverse("runs-detail", kwargs={"pk": run_id})
        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["id"], run_id)
        self.assertEqual(detail_response.data["status"], "succeeded")
        self.assertEqual(
            detail_response.data["output_json"]["tool"],
            "spatial.network_service_area",
        )

        steps_url = reverse("runs-steps", kwargs={"pk": run_id})
        steps_response = self.client.get(steps_url)
        self.assertEqual(steps_response.status_code, 200)
        self.assertGreaterEqual(len(steps_response.data), 3)
        step_names = [step["name"] for step in steps_response.data]
        self.assertIn("run.start", step_names)
        self.assertIn("tool.result", step_names)
        self.assertIn("run.end", step_names)

        trace_url = reverse("runs-trace", kwargs={"pk": run_id})
        trace_response = self.client.get(trace_url)
        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.data["id"], run_id)
        self.assertIn("trace", trace_response.data)
        self.assertEqual(trace_response.data["trace"]["goal"], "calcular cobertura de red desde un origen")
        self.assertEqual(trace_response.data["trace"]["replan_count"], 0)
        self.assertEqual(trace_response.data["trace"]["plan_history"], [])
        self.assertEqual(
            trace_response.data["trace"]["verification_summary"]["counts"]["verified"],
            0,
        )

    def test_execute_direct_network_service_area_is_forbidden_for_other_user_run(self):
        foreign_run = Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={
                "goal": "run ajeno",
                "tool_call": {
                    "name": "spatial.network_service_area",
                    "args": {
                        "layer": "demo_lines",
                        "origin_point": {"lon": -6.055, "lat": 37.325},
                        "max_cost": 300,
                    },
                },
            },
        )

        url = reverse("runs-execute", kwargs={"pk": foreign_run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 404)