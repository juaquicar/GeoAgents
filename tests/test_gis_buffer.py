"""
Tests para spatial.buffer — unitarios (mocks) + integración local.

Ejecutar:
    python manage.py test tests.test_gis_buffer
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.signals import request_finished
from django.db import close_old_connections, connection
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from django.urls import reverse

from agents_core.models import Agent


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_layer(name="span", geom_kind="line", srid=4326):
    return {
        "name": name,
        "table": name,
        "geom_col": "the_geom",
        "id_col": "fid",
        "geometry_kind": geom_kind,
        "srid": srid,
        "fields": ["category_n", "type_name"],
        "filter_fields": ["category_n", "type_name"],
    }


def _mock_invoke(args, target_layer=None, source_layer=None):
    from agents_gis.tools_buffer import SpatialBufferTool
    tool = SpatialBufferTool()
    tl = target_layer or _make_layer("struct", "point")
    sl = source_layer or _make_layer("span", "line")

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone = MagicMock(return_value=[3])
    mock_cur.description = [("fid",), ("category_n",), ("lon",), ("lat",),
                             ("geom_type",), ("geom_dim",), ("length_m",), ("area_m2",), ("distance_m",)]
    mock_cur.fetchall = MagicMock(return_value=[
        (1, "Junction", -6.0, 37.0, "POINT", 0, 0.0, 0.0, 12.5),
        (2, "Cabinet",  -6.0, 37.001, "POINT", 0, 0.0, 0.0, 34.1),
    ])
    mock_conn.cursor = MagicMock(return_value=mock_cur)

    def get_layer(name):
        if name == tl["name"]:
            return tl
        if name == sl["name"]:
            return sl
        return None

    with patch("agents_gis.tools_buffer._get_layer_cfg", side_effect=get_layer), \
         patch("agents_gis.tools_buffer.get_gis_connection", return_value=mock_conn):
        return tool.invoke(args=args)


# ── Tests unitarios ────────────────────────────────────────────────────────────

class BufferToolUnitTests(SimpleTestCase):

    def test_source_point_returns_items(self):
        result = _mock_invoke({
            "target_layer": "struct",
            "buffer_m": 100,
            "source_point": {"lon": -6.0, "lat": 37.0},
        })
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["source"]["type"], "point")
        self.assertEqual(result.data["buffer_m"], 100.0)
        self.assertIn("items", result.data)
        self.assertEqual(result.data["count_total"], 3)

    def test_source_layer_id_returns_items(self):
        result = _mock_invoke({
            "target_layer": "struct",
            "buffer_m": 50,
            "source_layer": "span",
            "source_id": 42,
        })
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["source"]["type"], "layer_element")
        self.assertEqual(result.data["source"]["layer"], "span")
        self.assertEqual(result.data["source"]["id"], 42)

    def test_missing_target_layer_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        with patch("agents_gis.tools_buffer._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"target_layer": "", "buffer_m": 100,
                                       "source_point": {"lon": -6.0, "lat": 37.0}})
        self.assertFalse(result.ok)
        self.assertIn("target_layer", result.error)

    def test_unknown_target_layer_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        with patch("agents_gis.tools_buffer._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"target_layer": "nope", "buffer_m": 100,
                                       "source_point": {"lon": -6.0, "lat": 37.0}})
        self.assertFalse(result.ok)
        self.assertIn("Unknown layer", result.error)

    def test_no_source_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        with patch("agents_gis.tools_buffer._get_layer_cfg", return_value=_make_layer("struct")):
            result = tool.invoke(args={"target_layer": "struct", "buffer_m": 100})
        self.assertFalse(result.ok)
        self.assertIn("source_point", result.error)

    def test_source_layer_without_id_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        with patch("agents_gis.tools_buffer._get_layer_cfg", return_value=_make_layer("struct")):
            result = tool.invoke(args={"target_layer": "struct", "buffer_m": 100,
                                       "source_layer": "span"})
        self.assertFalse(result.ok)
        self.assertIn("source_id", result.error)

    def test_unknown_source_layer_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        def get_layer(name):
            return _make_layer("struct") if name == "struct" else None
        with patch("agents_gis.tools_buffer._get_layer_cfg", side_effect=get_layer):
            result = tool.invoke(args={"target_layer": "struct", "buffer_m": 100,
                                       "source_layer": "nonexistent", "source_id": 1})
        self.assertFalse(result.ok)
        self.assertIn("Unknown source_layer", result.error)

    def test_invalid_filter_returns_error(self):
        from agents_gis.tools_buffer import SpatialBufferTool
        tool = SpatialBufferTool()
        with patch("agents_gis.tools_buffer._get_layer_cfg", return_value=_make_layer("struct")):
            result = tool.invoke(args={"target_layer": "struct", "buffer_m": 50,
                                       "source_point": {"lon": -6.0, "lat": 37.0},
                                       "filters": {"secret": "x"}})
        self.assertFalse(result.ok)
        self.assertIn("filter not allowed", result.error)

    def test_limit_clamped(self):
        result = _mock_invoke({
            "target_layer": "struct",
            "buffer_m": 100,
            "source_point": {"lon": -6.0, "lat": 37.0},
            "limit": 9999,
        })
        self.assertTrue(result.ok)
        self.assertEqual(result.data["limit"], 200)

    def test_with_bbox(self):
        result = _mock_invoke({
            "target_layer": "struct",
            "buffer_m": 100,
            "source_point": {"lon": -6.0, "lat": 37.0},
            "bbox": {"west": -6.01, "south": 36.99, "east": -5.99, "north": 37.01},
        })
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.data["bbox"])


# ── Tests de integración local ─────────────────────────────────────────────────

TEST_LINES_TABLE  = "test_buffer_lines"
TEST_POINTS_TABLE = "test_buffer_points"
TEST_LINES_LAYER  = "test_buf_lines"
TEST_POINTS_LAYER = "test_buf_points"
TEST_BBOX = {"west": -6.005, "south": 36.999, "east": -5.995, "north": 37.005}

TEST_CATALOG = [
    {
        "name": TEST_LINES_LAYER,
        "table": TEST_LINES_TABLE,
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name"],
        "filter_fields": ["name"],
        "geometry_kind": "line",
        "srid": 4326,
    },
    {
        "name": TEST_POINTS_LAYER,
        "table": TEST_POINTS_TABLE,
        "geom_col": "the_geom",
        "id_col": "id",
        "fields": ["name"],
        "filter_fields": ["name"],
        "geometry_kind": "point",
        "srid": 4326,
    },
]


@override_settings(AGENTS_GIS_DB_ALIAS="default", AGENTS_GIS_SCHEMA="public")
class BufferIntegrationTests(APITestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._patcher = patch("agents_gis.service.close_old_connections", lambda: None)
        cls._patcher.start()
        request_finished.disconnect(close_old_connections)

        with connection.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            for tbl in (TEST_LINES_TABLE, TEST_POINTS_TABLE):
                cur.execute(f"DROP TABLE IF EXISTS {tbl};")

            # Red de líneas en ~(−6.0, 37.001)
            cur.execute(f"""
                CREATE TABLE {TEST_LINES_TABLE} (
                    id integer PRIMARY KEY,
                    name varchar(50),
                    the_geom geometry(LineString, 4326) NOT NULL
                );
                INSERT INTO {TEST_LINES_TABLE} VALUES
                (1, 'tramo_central',
                   ST_GeomFromText('LINESTRING(-6.0 37.001, -6.0 37.002)', 4326));
            """)
            # Puntos: algunos cerca del tramo, otros lejos
            cur.execute(f"""
                CREATE TABLE {TEST_POINTS_TABLE} (
                    id integer PRIMARY KEY,
                    name varchar(50),
                    the_geom geometry(Point, 4326) NOT NULL
                );
                INSERT INTO {TEST_POINTS_TABLE} VALUES
                (1, 'cerca_10m',  ST_GeomFromText('POINT(-5.9999 37.0015)', 4326)),
                (2, 'cerca_40m',  ST_GeomFromText('POINT(-5.9996 37.0015)', 4326)),
                (3, 'lejos_500m', ST_GeomFromText('POINT(-5.990  37.001 )', 4326));
            """)

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        request_finished.connect(close_old_connections)
        try:
            with connection.cursor() as cur:
                for tbl in (TEST_LINES_TABLE, TEST_POINTS_TABLE):
                    cur.execute(f"DROP TABLE IF EXISTS {tbl};")
        finally:
            super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="buf_test_user", password="secret")
        self.token = Token.objects.create(user=self.user)
        self.agent = Agent.objects.create(
            name="buf-test-agent",
            profile="investigate",
            is_active=True,
            tool_allowlist=["spatial.buffer"],
            gis_db_connections=[],
            gis_layers_catalog=TEST_CATALOG,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def _run_tool(self, args):
        create = self.client.post(reverse("runs-list"), {
            "agent": self.agent.id,
            "input_json": {"goal": "buffer test",
                           "tool_call": {"name": "spatial.buffer", "args": args}},
        }, format="json")
        self.assertEqual(create.status_code, 201)
        execute = self.client.post(
            reverse("runs-execute", kwargs={"pk": create.data["id"]}), {}, format="json"
        )
        self.assertEqual(execute.status_code, 200)
        return execute

    def test_point_buffer_50m_finds_near_points(self):
        resp = self._run_tool({
            "target_layer": TEST_POINTS_LAYER,
            "buffer_m": 50,
            "source_point": {"lon": -6.0, "lat": 37.0015},
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        self.assertTrue(resp.data["output_json"]["ok"], resp.data["output_json"])
        names = {it["name"] for it in data["items"]}
        self.assertIn("cerca_10m", names)
        self.assertIn("cerca_40m", names)
        self.assertNotIn("lejos_500m", names)

    def test_point_buffer_small_radius_finds_only_closest(self):
        resp = self._run_tool({
            "target_layer": TEST_POINTS_LAYER,
            "buffer_m": 15,
            "source_point": {"lon": -6.0, "lat": 37.0015},
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        names = {it["name"] for it in data["items"]}
        self.assertIn("cerca_10m", names)
        self.assertNotIn("cerca_40m", names)
        self.assertNotIn("lejos_500m", names)

    def test_buffer_from_line_element_finds_nearby_points(self):
        """Buffer alrededor de un tramo (línea) → encuentra puntos cercanos."""
        resp = self._run_tool({
            "target_layer": TEST_POINTS_LAYER,
            "buffer_m": 60,
            "source_layer": TEST_LINES_LAYER,
            "source_id": 1,
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        self.assertTrue(resp.data["output_json"]["ok"], resp.data["output_json"])
        self.assertEqual(data["source"]["type"], "layer_element")
        names = {it["name"] for it in data["items"]}
        self.assertIn("cerca_10m", names)
        self.assertIn("cerca_40m", names)
        self.assertNotIn("lejos_500m", names)

    def test_results_ordered_by_distance_asc(self):
        resp = self._run_tool({
            "target_layer": TEST_POINTS_LAYER,
            "buffer_m": 100,
            "source_point": {"lon": -6.0, "lat": 37.0015},
            "bbox": TEST_BBOX,
        })
        items = resp.data["output_json"]["data"]["items"]
        distances = [it["distance_m"] for it in items if "distance_m" in it]
        self.assertEqual(distances, sorted(distances))

    def test_no_results_within_tiny_radius(self):
        resp = self._run_tool({
            "target_layer": TEST_POINTS_LAYER,
            "buffer_m": 1,
            "source_point": {"lon": -6.0, "lat": 37.0},
            "bbox": TEST_BBOX,
        })
        data = resp.data["output_json"]["data"]
        self.assertTrue(resp.data["output_json"]["ok"])
        self.assertEqual(data["count_total"], 0)
        self.assertEqual(data["items"], [])
