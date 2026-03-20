from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from agents_core.models import Agent, Run, RunStep


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

    def test_runs_endpoint_requires_authentication(self):
        self.client.credentials()
        url = reverse("runs-list")

        response = self.client.get(url)

        self.assertIn(response.status_code, (401, 403))

    def test_create_run_assigns_authenticated_user(self):
        url = reverse("runs-list")
        payload = {
            "agent": self.agent.id,
            "input_json": {
                "goal": "consulta simple",
            },
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, 201)
        run = Run.objects.get(id=response.data["id"])
        self.assertEqual(run.user_id, self.user.id)
        self.assertEqual(run.agent_id, self.agent.id)
        self.assertEqual(run.status, "queued")

    def test_runs_list_only_returns_current_user_runs(self):
        own_run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "run propio"},
        )
        Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={"goal": "run ajeno"},
        )

        url = reverse("runs-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertIn(own_run.id, ids)
        self.assertEqual(len(ids), 1)

    @patch("agents_core.views.execute_run")
    def test_execute_action_runs_and_returns_enriched_run(self, mock_execute_run):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "ejecuta este run"},
        )

        run.status = "succeeded"
        run.final_text = "respuesta final"
        run.output_json = {
            "ok": True,
            "goal": "ejecuta este run",
            "plan": {"steps": [{"id": "s1", "type": "tool", "name": "spatial.query_layer"}, {"type": "final"}]},
            "plan_history": [
                {"label": "initial", "steps": [{"id": "s1", "type": "tool", "name": "spatial.query_layer"}, {"type": "final"}]}
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

    def test_execute_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={"goal": "run ajeno"},
        )

        url = reverse("runs-execute", kwargs={"pk": foreign_run.id})
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_steps_action_returns_persisted_steps(self):
        run = Run.objects.create(
            agent=self.agent,
            user=self.user,
            input_json={"goal": "ver steps"},
        )

        RunStep.objects.create(
            run=run,
            idx=0,
            kind="system",
            name="run.start",
            input_json={"a": 1},
            output_json={"status": "running"},
            latency_ms=0,
            error="",
        )
        RunStep.objects.create(
            run=run,
            idx=1,
            kind="result",
            name="planner.result",
            input_json={"goal": "ver steps"},
            output_json={"ok": True},
            latency_ms=12,
            error="",
        )

        url = reverse("runs-steps", kwargs={"pk": run.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["idx"], 0)
        self.assertEqual(response.data[0]["name"], "run.start")
        self.assertEqual(response.data[1]["idx"], 1)
        self.assertEqual(response.data[1]["name"], "planner.result")

    def test_steps_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={"goal": "run ajeno"},
        )

        url = reverse("runs-steps", kwargs={"pk": foreign_run.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

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
                            {
                                "id": "s1",
                                "type": "tool",
                                "name": "spatial.network_trace",
                            },
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

        RunStep.objects.create(
            run=run,
            idx=0,
            kind="system",
            name="run.start",
            input_json={},
            output_json={"status": "running"},
            latency_ms=0,
            error="",
        )
        RunStep.objects.create(
            run=run,
            idx=1,
            kind="llm",
            name="llm.plan",
            input_json={"goal": "inspeccionar trace"},
            output_json={"steps": [{"id": "s1", "type": "tool"}, {"type": "final"}]},
            latency_ms=0,
            error="",
        )

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
        self.assertEqual(
            response.data["trace"]["verification_summary"]["counts"]["verified"],
            1,
        )
        self.assertEqual(
            response.data["trace"]["stats"]["tool_steps_executed"],
            1,
        )
        self.assertEqual(
            response.data["trace"]["stats"]["total_attempts"],
            2,
        )

    def test_trace_action_cannot_access_other_user_run(self):
        foreign_run = Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={"goal": "run ajeno"},
        )

        url = reverse("runs-trace", kwargs={"pk": foreign_run.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    @patch("agents_core.runner.invoke_tool")
    @patch("agents_core.runner.plan_run")
    @patch("agents_core.runner.synthesize_run", return_value="síntesis desde API")
    def test_full_execute_flow_persists_steps_and_trace_is_visible(
        self,
        _mock_synthesize_run,
        mock_plan_run,
        mock_invoke_tool,
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
            10,
        )

        execute_url = reverse("runs-execute", kwargs={"pk": run.id})
        execute_response = self.client.post(execute_url, {}, format="json")

        self.assertEqual(execute_response.status_code, 200)
        self.assertEqual(execute_response.data["status"], "succeeded")
        self.assertEqual(execute_response.data["verification_summary"]["counts"]["verified"], 1)

        trace_url = reverse("runs-trace", kwargs={"pk": run.id})
        trace_response = self.client.get(trace_url)

        self.assertEqual(trace_response.status_code, 200)
        self.assertGreaterEqual(len(trace_response.data["steps"]), 4)
        self.assertEqual(trace_response.data["trace"]["stats"]["tool_steps_executed"], 1)
        self.assertEqual(
            trace_response.data["trace"]["verification_summary"]["counts"]["verified"],
            1,
        )