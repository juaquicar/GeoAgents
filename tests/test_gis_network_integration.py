"""
Tests de integración GIS con BD real (BD de test local de Django).

Los tests crean una tabla PostGIS temporal en la BD de test y ejecutan
las tools reales contra ella. El Agent se configura con gis_layers_catalog
apuntando a esa tabla y gis_db_connections=[] (usa el alias 'default' de Django,
que en tests apunta a la BD de test local automáticamente).

Ejecutar:
    python manage.py test tests.test_gis_network_integration

Requisito: la BD de test debe tener la extensión PostGIS instalada.
"""
import agents_gis.tools_network_trace  # noqa: F401 — registro de tools

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.signals import request_finished
from django.db import close_old_connections, connection
from django.test import override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from agents_core.models import Agent, Run


TEST_TABLE = "test_network_lines_api"
TEST_LAYER_NAME = "test_network_lines"
TEST_BBOX = {
    "west": -6.001,
    "south": 36.999,
    "east": -5.999,
    "north": 37.004,
}

# Catálogo del agente que apunta a la tabla de test local
TEST_LAYER_CATALOG = [
    {
        "name": TEST_LAYER_NAME,
        "table": TEST_TABLE,
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name", "segment_type"],
        "filter_fields": ["name", "segment_type"],
        "geometry_kind": "line",
        "srid": 4326,
    }
]


@override_settings(AGENTS_GIS_DB_ALIAS="default", AGENTS_GIS_SCHEMA="public")
class NetworkServiceAreaRealIntegrationApiTests(APITestCase):
    """
    Integración real contra la BD de test local (alias 'default').
    El Agent tiene gis_db_connections=[] → get_gis_connection() usa el alias
    global AGENTS_GIS_DB_ALIAS. En producción puede ser 'gis_remote'; el
    decorador @override_settings lo fuerza a 'default' para estos tests.

    close_old_connections() se neutraliza de dos formas:
    - Parcheado en agents_gis.service para que no cierre la conexión durante
      la ejecución de tools.
    - Señal request_finished desconectada para que no se cierre tras la petición.
    Ambas son necesarias porque la conexión de test está en una transacción
    envolvente que no debe cerrarse entre tests.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # close_old_connections() se llama en dos lugares distintos durante los tests:
        # 1. En agents_gis.service.get_gis_connection() durante la ejecución de tools.
        # 2. En la señal request_finished al terminar cada petición HTTP del test client.
        # En ambos casos cierra la conexión de test de Django (que está dentro de una
        # transacción envolvente), rompiendo los tests siguientes.
        # Solución: parchear el símbolo en service y desconectar la señal.
        cls._patcher = patch("agents_gis.service.close_old_connections", lambda: None)
        cls._patcher.start()
        request_finished.disconnect(close_old_connections)
        with connection.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE};")
            cur.execute(
                f"""
                CREATE TABLE {TEST_TABLE} (
                    id integer PRIMARY KEY,
                    name varchar(100) NOT NULL,
                    segment_type varchar(50),
                    the_geom geometry(LineString, 4326) NOT NULL
                );
                """
            )
            # Red de prueba:
            # 1: A-B slow  (lento, coste alto)
            # 2: B-C slow
            # 3: A-C fiber (atajo barato con multiplicador fiber)
            # 4: C-D fiber
            cur.execute(
                f"""
                INSERT INTO {TEST_TABLE} (id, name, segment_type, the_geom) VALUES
                (1, 'A-B slow', 'slow',  ST_GeomFromText('LINESTRING(-6.0 37.0, -6.0 37.001)', 4326)),
                (2, 'B-C slow', 'slow',  ST_GeomFromText('LINESTRING(-6.0 37.001, -6.0 37.002)', 4326)),
                (3, 'A-C fiber','fiber', ST_GeomFromText('LINESTRING(-6.0 37.0, -6.0 37.002)', 4326)),
                (4, 'C-D fiber','fiber', ST_GeomFromText('LINESTRING(-6.0 37.002, -6.0 37.003)', 4326));
                """
            )

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        request_finished.connect(close_old_connections)
        try:
            with connection.cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE};")
        finally:
            super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="real_network_api_user",
            email="real_network_api_user@example.com",
            password="secret123",
        )
        self.other_user = User.objects.create_user(
            username="real_network_api_other",
            email="real_network_api_other@example.com",
            password="secret123",
        )

        self.token = Token.objects.create(user=self.user)
        self.other_token = Token.objects.create(user=self.other_user)

        # Agent con catálogo de la tabla de test y sin gis_db_connections
        # → get_gis_connection() usa el alias 'default' (= BD de test local)
        self.agent = Agent.objects.create(
            name="real-network-api-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=[
                "spatial.network_service_area",
                "spatial.route_cost",
                "spatial.network_trace",
            ],
            gis_db_connections=[],
            gis_layers_catalog=TEST_LAYER_CATALOG,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        self.origin_a = {"lon": -6.0, "lat": 37.0}
        self.node_b   = {"lon": -6.0, "lat": 37.001}
        self.node_c   = {"lon": -6.0, "lat": 37.002}
        self.node_d   = {"lon": -6.0, "lat": 37.003}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _create_run(self, payload):
        response = self.client.post(reverse("runs-list"), payload, format="json")
        self.assertEqual(response.status_code, 201)
        return response

    def _execute_run(self, run_id):
        response = self.client.post(
            reverse("runs-execute", kwargs={"pk": run_id}), {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _run_direct_tool(self, tool_name, args, goal):
        create_response = self._create_run({
            "agent": self.agent.id,
            "input_json": {
                "goal": goal,
                "tool_call": {"name": tool_name, "args": args},
            },
        })
        run_id = create_response.data["id"]
        execute_response = self._execute_run(run_id)
        return run_id, execute_response

    # ── Tests ────────────────────────────────────────────────────────────────

    def test_service_area_distance_limit_contracts_on_real_network(self):
        """Área de servicio corta (150 m) solo alcanza nodo B; larga (230 m) alcanza A, B, C."""
        _, short_response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "length",
                "max_distance_m": 150,
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area corto por distancia",
        )

        short_data = short_response.data["output_json"]["data"]
        self.assertTrue(short_response.data["output_json"]["ok"], short_response.data["output_json"])
        self.assertTrue(short_data["reachable"])
        self.assertEqual(short_data["metric"], "length")
        self.assertEqual(short_data["limits"]["max_distance_m"], 150.0)
        self.assertEqual(short_data["reachable_node_count"], 2)
        self.assertEqual(short_data["reachable_segment_count"], 1)
        self.assertCountEqual(short_data["reachable_segment_ids"], [1])
        self.assertEqual(short_data["coverage_bbox"]["south"], 37.0)
        self.assertEqual(short_data["coverage_bbox"]["north"], 37.001)

        _, larger_response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "length",
                "max_distance_m": 230,
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area mayor por distancia",
        )

        larger_data = larger_response.data["output_json"]["data"]
        self.assertTrue(larger_data["reachable"])
        self.assertEqual(larger_data["reachable_node_count"], 3)
        self.assertEqual(larger_data["reachable_segment_count"], 3)
        self.assertCountEqual(larger_data["reachable_segment_ids"], [1, 2, 3])
        self.assertEqual(larger_data["coverage_bbox"]["north"], 37.002)

    def test_service_area_cost_respects_segment_type_weights_on_real_network(self):
        """Con fiber×0.5 y max_cost=120, llega a C por el atajo fiber pero no a B por el slow."""
        _, response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "cost",
                "max_cost": 120,
                "length_weight": 1.0,
                "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area por coste con multiplicadores",
        )

        data = response.data["output_json"]["data"]
        self.assertTrue(data["reachable"])
        self.assertEqual(data["metric"], "cost")
        self.assertEqual(data["limits"]["max_cost"], 120.0)
        self.assertEqual(data["reachable_node_count"], 2)
        self.assertEqual(data["reachable_segment_count"], 1)
        self.assertCountEqual(data["reachable_segment_ids"], [3])

        reachable_nodes = {(n["lon"], n["lat"]) for n in data["reachable_nodes"]}
        self.assertIn((-6.0, 37.0), reachable_nodes)
        self.assertIn((-6.0, 37.002), reachable_nodes)
        self.assertNotIn((-6.0, 37.001), reachable_nodes)

    def test_service_area_and_route_cost_are_consistent_on_same_threshold(self):
        """El área de servicio con coste = coste de ruta A→C debe alcanzar C."""
        _, route_response = self._run_direct_tool(
            "spatial.route_cost",
            {
                "layer": TEST_LAYER_NAME,
                "start_point": self.origin_a,
                "end_point": self.node_c,
                "metric": "cost",
                "length_weight": 1.0,
                "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "route cost A-C",
        )

        route_data = route_response.data["output_json"]["data"]
        self.assertTrue(route_data["path_found"])
        self.assertCountEqual(route_data["segment_ids"], [3])

        route_total_cost = float(route_data["total_cost"])

        _, service_area_response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "cost",
                "max_cost": route_total_cost + 0.001,
                "length_weight": 1.0,
                "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area consistente con route_cost",
        )

        area_data = service_area_response.data["output_json"]["data"]
        self.assertTrue(area_data["reachable"])
        route_segments = set(route_data["segment_ids"])
        reachable_segments = set(area_data["reachable_segment_ids"])
        self.assertTrue(route_segments.issubset(reachable_segments))

        reachable_nodes = {(n["lon"], n["lat"]) for n in area_data["reachable_nodes"]}
        route_end_snap_node = (
            route_data["end_snap_node"]["lon"],
            route_data["end_snap_node"]["lat"],
        )
        self.assertIn(route_end_snap_node, reachable_nodes)

    def test_service_area_restrictions_change_real_coverage(self):
        """Prohibir el segmento fiber hace que no se alcance C con max_cost=120."""
        _, unrestricted_response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "cost",
                "max_cost": 120,
                "length_weight": 1.0,
                "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area sin restricciones",
        )
        self.assertCountEqual(
            unrestricted_response.data["output_json"]["data"]["reachable_segment_ids"], [3]
        )

        _, restricted_response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": self.origin_a,
                "metric": "cost",
                "max_cost": 120,
                "length_weight": 1.0,
                "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                "restrictions": {"forbidden_segment_ids": [3]},
                "max_snap_distance_m": 5,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area con atajo prohibido",
        )

        restricted_data = restricted_response.data["output_json"]["data"]
        self.assertTrue(restricted_data["reachable"])
        self.assertEqual(restricted_data["reachable_node_count"], 1)
        self.assertEqual(restricted_data["reachable_segment_count"], 0)
        self.assertEqual(restricted_data["reachable_segment_ids"], [])
        reachable_nodes = {(n["lon"], n["lat"]) for n in restricted_data["reachable_nodes"]}
        self.assertEqual(reachable_nodes, {(-6.0, 37.0)})

    def test_service_area_returns_snap_distance_exceeded_on_real_network(self):
        """Un origen muy lejano con max_snap=20 m devuelve snap_distance_exceeded."""
        _, response = self._run_direct_tool(
            "spatial.network_service_area",
            {
                "layer": TEST_LAYER_NAME,
                "origin_point": {"lon": -6.2, "lat": 37.2},
                "metric": "cost",
                "max_cost": 300,
                "max_snap_distance_m": 20,
                "bbox": TEST_BBOX,
                "include_geom": False,
            },
            "service area con origen muy alejado",
        )

        self.assertEqual(response.data["status"], "succeeded")
        self.assertTrue(response.data["output_json"]["ok"])
        data = response.data["output_json"]["data"]
        self.assertFalse(data["reachable"])
        self.assertEqual(data["reason"], "snap_distance_exceeded")

    def test_execute_direct_service_area_forbidden_for_other_user_run(self):
        foreign_run = Run.objects.create(
            agent=self.agent,
            user=self.other_user,
            input_json={
                "goal": "run ajeno real",
                "tool_call": {
                    "name": "spatial.network_service_area",
                    "args": {
                        "layer": TEST_LAYER_NAME,
                        "origin_point": self.origin_a,
                        "max_cost": 300,
                        "bbox": TEST_BBOX,
                    },
                },
            },
        )
        response = self.client.post(
            reverse("runs-execute", kwargs={"pk": foreign_run.id}), {}, format="json"
        )
        self.assertEqual(response.status_code, 404)
