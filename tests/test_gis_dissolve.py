"""
Tests para spatial.dissolve — unitarios (mocks).

Ejecutar:
    python manage.py test tests.test_gis_dissolve
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


def _make_layer(name="parcelas", fields=None, filter_fields=None):
    fields = fields or ["propietario", "tipo", "area_ha"]
    filter_fields = filter_fields or ["propietario", "tipo"]
    return {
        "name": name,
        "table": name,
        "geom_col": "the_geom",
        "id_col": "fid",
        "geometry_kind": "polygon",
        "srid": 4326,
        "fields": fields,
        "filter_fields": filter_fields,
    }


def _make_mock_conn(total_groups=3, groups=None):
    if groups is None:
        groups = [
            ("Martínez", 5, 12500.0),
            ("García", 3, 8000.0),
            ("López", 1, 2300.0),
        ]
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)

    fetchone_calls = [0]

    def fetchone_side():
        fetchone_calls[0] += 1
        return [total_groups]

    mock_cursor.fetchone = MagicMock(side_effect=fetchone_side)
    mock_cursor.description = [("propietario",), ("feature_count",), ("dissolved_area_m2",)]
    mock_cursor.fetchall = MagicMock(return_value=groups)
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    return mock_conn


class DissolveToolUnitTests(SimpleTestCase):

    def _invoke(self, args, layer=None):
        from agents_gis.tools_dissolve import SpatialDissolveTool
        layer_cfg = layer or _make_layer()
        tool = SpatialDissolveTool()
        mock_conn = _make_mock_conn()
        with patch("agents_gis.tools_dissolve._get_layer_cfg", return_value=layer_cfg), \
             patch("agents_gis.tools_dissolve.get_gis_connection", return_value=mock_conn):
            return tool.invoke(args=args)

    def test_basic_dissolve_returns_dissolved_features(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("dissolved_features", result.data)
        self.assertEqual(result.data["dissolve_field"], "propietario")
        self.assertEqual(result.data["total_groups"], 3)

    def test_unknown_layer_returns_error(self):
        from agents_gis.tools_dissolve import SpatialDissolveTool
        tool = SpatialDissolveTool()
        with patch("agents_gis.tools_dissolve._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "nonexistent", "dissolve_field": "tipo"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown layer", result.error)

    def test_missing_layer_returns_error(self):
        from agents_gis.tools_dissolve import SpatialDissolveTool
        tool = SpatialDissolveTool()
        with patch("agents_gis.tools_dissolve._get_layer_cfg", return_value=_make_layer()):
            result = tool.invoke(args={"layer": "", "dissolve_field": "propietario"})
        self.assertFalse(result.ok)
        self.assertIn("layer is required", result.error)

    def test_missing_dissolve_field_returns_error(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": ""})
        self.assertFalse(result.ok)
        self.assertIn("dissolve_field is required", result.error)

    def test_disallowed_dissolve_field_returns_error(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "area_ha"})
        self.assertFalse(result.ok)
        self.assertIn("dissolve_field not allowed", result.error)

    def test_limit_clamped(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario", "limit": 9999})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["limit"], 200)

    def test_limit_minimum(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario", "limit": -5})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["limit"], 1)

    def test_include_geom_false_by_default(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario"})
        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.data["include_geom"])

    def test_include_geom_true_passed_through(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario", "include_geom": True})
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.data["include_geom"])

    def test_invalid_agg_func_returns_error(self):
        result = self._invoke({
            "layer": "parcelas",
            "dissolve_field": "propietario",
            "aggs": [{"field": "area_ha", "func": "count"}],  # count no está permitido
        })
        self.assertFalse(result.ok)
        self.assertIn("func must be one of", result.error)

    def test_agg_field_not_in_layer_returns_error(self):
        result = self._invoke({
            "layer": "parcelas",
            "dissolve_field": "propietario",
            "aggs": [{"field": "campo_inexistente", "func": "sum"}],
        })
        self.assertFalse(result.ok)
        self.assertIn("agg field not in layer fields", result.error)

    def test_valid_agg_passes(self):
        result = self._invoke({
            "layer": "parcelas",
            "dissolve_field": "propietario",
            "aggs": [{"field": "area_ha", "func": "sum", "alias": "area_total"}],
        })
        self.assertTrue(result.ok, result.error)

    def test_invalid_filter_field_returns_error(self):
        result = self._invoke({
            "layer": "parcelas",
            "dissolve_field": "propietario",
            "filters": {"campo_no_permitido": "valor"},
        })
        self.assertFalse(result.ok)
        self.assertIn("filter not allowed", result.error)

    def test_valid_filter_passes(self):
        result = self._invoke({
            "layer": "parcelas",
            "dissolve_field": "propietario",
            "filters": {"tipo": "urbano"},
        })
        self.assertTrue(result.ok, result.error)

    def test_result_data_has_expected_keys(self):
        result = self._invoke({"layer": "parcelas", "dissolve_field": "propietario"})
        self.assertTrue(result.ok, result.error)
        for key in ("layer", "dissolve_field", "total_groups", "dissolved_features", "include_geom", "limit"):
            self.assertIn(key, result.data)
