"""
Tests de API REST para agents_core: agentes, runs, steps, trace, memoria y episodios.

Ejecutar:
    python manage.py test tests.test_api_core
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from agents_core.models import Agent, Episode, Run, RunMemory, RunStep
from agents_core.runner import execute_run


def _tool_ok(data):
    return SimpleNamespace(ok=True, data=data, error="")


class AgentsCoreApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="api_user",
            email="api_user@example.com",
            password="secret123",
        )
        self.other_user = User.objects.create_user(
            username="other_user",
            email="other_user@example.com",
            password="secret123",
        )

        self.token = Token.objects.create(user=self.user)
        self.other_token = Token.objects.create(user=self.other_user)

        # Agente sin gis_db_connections (los tests de core no necesitan GIS remoto)
        self.agent = Agent.objects.create(
            name="api-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=[
                "spatial.query_layer",
                "spatial.network_trace",
            ],
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    # ── Autenticación ────────────────────────────────────────────────────────

    def test_runs_endpoint_requires_authentication(self):
        self.client.credentials()
        url = reverse("runs-list")
        response = self.client.get(url)
        self.assertIn(response.status_code, (401, 403))

    # ── Creación y listado ───────────────────────────────────────────────────

    def test_create_run_assigns_authenticated_user(self):
        url = reverse("runs-list")
        payload = {"agent": self.agent.id, "input_json": {"goal": "consulta simple"}}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, 201)
        run = Run.objects.get(id=response.data["id"])
        self.assertEqual(run.user_id, self.user.id)
        self.assertEqual(run.agent_id, self.agent.id)
        self.assertEqual(run.status, "queued")

    def test_runs_list_only_returns_current_user_runs(self):
        own_run = Run.objects.create(agent=self.agent, user=self.user, input_json={"goal": "run propio"})
        Run.objects.create(agent=self.agent, user=self.other_user, input_json={"goal": "run ajeno"})
        url = reverse("runs-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertIn(own_run.id, ids)
        self.assertEqual(len(ids), 1)

    # ── Execute ──────────────────────────────────────────────────────────────

    @patch("agents_core.views.execute_run")
    def test_execute_action_runs_and_returns_enriched_run(self, mock_execute_run):
        run = Run.objects.create(agent=self.agent, user=self.user, input_json={"goal": "ejecuta este run"})
        run.status = "succeeded"
        run.final_text = "respuesta final"
        run.output_json = {
            "ok": True,
            "goal": "ejecuta este run",
            "plan": {
                "steps": [
                    {"id": "s1", "type": "tool", "name": "spatial.query_layer"},
                    {"type": "final"},
                ]
            },
            "plan_history": [
                {
                    "label": "initial",
                    "steps": [
                        {"id": "s1", "type": "tool", "name": "spatial.query_layer"},
                        {"type": "final"},
                    ],
                }
            ],
            "replan_count": 0,
            "executed_outputs": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "ok": True,
                    "data": {"features": [{"id": 1, "name": "A"}]},
                    "error": "",
                    "attempt_count": 1,
                    "latency_ms": 8,
                    "latency_ms_total": 8,
                    "verification": {
                        "status": "not_evaluated",
                        "reason": "No success_criteria provided.",
                        "observed": None,
                        "criteria": {},
                    },
                }
            ],
        }
        mock_execute_run.return_value = run

        url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], run.id)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["final_text"], "respuesta final")
        self.assertEqual(response.data["replan_count"], 0)
        self.assertIn("verification_summary", response.data)
        self.assertIn("executed_outputs", response.data)
        self.assertEqual(len(response.data["executed_outputs"]), 1)

        step = response.data["executed_outputs"][0]
        self.assertIn("attempt_count", step)
        self.assertIn("depends_on", step)
        self.assertIn("resolved_args", step)
        self.assertIn("verification", step)
        self.assertEqual(step["attempt_count"], 1)
        self.assertEqual(step["depends_on"], [])
        self.assertEqual(step["resolved_args"], {})
        self.assertEqual(step["verification"]["status"], "not_evaluated")
        self.assertEqual(step["verification"]["reason"], "No success_criteria provided.")

    def test_execute_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(agent=self.agent, user=self.other_user, input_json={"goal": "run ajeno"})
        url = reverse("runs-execute", kwargs={"pk": foreign_run.id})
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 404)

    # ── Steps ────────────────────────────────────────────────────────────────

    def test_steps_action_returns_persisted_steps(self):
        run = Run.objects.create(agent=self.agent, user=self.user, input_json={"goal": "ver steps"})
        RunStep.objects.create(run=run, idx=0, kind="system", name="run.start",
                               input_json={"a": 1}, output_json={"status": "running"}, latency_ms=0, error="")
        RunStep.objects.create(run=run, idx=1, kind="result", name="planner.result",
                               input_json={"goal": "ver steps"}, output_json={"ok": True}, latency_ms=12, error="")

        url = reverse("runs-steps", kwargs={"pk": run.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["idx"], 0)
        self.assertEqual(response.data[0]["name"], "run.start")
        self.assertEqual(response.data[1]["idx"], 1)
        self.assertEqual(response.data[1]["name"], "planner.result")

    def test_steps_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(agent=self.agent, user=self.other_user, input_json={"goal": "run ajeno"})
        url = reverse("runs-steps", kwargs={"pk": foreign_run.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    # ── Trace ────────────────────────────────────────────────────────────────

    def test_trace_action_returns_trace_payload(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="succeeded",
            input_json={"goal": "inspeccionar trace"},
            output_json={
                "ok": True,
                "goal": "inspeccionar trace",
                "plan": {
                    "steps": [
                        {
                            "id": "s1",
                            "type": "tool",
                            "name": "spatial.network_trace",
                            "success_criteria": {"path": "data.path_found", "equals": True},
                        },
                        {"type": "final"},
                    ]
                },
                "plan_history": [
                    {
                        "label": "initial",
                        "steps": [
                            {"id": "s1", "type": "tool", "name": "spatial.network_trace"},
                            {"type": "final"},
                        ],
                    }
                ],
                "replan_count": 1,
                "executed_outputs": [
                    {
                        "id": "s1",
                        "type": "tool",
                        "name": "spatial.network_trace",
                        "ok": True,
                        "hypothesis": "Existe una ruta de red válida",
                        "verification_target": "Confirmar si hay ruta",
                        "success_criteria": {"path": "data.path_found", "equals": True},
                        "depends_on": [],
                        "resolved_args": {
                            "layer": "demo_lines",
                            "start_point": {"lon": -6.055, "lat": 37.325},
                            "end_point": {"lon": -6.056, "lat": 37.326},
                        },
                        "data": {"path_found": True, "segments": [{"name": "seg-1"}]},
                        "error": "",
                        "attempt_count": 2,
                        "latency_ms": 7,
                        "latency_ms_total": 12,
                        "verification": {
                            "status": "verified",
                            "hypothesis": "Existe una ruta de red válida",
                            "target": "Confirmar si hay ruta",
                            "criteria": {"path": "data.path_found", "equals": True},
                            "observed": True,
                            "reason": "Evaluated equals on path 'data.path_found'.",
                        },
                    }
                ],
                "final_text": "Se encontró una ruta válida.",
            },
            final_text="Se encontró una ruta válida.",
        )
        RunStep.objects.create(run=run, idx=0, kind="system", name="run.start",
                               input_json={}, output_json={"status": "running"}, latency_ms=0, error="")
        RunStep.objects.create(run=run, idx=1, kind="llm", name="llm.plan",
                               input_json={"goal": "inspeccionar trace"},
                               output_json={"steps": [{"id": "s1", "type": "tool"}, {"type": "final"}]},
                               latency_ms=0, error="")

        url = reverse("runs-trace", kwargs={"pk": run.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], run.id)
        self.assertEqual(response.data["agent_name"], self.agent.name)
        self.assertIn("steps", response.data)
        self.assertIn("trace", response.data)
        self.assertEqual(len(response.data["steps"]), 2)
        self.assertEqual(response.data["trace"]["goal"], "inspeccionar trace")
        self.assertEqual(response.data["trace"]["replan_count"], 1)
        self.assertEqual(response.data["trace"]["verification_summary"]["counts"]["verified"], 1)
        self.assertEqual(response.data["trace"]["stats"]["tool_steps_executed"], 1)
        self.assertEqual(response.data["trace"]["stats"]["total_attempts"], 2)

        verified_item = response.data["trace"]["verification_summary"]["verified"][0]
        self.assertIn("depends_on", verified_item)
        self.assertIn("resolved_args", verified_item)
        self.assertIn("attempt_count", verified_item)
        self.assertIn("reason", verified_item)
        self.assertEqual(verified_item["depends_on"], [])
        self.assertEqual(verified_item["attempt_count"], 2)
        self.assertEqual(verified_item["reason"], "Evaluated equals on path 'data.path_found'.")

        trace_step = response.data["trace"]["executed_outputs"][0]
        self.assertEqual(trace_step["depends_on"], [])
        self.assertIn("resolved_args", trace_step)
        self.assertIn("attempt_count", trace_step)
        self.assertEqual(trace_step["attempt_count"], 2)
        self.assertEqual(trace_step["verification"]["status"], "verified")
        self.assertEqual(trace_step["verification"]["reason"], "Evaluated equals on path 'data.path_found'.")

    def test_trace_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(agent=self.agent, user=self.other_user, input_json={"goal": "run ajeno"})
        url = reverse("runs-trace", kwargs={"pk": foreign_run.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    # ── Serializer normalization ─────────────────────────────────────────────

    def test_run_serializer_normalizes_contract_defaults(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="succeeded",
            input_json={"goal": "defaults contract"},
            output_json={
                "ok": True,
                "plan_history": [],
                "replan_count": 0,
                "executed_outputs": [
                    {"id": "s1", "type": "tool", "name": "spatial.query_layer", "ok": True}
                ],
            },
        )
        url = reverse("runs-detail", kwargs={"pk": run.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        step = response.data["executed_outputs"][0]
        self.assertEqual(step["attempt_count"], 0)
        self.assertEqual(step["depends_on"], [])
        self.assertEqual(step["resolved_args"], {})
        self.assertEqual(step["verification"]["status"], "not_evaluated")
        self.assertEqual(step["verification"]["reason"], "")
        self.assertEqual(response.data["replan_count"], 0)
        self.assertEqual(response.data["plan_history"], [])

    def test_trace_serializer_normalizes_contract_defaults(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="succeeded",
            input_json={"goal": "trace defaults"},
            output_json={
                "ok": True,
                "plan": {"steps": [{"id": "s1", "type": "tool", "name": "spatial.query_layer"}, {"type": "final"}]},
                "plan_history": [],
                "replan_count": 0,
                "executed_outputs": [
                    {"id": "s1", "type": "tool", "name": "spatial.query_layer", "ok": True}
                ],
            },
        )
        url = reverse("runs-trace", kwargs={"pk": run.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        trace_step = response.data["trace"]["executed_outputs"][0]
        self.assertEqual(trace_step["depends_on"], [])
        self.assertEqual(trace_step["resolved_args"], {})
        self.assertEqual(trace_step["attempt_count"], 0)
        self.assertEqual(trace_step["verification"]["status"], "not_evaluated")
        self.assertEqual(trace_step["verification"]["reason"], "")

        verification_item = response.data["trace"]["verification_summary"]["not_evaluated"][0]
        self.assertEqual(verification_item["depends_on"], [])
        self.assertEqual(verification_item["resolved_args"], {})
        self.assertEqual(verification_item["attempt_count"], 0)
        self.assertEqual(verification_item["reason"], "")
        self.assertEqual(response.data["trace"]["replan_count"], 0)
        self.assertEqual(response.data["trace"]["plan_history"], [])

    # ── Flujo completo con mocks ─────────────────────────────────────────────

    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis desde API", "final_sql": ""})
    def test_full_execute_flow_persists_steps_and_trace_is_visible(
        self, _mock_synthesize_run, mock_plan_run, mock_invoke_tool
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "ejecución completa API"},
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
                    "success_criteria": {"path": "data.path_found", "equals": True},
                },
                {"type": "final"},
            ]
        }
        mock_invoke_tool.return_value = (
            _tool_ok({"path_found": True, "segments": [{"name": "seg-1"}]}),
            10,
        )

        execute_url = reverse("runs-execute", kwargs={"pk": run.id})
        execute_response = self.client.post(execute_url, {}, format="json")

        self.assertEqual(execute_response.status_code, 200)
        self.assertEqual(execute_response.data["status"], "succeeded")
        self.assertEqual(execute_response.data["verification_summary"]["counts"]["verified"], 1)

        execute_step = execute_response.data["executed_outputs"][0]
        self.assertIn("attempt_count", execute_step)
        self.assertIn("depends_on", execute_step)
        self.assertIn("resolved_args", execute_step)
        self.assertEqual(execute_step["attempt_count"], 1)
        self.assertEqual(execute_step["depends_on"], [])
        self.assertEqual(execute_step["verification"]["status"], "verified")
        self.assertEqual(execute_step["verification"]["reason"], "Evaluated equals on path 'data.path_found'.")

        trace_url = reverse("runs-trace", kwargs={"pk": run.id})
        trace_response = self.client.get(trace_url)

        self.assertEqual(trace_response.status_code, 200)
        self.assertGreaterEqual(len(trace_response.data["steps"]), 4)
        self.assertEqual(trace_response.data["trace"]["stats"]["tool_steps_executed"], 1)
        self.assertEqual(trace_response.data["trace"]["verification_summary"]["counts"]["verified"], 1)

        verified_item = trace_response.data["trace"]["verification_summary"]["verified"][0]
        self.assertEqual(verified_item["attempt_count"], 1)
        self.assertEqual(verified_item["depends_on"], [])
        self.assertIn("resolved_args", verified_item)
        self.assertEqual(verified_item["reason"], "Evaluated equals on path 'data.path_found'.")

    # ── Filtrado por memoria ─────────────────────────────────────────────────

    def test_runs_list_can_filter_by_persisted_memory_fields(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="succeeded",
            input_json={"goal": "Traza una ruta por la red"},
            output_json={"ok": True},
        )
        other_run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            status="succeeded",
            input_json={"goal": "Consulta simple"},
            output_json={"ok": True},
        )

        RunMemory.objects.create(
            run=run,
            normalized_goal="traza una ruta por la red",
            goal_signature="traza|ruta|red",
            domain="network",
            analysis_types=["network_trace"],
            analysis_types_search="network_trace",
            layers=["demo_lines"],
            layers_search="demo_lines",
            tools_used=["spatial.network_trace"],
            tools_search="spatial.network_trace",
            tool_sequence_signature="spatial.network_trace",
            verification_status="verified",
            outcome={"status": "succeeded"},
        )
        RunMemory.objects.create(
            run=other_run,
            normalized_goal="consulta simple",
            goal_signature="consulta|simple",
            domain="layer_inspection",
            analysis_types=["layer_query"],
            analysis_types_search="layer_query",
            layers=["demo_points"],
            layers_search="demo_points",
            tools_used=["spatial.query_layer"],
            tools_search="spatial.query_layer",
            tool_sequence_signature="spatial.query_layer",
            verification_status="not_evaluated",
            outcome={"status": "succeeded"},
        )

        url = reverse("runs-list")
        response = self.client.get(url, {
            "tool": "spatial.network_trace",
            "layer": "demo_lines",
            "analysis_type": "network_trace",
            "verification_status": "verified",
            "domain": "network",
        })

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertEqual(ids, [run.id])

    # ── Memory y Episode en respuesta ────────────────────────────────────────

    def test_execute_response_includes_run_memory_and_episode(self):
        run = Run.objects.create(agent=self.agent, user=self.user, input_json={"goal": "ejecuta este run"})
        run.status = "succeeded"
        run.final_text = "respuesta final"
        run.output_json = {
            "ok": True,
            "goal": "ejecuta este run",
            "plan": {"steps": [{"type": "final"}]},
            "plan_history": [],
            "replan_count": 0,
            "executed_outputs": [],
            "verification_summary": {
                "verified": [], "refuted": [], "inconclusive": [], "not_evaluated": [],
                "counts": {"verified": 0, "refuted": 0, "inconclusive": 0, "not_evaluated": 0},
            },
        }
        run.save()
        RunMemory.objects.create(
            run=run,
            normalized_goal="ejecuta este run",
            goal_signature="ejecuta|run",
            domain="generic_spatial",
            analysis_types=["generic_spatial"],
            analysis_types_search="generic_spatial",
            layers=[],
            layers_search="",
            tools_used=[],
            tools_search="",
            tool_sequence_signature="none",
            verification_status="not_evaluated",
            verification_summary=run.output_json["verification_summary"],
            outcome={"status": "succeeded"},
        )
        Episode.objects.create(
            run=run,
            normalized_goal="ejecuta este run",
            goal_signature="ejecuta|run",
            domain="generic_spatial",
            analysis_types=["generic_spatial"],
            tools_used=[],
            tool_sequence=[],
            tool_sequence_signature="none",
            outcome_status="succeeded",
            verification_status="not_evaluated",
            success=True,
            recommended_strategy="Arranque recomendado: spatial.query_layer.",
        )

        with patch("agents_core.views.execute_run", return_value=run):
            url = reverse("runs-execute", kwargs={"pk": run.id})
            response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["run_memory"])
        self.assertIsNotNone(response.data["episode"])
        self.assertEqual(response.data["run_memory"]["goal_signature"], "ejecuta|run")
        self.assertEqual(response.data["episode"]["outcome_status"], "succeeded")

    # ── Flujo refutado (verificación fallida + replan) ────────────────────────

    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis refutada", "final_sql": ""})
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_full_execute_flow_persists_refuted_memory_and_episode(
        self, mock_plan_run, mock_invoke_tool, _mock_synthesize_run
    ):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={
                "goal": "Traza una ruta de red entre dos puntos desconectados",
                "map_context": {
                    "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                    "zoom": 18,
                },
                "trace_context": {
                    "start_point": {"lon": -6.06, "lat": 37.3201},
                    "end_point": {"lon": -6.051, "lat": 37.3299},
                },
            },
        )

        initial_plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": {"lon": -6.06, "lat": 37.3201},
                        "end_point": {"lon": -6.051, "lat": 37.3299},
                        "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                        "include_geom": True,
                        "max_snap_distance_m": 250.0,
                    },
                    "required": True,
                    "on_fail": "continue",
                    "hypothesis": "Existe una ruta de red válida entre ambos puntos",
                    "verification_target": "Comprobar si path_found es true",
                    "success_criteria": {"path": "data.path_found", "equals": True},
                    "timeout_s": 0,
                    "max_retries": 1,
                    "retry_backoff_s": 0,
                    "can_replan": True,
                    "depends_on": [],
                },
                {"type": "final"},
            ]
        }
        replanned = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": {"lon": -6.06, "lat": 37.3201},
                        "end_point": {"lon": -6.051, "lat": 37.3299},
                        "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                        "include_geom": True,
                        "max_snap_distance_m": 250.0,
                    },
                    "required": True,
                    "on_fail": "continue",
                    "hypothesis": "Existe una ruta de red válida entre ambos puntos",
                    "verification_target": "Comprobar si path_found es true",
                    "success_criteria": {"path": "data.path_found", "equals": True},
                    "timeout_s": 0,
                    "max_retries": 1,
                    "retry_backoff_s": 0,
                    "can_replan": True,
                    "depends_on": [],
                },
                {"type": "final"},
            ]
        }
        mock_plan_run.side_effect = [initial_plan, replanned]
        mock_invoke_tool.return_value = (
            _tool_ok({
                "layer": "demo_lines",
                "path_found": False,
                "reason": "snap_distance_exceeded",
                "start_point": {"lon": -6.06, "lat": 37.3201},
                "end_point": {"lon": -6.051, "lat": 37.3299},
                "start_snap_m": 109.40,
                "end_snap_m": 417.54,
                "segment_ids": [],
                "segment_names": [],
                "total_length_m": 0.0,
                "node_count": 0,
                "include_geom": True,
            }),
            19,
        )

        execute_url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(execute_url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")
        # El plan inicial + el replan ambos fallan (path_found=False → refuted en cada ciclo)
        self.assertEqual(response.data["verification_summary"]["counts"]["refuted"], 2)
        self.assertEqual(response.data["replan_count"], 1)

        step = response.data["executed_outputs"][0]
        self.assertEqual(step["name"], "spatial.network_trace")
        self.assertEqual(step["verification"]["status"], "refuted")
        self.assertEqual(step["verification"]["observed"], False)
        self.assertEqual(step["resolved_args"]["start_point"]["lon"], -6.06)
        self.assertEqual(step["resolved_args"]["end_point"]["lon"], -6.051)

        run.refresh_from_db()
        self.assertIsNotNone(run.memory)
        self.assertIsNotNone(run.episode)
        self.assertEqual(run.memory.verification_status, "refuted")
        self.assertEqual(run.memory.tools_used, ["spatial.network_trace"])
        self.assertIn("verification_refuted", run.memory.failure_modes)
        self.assertEqual(run.memory.outcome["replan_count"], 1)
        self.assertEqual(run.episode.verification_status, "refuted")
        self.assertFalse(run.episode.success)
        self.assertEqual(run.episode.failure_mode, "verification_refuted")
        # El plan inicial + replan ejecutan el mismo tool → 2 entradas en tool_sequence
        self.assertEqual(run.episode.tool_sequence, ["spatial.network_trace", "spatial.network_trace"])
        self.assertEqual(run.episode.replan_count, 1)

        list_url = reverse("runs-list")
        filtered = self.client.get(list_url, {"verification_status": "refuted"})
        self.assertEqual(filtered.status_code, 200)
        ids = [item["id"] for item in filtered.data]
        self.assertIn(run.id, ids)

    # ── Replan por fallo de tool ─────────────────────────────────────────────

    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis tras replan", "final_sql": ""})
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_tool_failure_with_abort_policy_triggers_replan(
        self, mock_plan_run, mock_invoke_tool, _mock_synthesize
    ):
        """Un tool que falla con on_fail=abort debe disparar replan automático."""
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "Análisis de red con fallo"},
        )

        failed_tool = SimpleNamespace(ok=False, data={}, error="layer not found: unknown_layer")
        ok_tool = SimpleNamespace(ok=True, data={"layers": [{"layer": "demo_lines", "count": 5}]}, error="")

        initial_plan = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "unknown_layer"},
                    "required": True,
                    "on_fail": "abort",
                    "can_replan": False,  # no importa: abort+fail → replan igualmente
                },
                {"type": "final"},
            ]
        }
        replanned = {
            "steps": [
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": {"lon": -6.06, "lat": 37.32},
                        "end_point": {"lon": -6.05, "lat": 37.33},
                    },
                    "required": True,
                    "on_fail": "continue",
                },
                {"type": "final"},
            ]
        }

        mock_plan_run.side_effect = [initial_plan, replanned]
        mock_invoke_tool.side_effect = [(failed_tool, 10), (ok_tool, 15)]

        url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["replan_count"], 1)
        # plan_run se llamó dos veces: plan inicial + replan
        self.assertEqual(mock_plan_run.call_count, 2)
        # La segunda llamada a plan_run recibe execution_context con replan_reason
        _, kwargs = mock_plan_run.call_args_list[1]
        exec_ctx = kwargs.get("execution_context") or mock_plan_run.call_args_list[1][0][2]
        self.assertEqual(exec_ctx["replan_reason"], "tool_failed")
        self.assertIn("layer not found", exec_ctx["replan_hint"])

    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis sin replan", "final_sql": ""})
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_tool_failure_with_continue_policy_does_not_replan(
        self, mock_plan_run, mock_invoke_tool, _mock_synthesize
    ):
        """Un tool que falla con on_fail=continue NO debe disparar replan."""
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "consulta con fallo no crítico"},
        )

        failed_tool = SimpleNamespace(ok=False, data={}, error="no data")
        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_lines"},
                    "required": False,
                    "on_fail": "continue",
                    "can_replan": False,
                },
                {"type": "final"},
            ]
        }
        mock_invoke_tool.return_value = (failed_tool, 5)

        url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["replan_count"], 0)
        # plan_run se llamó solo una vez (no replan)
        self.assertEqual(mock_plan_run.call_count, 1)

    # ── Tool call directo: persiste memoria y episodio ───────────────────────
    # Nota: los tool calls directos no pasan por el ciclo de verificación del
    # planner (no hay success_criteria). El runner devuelve el resultado raw
    # con verification_summary en cero y persiste RunMemory/Episode básicos.

    @patch("agents_core.runner.invoke_tool")
    def test_direct_tool_call_persists_memory_and_episode(self, mock_invoke_tool):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={
                "goal": "trazar red directamente",
                "tool_call": {
                    "name": "spatial.network_trace",
                    "args": {
                        "layer": "demo_lines",
                        "start_point": {"lon": -6.06, "lat": 37.3201},
                        "end_point": {"lon": -6.051, "lat": 37.3299},
                        "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
                        "include_geom": True,
                        "max_snap_distance_m": 20,
                    },
                },
            },
        )
        mock_invoke_tool.return_value = (
            _tool_ok({
                "layer": "demo_lines",
                "path_found": False,
                "reason": "snap_distance_exceeded",
                "start_point": {"lon": -6.06, "lat": 37.3201},
                "end_point": {"lon": -6.051, "lat": 37.3299},
                "start_snap_m": 109.40,
                "end_snap_m": 417.54,
                "segment_ids": [],
                "segment_names": [],
                "total_length_m": 0.0,
                "node_count": 0,
                "include_geom": True,
            }),
            10,
        )

        execute_url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(execute_url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")

        # Los tool calls directos no ejecutan el ciclo de verificación del planner:
        # no hay success_criteria → verification_summary en cero y executed_outputs vacío.
        self.assertEqual(response.data["verification_summary"]["counts"]["refuted"], 0)
        self.assertEqual(response.data["verification_summary"]["counts"]["verified"], 0)
        self.assertEqual(response.data["executed_outputs"], [])
        self.assertEqual(response.data["output_json"]["tool"], "spatial.network_trace")
        self.assertFalse(response.data["output_json"]["data"]["path_found"])

        # RunMemory y Episode se crean igualmente pero sin datos de verificación.
        run.refresh_from_db()
        self.assertIsNotNone(run.memory)
        self.assertIsNotNone(run.episode)
        self.assertEqual(run.memory.verification_status, "not_evaluated")
        self.assertEqual(run.episode.verification_status, "not_evaluated")
        self.assertTrue(run.episode.success)  # ok=True, no refutado


# ── Paralelismo de steps ─────────────────────────────────────────────────────

class ParallelStepsTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="par_user", password="x")
        self.token = Token.objects.create(user=self.user)
        self.agent = Agent.objects.create(
            name="par-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=["spatial.query_layer", "spatial.nearby"],
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis paralela", "final_sql": ""})
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_independent_steps_execute_and_collect_both_results(
        self, mock_plan_run, mock_invoke_tool, _mock_synthesize
    ):
        """Dos steps sin depends_on entre sí se ejecutan en la misma wave y ambos aparecen en output."""
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "Consulta dos capas independientes"},
        )
        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points"},
                    "required": True,
                    "depends_on": [],
                    "on_fail": "continue",
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.nearby",
                    "args": {"layer": "demo_points", "point": {"lon": -6.0, "lat": 37.0}, "radius_m": 50},
                    "required": True,
                    "depends_on": [],  # sin dependencia: puede ir en paralelo
                    "on_fail": "continue",
                },
                {"type": "final"},
            ]
        }
        mock_invoke_tool.return_value = (
            _tool_ok({"items": [{"id": 1}], "count_total": 1}),
            10,
        )

        url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(len(response.data["executed_outputs"]), 2)
        names = {s["name"] for s in response.data["executed_outputs"]}
        self.assertIn("spatial.query_layer", names)
        self.assertIn("spatial.nearby", names)

    @patch("agents_core.runner.synthesize_run", return_value={"final_text": "síntesis secuencial", "final_sql": ""})
    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    def test_dependent_steps_execute_sequentially(
        self, mock_plan_run, mock_invoke_tool, _mock_synthesize
    ):
        """Un step con depends_on en otro va en una wave posterior (secuencial respecto al primero)."""
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "Primero localiza, luego busca cerca"},
        )
        mock_plan_run.return_value = {
            "steps": [
                {
                    "id": "s1",
                    "type": "tool",
                    "name": "spatial.query_layer",
                    "args": {"layer": "demo_points"},
                    "required": True,
                    "depends_on": [],
                    "on_fail": "continue",
                },
                {
                    "id": "s2",
                    "type": "tool",
                    "name": "spatial.nearby",
                    "args": {
                        "layer": "demo_points",
                        "point": {"lon": "$step:s1.data.items.0.lon", "lat": "$step:s1.data.items.0.lat"},
                        "radius_m": 50,
                    },
                    "required": True,
                    "depends_on": ["s1"],  # secuencial
                    "on_fail": "continue",
                },
                {"type": "final"},
            ]
        }
        mock_invoke_tool.return_value = (
            _tool_ok({"items": [{"id": 1, "lon": -6.0, "lat": 37.0}], "count_total": 1}),
            10,
        )

        url = reverse("runs-execute", kwargs={"pk": run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["executed_outputs"]), 2)
        # s1 debe aparecer antes que s2
        ids = [s["id"] for s in response.data["executed_outputs"]]
        self.assertEqual(ids, ["s1", "s2"])


# ── Multi-turno (session_id) ─────────────────────────────────────────────────

class SessionContextTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="ses_user", password="x")
        self.token = Token.objects.create(user=self.user)
        self.agent = Agent.objects.create(
            name="ses-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=["spatial.query_layer"],
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_run_accepts_session_id(self):
        url = reverse("runs-list")
        response = self.client.post(url, {
            "agent": self.agent.id,
            "session_id": "test-session-42",
            "input_json": {"goal": "primera consulta"},
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["session_id"], "test-session-42")

    def test_run_session_id_persists(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            session_id="ses-abc",
            input_json={"goal": "primera"},
        )
        run.refresh_from_db()
        self.assertEqual(run.session_id, "ses-abc")

    def test_session_context_returns_previous_runs(self):
        """_build_session_context devuelve historial condensado de runs previos en la sesión."""
        from agents_llm.planner import _build_session_context

        # Primer run (succeeded) en la sesión
        run1 = Run.objects.create(
            agent=self.agent,
            user=self.user,
            session_id="ses-hist",
            status="succeeded",
            input_json={"goal": "primer turno"},
            final_text="resultado del primer turno",
            output_json={"executed_outputs": [
                {"type": "tool", "name": "spatial.query_layer", "ok": True}
            ]},
        )
        # Segundo run (el actual, no debe aparecer en el historial)
        run2 = Run.objects.create(
            agent=self.agent,
            user=self.user,
            session_id="ses-hist",
            status="queued",
            input_json={"goal": "segundo turno"},
        )

        history = _build_session_context(run2)
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["run_id"], run1.pk)
        self.assertEqual(history[0]["goal"], "primer turno")
        self.assertIn("resultado del primer turno", history[0]["final_text"])
        self.assertIn("spatial.query_layer", history[0]["tools_used"])

    def test_session_context_empty_without_session_id(self):
        """Sin session_id, _build_session_context devuelve None."""
        from agents_llm.planner import _build_session_context

        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "sin sesión"},
        )
        self.assertIsNone(_build_session_context(run))
