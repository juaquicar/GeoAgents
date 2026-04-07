"""
Tests para spatial.aggregate — unitarios (mocks) + integración local.

Ejecutar:
    python manage.py test tests.test_gis_aggregate
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.signals import request_finished
from django.db import close_old_connections, connection
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from django.urls import reverse

from agents_core.models import Agent, Run


# ── Helpers de mock ────────────────────────────────────────────────────────────

def _make_layer(name="span", fields=None, filter_fields=None):
    fields = fields or ["category_n", "type_name", "measured_l", "ducts_avai"]
    filter_fields = filter_fields or fields
    return {
        "name": name,
        "table": name,
        "geom_col": "the_geom",
        "id_col": "fid",
        "geometry_kind": "line",
        "srid": 4326,
        "fields": fields,
        "filter_fields": filter_fields,
    }


# ── Tests unitarios (sin BD) ──────────────────────────────────────────────────

class AggregateToolUnitTests(SimpleTestCase):

    def _invoke(self, args, layer=None):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        layer_cfg = layer or _make_layer()
        tool = SpatialAggregateTool()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone = MagicMock(return_value=[5])
        mock_cursor.description = [("category_n",), ("count",)]
        mock_cursor.fetchall = MagicMock(return_value=[("Underground", 3), ("Aerial", 2)])
        mock_conn.cursor = MagicMock(return_value=mock_cursor)

        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=layer_cfg), \
             patch("agents_gis.tools_aggregate.get_gis_connection", return_value=mock_conn):
            return tool.invoke(args=args)

    def test_basic_group_by_returns_groups(self):
        result = self._invoke({"layer": "span", "group_by": ["category_n"]})
        self.assertTrue(result.ok, result.error)
        self.assertIn("groups", result.data)
        self.assertEqual(result.data["group_by"], ["category_n"])
        self.assertEqual(result.data["total_groups"], 5)

    def test_unknown_layer_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "nonexistent", "group_by": ["category_n"]})
        self.assertFalse(result.ok)
        self.assertIn("Unknown layer", result.error)

    def test_missing_group_by_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=_make_layer()):
            result = tool.invoke(args={"layer": "span", "group_by": []})
        self.assertFalse(result.ok)
        self.assertIn("group_by", result.error)

    def test_group_by_field_not_in_filter_fields_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        layer = _make_layer(filter_fields=["type_name"])
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=layer):
            result = tool.invoke(args={"layer": "span", "group_by": ["category_n"]})
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_more_than_4_group_by_fields_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        layer = _make_layer(filter_fields=["a", "b", "c", "d", "e"])
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=layer):
            result = tool.invoke(args={"layer": "span", "group_by": ["a", "b", "c", "d", "e"]})
        self.assertFalse(result.ok)
        self.assertIn("at most 4", result.error)

    def test_invalid_agg_func_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=_make_layer()):
            result = tool.invoke(args={
                "layer": "span",
                "group_by": ["category_n"],
                "aggs": [{"field": "measured_l", "func": "median"}],
            })
        self.assertFalse(result.ok)
        self.assertIn("func", result.error)

    def test_agg_field_not_in_layer_fields_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=_make_layer()):
            result = tool.invoke(args={
                "layer": "span",
                "group_by": ["category_n"],
                "aggs": [{"field": "nonexistent_field", "func": "sum"}],
            })
        self.assertFalse(result.ok)
        self.assertIn("not in layer fields", result.error)

    def test_filter_on_disallowed_field_returns_error(self):
        from agents_gis.tools_aggregate import SpatialAggregateTool
        tool = SpatialAggregateTool()
        with patch("agents_gis.tools_aggregate._get_layer_cfg", return_value=_make_layer()):
            result = tool.invoke(args={
                "layer": "span",
                "group_by": ["category_n"],
                "filters": {"secret_field": "x"},
            })
        self.assertFalse(result.ok)
        self.assertIn("filter not allowed", result.error)

    def test_with_aggs_and_bbox(self):
        result = self._invoke({
            "layer": "span",
            "group_by": ["category_n"],
            "aggs": [{"field": "measured_l", "func": "sum", "alias": "total_length"}],
            "bbox": {"west": -6.0, "south": 37.0, "east": -5.9, "north": 37.1},
        })
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["aggs"][0]["alias"], "total_length")
        self.assertIsNotNone(result.data["bbox"])

    def test_order_by_options(self):
        for order in ("count_desc", "count_asc", "group_asc"):
            result = self._invoke({
                "layer": "span",
                "group_by": ["category_n"],
                "order_by": order,
            })
            self.assertTrue(result.ok, f"order_by={order} failed: {result.error}")
            self.assertEqual(result.data["order_by"], order)

    def test_limit_clamped_to_200(self):
        result = self._invoke({"layer": "span", "group_by": ["category_n"], "limit": 9999})
        self.assertTrue(result.ok)
        self.assertEqual(result.data["limit"], 200)


# ── Tests de integración local (BD de test de Django) ─────────────────────────

TEST_TABLE = "test_aggregate_spans"
TEST_LAYER_NAME = "test_agg_span"
TEST_BBOX = {"west": -6.001, "south": 36.999, "east": -5.999, "north": 37.004}
TEST_LAYER_CATALOG = [
    {
        "name": TEST_LAYER_NAME,
        "table": TEST_TABLE,
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["category_n", "type_name", "measured_l"],
        "filter_fields": ["category_n", "type_name", "measured_l"],
        "geometry_kind": "line",
        "srid": 4326,
    }
]


@override_settings(AGENTS_GIS_DB_ALIAS="default", AGENTS_GIS_SCHEMA="public")
class AggregateIntegrationTests(APITestCase):
    """
    Integración real contra BD de test local.
    Mismos patrones que test_gis_network_integration:
    - close_old_connections parcheado en agents_gis.service
    - request_finished signal desconectada
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._patcher = patch("agents_gis.service.close_old_connections", lambda: None)
        cls._patcher.start()
        request_finished.disconnect(close_old_connections)

        with connection.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE};")
            cur.execute(f"""
                CREATE TABLE {TEST_TABLE} (
                    id integer PRIMARY KEY,
                    category_n varchar(50),
                    type_name  varchar(50),
                    measured_l float,
                    the_geom   geometry(LineString, 4326) NOT NULL
                );
            """)
            cur.execute(f"""
                INSERT INTO {TEST_TABLE} VALUES
                (1, 'Underground', 'Duct',  100.0, ST_GeomFromText('LINESTRING(-6.0 37.0, -6.0 37.001)', 4326)),
                (2, 'Underground', 'Duct',  120.0, ST_GeomFromText('LINESTRING(-6.0 37.001, -6.0 37.002)', 4326)),
                (3, 'Aerial',      'Cable',  80.0, ST_GeomFromText('LINESTRING(-6.0 37.002, -6.0 37.003)', 4326)),
                (4, 'Underground', 'Pipe',   90.0, ST_GeomFromText('LINESTRING(-6.0 37.0, -6.0 37.003)', 4326));
            """)

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
            username="agg_test_user", password="secret123"
        )
        self.token = Token.objects.create(user=self.user)
        self.agent = Agent.objects.create(
            name="agg-test-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=["spatial.aggregate"],
            gis_db_connections=[],
            gis_layers_catalog=TEST_LAYER_CATALOG,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def _run_tool(self, args, goal="aggregate test"):
        create = self.client.post(reverse("runs-list"), {
            "agent": self.agent.id,
            "input_json": {"goal": goal, "tool_call": {"name": "spatial.aggregate", "args": args}},
        }, format="json")
        self.assertEqual(create.status_code, 201)
        execute = self.client.post(
            reverse("runs-execute", kwargs={"pk": create.data["id"]}), {}, format="json"
        )
        self.assertEqual(execute.status_code, 200)
        return execute

    def test_count_by_category_returns_correct_groups(self):
        resp = self._run_tool({"layer": TEST_LAYER_NAME, "group_by": ["category_n"], "bbox": TEST_BBOX})
        data = resp.data["output_json"]["data"]
        self.assertTrue(resp.data["output_json"]["ok"], resp.data["output_json"])
        groups = {g["category_n"]: g["count"] for g in data["groups"]}
        self.assertEqual(groups["Underground"], 3)
        self.assertEqual(groups["Aerial"], 1)
        self.assertEqual(data["total_groups"], 2)

    def test_count_by_two_fields(self):
        resp = self._run_tool({
            "layer": TEST_LAYER_NAME,
            "group_by": ["category_n", "type_name"],
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        self.assertTrue(data["total_groups"] >= 3)
        keys = {(g["category_n"], g["type_name"]) for g in data["groups"]}
        self.assertIn(("Underground", "Duct"), keys)
        self.assertIn(("Aerial", "Cable"), keys)

    def test_agg_sum_returns_correct_total(self):
        resp = self._run_tool({
            "layer": TEST_LAYER_NAME,
            "group_by": ["category_n"],
            "aggs": [{"field": "measured_l", "func": "sum", "alias": "total_m"}],
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        groups = {g["category_n"]: g for g in data["groups"]}
        self.assertAlmostEqual(groups["Underground"]["total_m"], 310.0, places=1)
        self.assertAlmostEqual(groups["Aerial"]["total_m"], 80.0, places=1)

    def test_order_by_count_desc(self):
        resp = self._run_tool({
            "layer": TEST_LAYER_NAME,
            "group_by": ["category_n"],
            "bbox": TEST_BBOX,
            "order_by": "count_desc",
        })
        groups = resp.data["output_json"]["data"]["groups"]
        self.assertEqual(groups[0]["category_n"], "Underground")

    def test_filter_reduces_groups(self):
        resp = self._run_tool({
            "layer": TEST_LAYER_NAME,
            "group_by": ["type_name"],
            "filters": {"category_n": "Aerial"},
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        self.assertEqual(data["total_groups"], 1)
        self.assertEqual(data["groups"][0]["type_name"], "Cable")

    def test_no_bbox_returns_all_groups(self):
        resp = self._run_tool({"layer": TEST_LAYER_NAME, "group_by": ["category_n"]})
        data = resp.data["output_json"]["data"]
        self.assertEqual(data["total_groups"], 2)
        self.assertIsNone(data["bbox"])
