"""
Tests de _build_session_context: construcción del historial de sesión para el planner.

Cubre:
  - Sin session_id → None
  - Sin runs previos → None
  - Run exitoso → ok=True, final_text, tools_used
  - Run fallido → ok=False, tools_tried, error
  - Mezcla de exitosos y fallidos
  - Excluye el run actual
  - Excluye runs de otro agente
  - Límite de 5 runs
  - Orden cronológico ascendente

Ejecutar:
    python manage.py test tests.test_planner_session_context
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from agents_core.models import Agent, Run
from agents_llm.planner import _build_session_context


def _make_agent(name="agent-session-test"):
    return Agent.objects.create(
        name=name,
        system_prompt="",
        is_active=True,
        profile="compact",
        tool_allowlist=["spatial.query_layer"],
    )


def _make_run(agent, session_id, status, goal="test goal", final_text="", output_json=None, error=""):
    return Run.objects.create(
        agent=agent,
        status=status,
        session_id=session_id,
        input_json={"goal": goal},
        final_text=final_text,
        output_json=output_json or {},
        error=error,
    )


class SessionContextNoSessionIdTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-no-session")
        self.run = Run.objects.create(
            agent=self.agent,
            status="queued",
            input_json={"goal": "test"},
        )

    def test_no_session_id_returns_none(self):
        self.assertIsNone(_build_session_context(self.run))

    def test_empty_session_id_returns_none(self):
        self.run.session_id = ""
        self.run.save()
        self.assertIsNone(_build_session_context(self.run))


class SessionContextNoPreviousRunsTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-no-prev")
        self.session_id = str(uuid.uuid4())
        self.run = _make_run(self.agent, self.session_id, "queued")

    def test_no_previous_runs_returns_none(self):
        # Solo existe el run actual — no debe aparecer en el historial
        self.assertIsNone(_build_session_context(self.run))


class SessionContextSucceededRunTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-succeeded")
        self.session_id = str(uuid.uuid4())
        self.prev = _make_run(
            self.agent,
            self.session_id,
            "succeeded",
            goal="busca elementos cercanos",
            final_text="Se encontraron 3 elementos cercanos.",
            output_json={
                "executed_outputs": [
                    {"type": "tool", "name": "spatial.nearby", "ok": True},
                    {"type": "tool", "name": "spatial.query_layer", "ok": False},
                ]
            },
        )
        self.current = _make_run(self.agent, self.session_id, "queued")

    def test_succeeded_run_has_ok_true(self):
        history = _build_session_context(self.current)
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]["ok"])

    def test_succeeded_run_has_final_text(self):
        history = _build_session_context(self.current)
        self.assertIn("final_text", history[0])
        self.assertIn("Se encontraron", history[0]["final_text"])

    def test_succeeded_run_has_only_successful_tools_used(self):
        history = _build_session_context(self.current)
        # tools_used solo incluye tools con ok=True
        self.assertIn("tools_used", history[0])
        self.assertIn("spatial.nearby", history[0]["tools_used"])
        self.assertNotIn("spatial.query_layer", history[0]["tools_used"])

    def test_succeeded_run_has_no_tools_tried(self):
        history = _build_session_context(self.current)
        self.assertNotIn("tools_tried", history[0])

    def test_succeeded_run_has_goal(self):
        history = _build_session_context(self.current)
        self.assertEqual(history[0]["goal"], "busca elementos cercanos")


class SessionContextFailedRunTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-failed")
        self.session_id = str(uuid.uuid4())
        self.prev = _make_run(
            self.agent,
            self.session_id,
            "failed",
            goal="traza una ruta imposible",
            error="No path found between the given points",
            output_json={
                "executed_outputs": [
                    {"type": "tool", "name": "spatial.network_trace", "ok": False},
                    {"type": "tool", "name": "spatial.route_cost", "ok": False},
                    {"type": "final"},
                ]
            },
        )
        self.current = _make_run(self.agent, self.session_id, "queued")

    def test_failed_run_has_ok_false(self):
        history = _build_session_context(self.current)
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 1)
        self.assertFalse(history[0]["ok"])

    def test_failed_run_has_tools_tried(self):
        history = _build_session_context(self.current)
        self.assertIn("tools_tried", history[0])
        self.assertIn("spatial.network_trace", history[0]["tools_tried"])
        self.assertIn("spatial.route_cost", history[0]["tools_tried"])

    def test_failed_run_has_no_tools_used(self):
        history = _build_session_context(self.current)
        self.assertNotIn("tools_used", history[0])

    def test_failed_run_has_error(self):
        history = _build_session_context(self.current)
        self.assertIn("error", history[0])
        self.assertIn("No path found", history[0]["error"])

    def test_failed_run_has_no_final_text(self):
        history = _build_session_context(self.current)
        self.assertNotIn("final_text", history[0])

    def test_failed_run_error_truncated_at_200(self):
        long_error = "x" * 300
        self.prev.error = long_error
        self.prev.save()
        history = _build_session_context(self.current)
        self.assertLessEqual(len(history[0]["error"]), 200)


class SessionContextMixedRunsTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-mixed")
        self.session_id = str(uuid.uuid4())
        self.succeeded = _make_run(
            self.agent, self.session_id, "succeeded",
            goal="busca cercanos",
            final_text="Encontré 5.",
            output_json={"executed_outputs": [{"type": "tool", "name": "spatial.nearby", "ok": True}]},
        )
        self.failed = _make_run(
            self.agent, self.session_id, "failed",
            goal="traza ruta",
            error="No route",
            output_json={"executed_outputs": [{"type": "tool", "name": "spatial.network_trace", "ok": False}]},
        )
        self.current = _make_run(self.agent, self.session_id, "queued")

    def test_both_runs_included(self):
        history = _build_session_context(self.current)
        self.assertIsNotNone(history)
        self.assertEqual(len(history), 2)

    def test_ok_flags_correct(self):
        history = _build_session_context(self.current)
        ok_values = {h["goal"]: h["ok"] for h in history}
        self.assertTrue(ok_values["busca cercanos"])
        self.assertFalse(ok_values["traza ruta"])

    def test_current_run_excluded(self):
        history = _build_session_context(self.current)
        run_ids = [h["run_id"] for h in history]
        self.assertNotIn(self.current.pk, run_ids)

    def test_chronological_order(self):
        history = _build_session_context(self.current)
        self.assertEqual(history[0]["run_id"], self.succeeded.pk)
        self.assertEqual(history[1]["run_id"], self.failed.pk)


class SessionContextIsolationTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-isolation-a")
        self.other_agent = _make_agent("agent-isolation-b")
        self.session_id = str(uuid.uuid4())
        # Run del otro agente con el mismo session_id — no debe aparecer
        _make_run(self.other_agent, self.session_id, "succeeded", goal="otro agente")
        self.current = _make_run(self.agent, self.session_id, "queued")

    def test_other_agent_runs_excluded(self):
        # Sin runs del propio agente, devuelve None
        self.assertIsNone(_build_session_context(self.current))


class SessionContextLimitTests(TestCase):
    def setUp(self):
        self.agent = _make_agent("agent-limit")
        self.session_id = str(uuid.uuid4())
        for i in range(7):
            _make_run(self.agent, self.session_id, "succeeded", goal=f"goal {i}", final_text=f"ok {i}")
        self.current = _make_run(self.agent, self.session_id, "queued")

    def test_max_5_previous_runs(self):
        history = _build_session_context(self.current)
        self.assertIsNotNone(history)
        self.assertLessEqual(len(history), 5)
