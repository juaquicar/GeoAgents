"""
Tests de introspección GIS (inspect_agent_gis).

Se distinguen dos bloques:
1. Tests unitarios con mocks (siempre ejecutan).
2. Tests de integración contra la BD remota real (solo si GIS_REMOTE_DB_HOST está en el entorno).

BD remota de referencia (span + struct en schema planex):
    Host:     82.223.78.166
    Puerto:   5432
    DB:       tesa
    Usuario:  postgres
    Schema:   planex

Ejecutar todos:
    python manage.py test tests.test_gis_inspect

Solo unitarios:
    python manage.py test tests.test_gis_inspect.InspectAgentGisUnitTests

Solo integración:
    python manage.py test tests.test_gis_inspect.InspectAgentGisRemoteIntegrationTests
"""
import os
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch, call

from agents_gis.inspect import inspect_agent_gis, _infer_geometry_kind, _infer_id_col


# ── Tests unitarios ──────────────────────────────────────────────────────────

class InspectHelperTests(TestCase):
    def test_infer_geometry_kind_point(self):
        self.assertEqual(_infer_geometry_kind("POINT"), "point")
        self.assertEqual(_infer_geometry_kind("MULTIPOINT"), "point")

    def test_infer_geometry_kind_line(self):
        self.assertEqual(_infer_geometry_kind("LINESTRING"), "line")
        self.assertEqual(_infer_geometry_kind("MULTILINESTRING"), "line")
        self.assertEqual(_infer_geometry_kind("LINESTRINGZ"), "line")

    def test_infer_geometry_kind_polygon(self):
        self.assertEqual(_infer_geometry_kind("POLYGON"), "polygon")
        self.assertEqual(_infer_geometry_kind("MULTIPOLYGON"), "polygon")

    def test_infer_geometry_kind_unknown_defaults_to_point(self):
        self.assertEqual(_infer_geometry_kind(""), "point")
        self.assertEqual(_infer_geometry_kind("UNKNOWN_TYPE"), "point")

    def test_infer_id_col_prefers_known_names(self):
        cols = [{"name": "gid", "data_type": "integer"}, {"name": "name", "data_type": "text"}]
        self.assertEqual(_infer_id_col(cols), "gid")

    def test_infer_id_col_falls_back_to_integer_type(self):
        cols = [{"name": "fk_id", "data_type": "integer"}, {"name": "name", "data_type": "text"}]
        self.assertEqual(_infer_id_col(cols), "fk_id")

    def test_infer_id_col_defaults_to_id(self):
        cols = [{"name": "name", "data_type": "text"}]
        self.assertEqual(_infer_id_col(cols), "id")


class InspectAgentGisUnitTests(TestCase):
    """Tests con psycopg2 mockeado — no requieren BD real."""

    def _make_agent(self, connections):
        agent = MagicMock()
        agent.gis_db_connections = connections
        return agent

    def _make_cursor(self, tables, columns):
        """Crea un cursor mock que devuelve tablas y columnas en secuencia."""
        cursor = MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)

        # Primera llamada: _inspect_tables → devuelve tabla(s)
        # Siguientes: _inspect_columns → devuelve columnas
        fetch_returns = [tables] + [columns] * len(tables)
        cursor.fetchall.side_effect = fetch_returns

        # description para _fetchall_dict
        if tables:
            cursor.description = [
                ("schema",), ("table_name",), ("geom_col",), ("geom_type",), ("srid",)
            ]
        return cursor

    @patch("agents_gis.inspect.psycopg2")
    def test_inspect_returns_empty_when_no_connections(self, _mock_psycopg2):
        agent = self._make_agent([])
        result = inspect_agent_gis(agent)
        self.assertEqual(result, [])

    @patch("agents_gis.inspect.psycopg2")
    def test_inspect_raises_runtime_error_on_connection_failure(self, mock_psycopg2):
        mock_psycopg2.connect.side_effect = Exception("connection refused")
        agent = self._make_agent([{
            "alias": "main", "host": "bad-host", "port": 5432,
            "db_name": "db", "user": "u", "password": "p", "schema": "public",
        }])
        with self.assertRaises(RuntimeError) as ctx:
            inspect_agent_gis(agent)
        self.assertIn("bad-host", str(ctx.exception))

    @patch("agents_gis.inspect.psycopg2")
    def test_inspect_returns_catalog_with_correct_fields(self, mock_psycopg2):
        raw_conn = MagicMock()
        mock_psycopg2.connect.return_value = raw_conn

        # Simular dos llamadas al cursor context manager
        cur_tables = MagicMock()
        cur_tables.__enter__ = lambda s: s
        cur_tables.__exit__ = MagicMock(return_value=False)
        cur_tables.description = [
            ("schema",), ("table_name",), ("geom_col",), ("geom_type",), ("srid",)
        ]
        cur_tables.fetchall.return_value = [
            ("planex", "span", "the_geom", "LINESTRING", 4326)
        ]

        cur_cols = MagicMock()
        cur_cols.__enter__ = lambda s: s
        cur_cols.__exit__ = MagicMock(return_value=False)
        cur_cols.description = [("name",), ("data_type",)]
        cur_cols.fetchall.return_value = [
            ("id", "integer"),
            ("name", "character varying"),
            ("the_geom", "geometry"),  # se filtra por _SKIP_TYPES
        ]

        raw_conn.cursor.side_effect = [cur_tables, cur_cols]

        agent = self._make_agent([{
            "alias": "main", "host": "localhost", "port": 5432,
            "db_name": "tesa", "user": "postgres", "password": "",
            "schema": "planex",
        }])

        result = inspect_agent_gis(agent)

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["name"], "span")
        self.assertEqual(entry["table"], "span")
        self.assertEqual(entry["geom_col"], "the_geom")
        self.assertEqual(entry["id_col"], "id")
        self.assertEqual(entry["geometry_kind"], "line")
        self.assertEqual(entry["srid"], 4326)
        self.assertEqual(entry["schema"], "planex")
        self.assertEqual(entry["_db_alias"], "main")
        self.assertIn("fields", entry)
        self.assertNotIn("the_geom", entry["fields"])

    @patch("agents_gis.inspect.psycopg2")
    def test_inspect_closes_connection_after_error(self, mock_psycopg2):
        """La conexión debe cerrarse aunque falle la introspección."""
        raw_conn = MagicMock()
        mock_psycopg2.connect.return_value = raw_conn

        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.execute.side_effect = Exception("query failed")
        raw_conn.cursor.return_value = cur

        agent = self._make_agent([{
            "alias": "main", "host": "localhost", "port": 5432,
            "db_name": "db", "user": "u", "password": "p", "schema": "public",
        }])

        with self.assertRaises(Exception):
            inspect_agent_gis(agent)

        raw_conn.close.assert_called_once()

    @patch("agents_gis.inspect.psycopg2")
    def test_inspect_multiple_connections(self, mock_psycopg2):
        """Con dos conexiones se generan catálogos separados con _db_alias correcto."""
        def make_conn(table_name, alias_name):
            raw_conn = MagicMock()
            cur_tables = MagicMock()
            cur_tables.__enter__ = lambda s: s
            cur_tables.__exit__ = MagicMock(return_value=False)
            cur_tables.description = [
                ("schema",), ("table_name",), ("geom_col",), ("geom_type",), ("srid",)
            ]
            cur_tables.fetchall.return_value = [("public", table_name, "geom", "POINT", 4326)]

            cur_cols = MagicMock()
            cur_cols.__enter__ = lambda s: s
            cur_cols.__exit__ = MagicMock(return_value=False)
            cur_cols.description = [("name",), ("data_type",)]
            cur_cols.fetchall.return_value = [("id", "integer")]

            raw_conn.cursor.side_effect = [cur_tables, cur_cols]
            return raw_conn

        mock_psycopg2.connect.side_effect = [
            make_conn("table_a", "conn1"),
            make_conn("table_b", "conn2"),
        ]

        agent = self._make_agent([
            {"alias": "conn1", "host": "h1", "port": 5432, "db_name": "db1", "user": "u", "password": "", "schema": "public"},
            {"alias": "conn2", "host": "h2", "port": 5432, "db_name": "db2", "user": "u", "password": "", "schema": "public"},
        ])

        result = inspect_agent_gis(agent)

        self.assertEqual(len(result), 2)
        aliases = {e["_db_alias"] for e in result}
        self.assertEqual(aliases, {"conn1", "conn2"})


# ── Tests de integración real ────────────────────────────────────────────────

REMOTE_GIS_CONFIGURED = bool(os.getenv("GIS_REMOTE_DB_HOST", "").strip())


@skipUnless(REMOTE_GIS_CONFIGURED, "BD remota GIS no configurada (GIS_REMOTE_DB_HOST vacío)")
class InspectAgentGisRemoteIntegrationTests(TestCase):
    """
    Tests contra la BD remota real (82.223.78.166 / tesa / schema planex).
    Se saltan automáticamente si GIS_REMOTE_DB_HOST no está en el entorno.

    Capas esperadas: span (LINESTRING), struct (POINT o similar).
    """

    def setUp(self):
        self.remote_conn_cfg = {
            "alias":     "main",
            "host":      os.getenv("GIS_REMOTE_DB_HOST", "82.223.78.166"),
            "port":      int(os.getenv("GIS_REMOTE_DB_PORT", "5432")),
            "db_name":   os.getenv("GIS_REMOTE_DB_NAME", "tesa"),
            "user":      os.getenv("GIS_REMOTE_DB_USER", "postgres"),
            "password":  os.getenv("GIS_REMOTE_DB_PASSWORD", ""),
            "schema":    os.getenv("AGENTS_GIS_SCHEMA", "planex"),
            "sslmode":   os.getenv("GIS_REMOTE_DB_SSLMODE", ""),
            "is_default": True,
        }

        agent = MagicMock()
        agent.gis_db_connections = [self.remote_conn_cfg]
        self.agent = agent

    def test_inspect_finds_span_and_struct_layers(self):
        """inspect_agent_gis debe devolver al menos las capas span y struct."""
        catalog = inspect_agent_gis(self.agent)

        names = {entry["name"] for entry in catalog}
        self.assertIn("span", names, f"Capas encontradas: {names}")
        self.assertIn("struct", names, f"Capas encontradas: {names}")

    def test_inspect_span_layer_has_correct_geometry_kind(self):
        """La capa span debe clasificarse como línea."""
        catalog = inspect_agent_gis(self.agent)
        span = next((e for e in catalog if e["name"] == "span"), None)
        self.assertIsNotNone(span, "Capa 'span' no encontrada")
        self.assertEqual(span["geometry_kind"], "line")

    def test_inspect_entries_have_required_fields(self):
        """Cada entrada del catálogo debe tener todos los campos requeridos."""
        catalog = inspect_agent_gis(self.agent)
        required = {"name", "table", "geom_col", "id_col", "fields",
                    "filter_fields", "geometry_kind", "srid", "_db_alias"}
        for entry in catalog:
            missing = required - entry.keys()
            self.assertEqual(missing, set(), f"Faltan campos en '{entry.get('name')}': {missing}")

    def test_inspect_all_entries_have_db_alias_main(self):
        """Todos los entries deben llevar _db_alias = 'main'."""
        catalog = inspect_agent_gis(self.agent)
        for entry in catalog:
            self.assertEqual(entry["_db_alias"], "main", f"Alias incorrecto en '{entry['name']}'")

    def test_inspect_schema_is_set_for_non_public(self):
        """Como el schema es 'planex' (≠ public), debe aparecer en cada entry."""
        catalog = inspect_agent_gis(self.agent)
        for entry in catalog:
            self.assertEqual(entry.get("schema"), "planex",
                             f"Schema ausente o incorrecto en '{entry['name']}'")
