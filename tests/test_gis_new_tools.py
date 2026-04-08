"""
Tests unitarios (mocks) para las nuevas tools GIS:
  spatial.count_within, spatial.spatial_join, spatial.clip,
  spatial.grid_stats, spatial.difference, spatial.cluster_dbscan

Ejecutar:
    python manage.py test tests.test_gis_new_tools
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_layer(name, fields=None, filter_fields=None, geom_kind="polygon", srid=4326):
    fields = fields or ["nombre", "tipo"]
    filter_fields = filter_fields or fields
    return {
        "name": name, "table": name,
        "geom_col": "the_geom", "id_col": "fid",
        "geometry_kind": geom_kind, "srid": srid,
        "fields": fields, "filter_fields": filter_fields,
    }


def _mock_conn(fetchone_val=None, fetchall_val=None, description=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone = MagicMock(return_value=fetchone_val or [5])
    cur.description = description or [("fid",), ("count_within",)]
    cur.fetchall = MagicMock(return_value=fetchall_val or [])
    conn.cursor = MagicMock(return_value=cur)
    return conn


# ── spatial.count_within ─────────────────────────────────────────────────────

class CountWithinUnitTests(SimpleTestCase):

    def _invoke(self, args, src=None, tgt=None):
        from agents_gis.tools_count_within import SpatialCountWithinTool
        tool = SpatialCountWithinTool()
        src = src or _make_layer("zonas")
        tgt = tgt or _make_layer("farolas", fields=["estado"], filter_fields=["estado"])

        def layer_cfg(name):
            return src if name == "zonas" else tgt if name == "farolas" else None

        with patch("agents_gis.tools_count_within._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_count_within.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(1, "Parque Norte", 5.0, 6.0, 12)],
                 description=[("fid",), ("nombre",), ("centroid_lon",), ("centroid_lat",), ("count_within",)],
             )):
            return tool.invoke(args=args)

    def test_basic_returns_ok(self):
        result = self._invoke({"source_layer": "zonas", "target_layer": "farolas"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("items", result.data)

    def test_missing_source_layer(self):
        from agents_gis.tools_count_within import SpatialCountWithinTool
        tool = SpatialCountWithinTool()
        with patch("agents_gis.tools_count_within._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"source_layer": "", "target_layer": "farolas"})
        self.assertFalse(result.ok)
        self.assertIn("required", result.error)

    def test_unknown_source_layer(self):
        from agents_gis.tools_count_within import SpatialCountWithinTool
        tool = SpatialCountWithinTool()
        with patch("agents_gis.tools_count_within._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"source_layer": "ghost", "target_layer": "farolas"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_invalid_source_filter(self):
        result = self._invoke({
            "source_layer": "zonas", "target_layer": "farolas",
            "source_filters": {"campo_inexistente": "x"},
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_limit_clamped(self):
        result = self._invoke({"source_layer": "zonas", "target_layer": "farolas", "limit": 9999})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["limit"], 200)

    def test_result_keys(self):
        result = self._invoke({"source_layer": "zonas", "target_layer": "farolas"})
        for k in ("source_layer", "target_layer", "items", "count_total"):
            self.assertIn(k, result.data)


# ── spatial.spatial_join ─────────────────────────────────────────────────────

class SpatialJoinUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_spatial_join import SpatialJoinTool
        tool = SpatialJoinTool()
        src = _make_layer("farolas", fields=["estado"], filter_fields=["estado"])
        join = _make_layer("barrios", fields=["nombre_barrio"], filter_fields=["nombre_barrio"])

        def layer_cfg(name):
            return src if name == "farolas" else join if name == "barrios" else None

        with patch("agents_gis.tools_spatial_join._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_spatial_join.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(1, "encendida", 4.5, 6.0, "Centro")],
                 description=[("fid",), ("estado",), ("centroid_lon",), ("centroid_lat",), ("join_nombre_barrio",)],
             )):
            return tool.invoke(args=args)

    def test_contains_mode(self):
        result = self._invoke({
            "source_layer": "farolas", "join_layer": "barrios",
            "join_type": "contains", "join_fields": ["nombre_barrio"],
        })
        self.assertTrue(result.ok, result.error)

    def test_nearest_mode(self):
        result = self._invoke({
            "source_layer": "farolas", "join_layer": "barrios",
            "join_type": "nearest", "join_fields": ["nombre_barrio"],
        })
        self.assertTrue(result.ok, result.error)

    def test_invalid_join_type(self):
        result = self._invoke({
            "source_layer": "farolas", "join_layer": "barrios",
            "join_type": "invalid", "join_fields": ["nombre_barrio"],
        })
        self.assertFalse(result.ok)
        self.assertIn("join_type", result.error)

    def test_disallowed_join_field(self):
        result = self._invoke({
            "source_layer": "farolas", "join_layer": "barrios",
            "join_type": "nearest", "join_fields": ["campo_secreto"],
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_empty_join_fields(self):
        result = self._invoke({
            "source_layer": "farolas", "join_layer": "barrios",
            "join_type": "nearest", "join_fields": [],
        })
        self.assertFalse(result.ok)


# ── spatial.clip ─────────────────────────────────────────────────────────────

class ClipUnitTests(SimpleTestCase):

    def _invoke(self, args, src_layer=None, clip_layer=None):
        from agents_gis.tools_clip import SpatialClipTool
        tool = SpatialClipTool()
        src = src_layer or _make_layer("red", fields=["tipo"], filter_fields=["tipo"])
        clp = clip_layer or _make_layer("parcelas", fields=["ref"], filter_fields=["ref"])

        def layer_cfg(name):
            return src if name == "red" else clp if name == "parcelas" else None

        with patch("agents_gis.tools_clip._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_clip.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(1, "fibra", 250.5, 0.0)],
                 description=[("fid",), ("tipo",), ("clipped_area_m2",), ("clipped_length_m",)],
             )):
            return tool.invoke(args=args)

    def test_clip_with_layer_and_id(self):
        result = self._invoke({
            "source_layer": "red", "clip_layer": "parcelas", "clip_id": 42,
        })
        self.assertTrue(result.ok, result.error)

    def test_clip_with_bbox(self):
        result = self._invoke({
            "source_layer": "red",
            "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
        })
        self.assertTrue(result.ok, result.error)

    def test_no_clip_geometry_fails(self):
        result = self._invoke({"source_layer": "red"})
        self.assertFalse(result.ok)
        self.assertIn("clip_layer", result.error.lower())

    def test_clip_layer_without_id_fails(self):
        result = self._invoke({"source_layer": "red", "clip_layer": "parcelas"})
        self.assertFalse(result.ok)
        self.assertIn("clip_id", result.error)


# ── spatial.grid_stats ───────────────────────────────────────────────────────

class GridStatsUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_grid_stats import SpatialGridStatsTool
        tool = SpatialGridStatsTool()
        layer = _make_layer("incidencias", fields=["tipo"], filter_fields=["tipo"])

        with patch("agents_gis.tools_grid_stats._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_grid_stats.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(2, 3, 5, '{}')],
                 description=[("col",), ("row",), ("count",), ("cell_geom_json",)],
             )):
            return tool.invoke(args=args)

    def test_basic_grid(self):
        result = self._invoke({
            "layer": "incidencias",
            "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
        })
        self.assertTrue(result.ok, result.error)
        self.assertIn("cells", result.data)
        self.assertIn("non_empty_cells", result.data)

    def test_missing_bbox_fails(self):
        result = self._invoke({"layer": "incidencias"})
        self.assertFalse(result.ok)
        self.assertIn("bbox", result.error)

    def test_cell_size_minimum(self):
        result = self._invoke({
            "layer": "incidencias",
            "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
            "cell_size_m": 1,
        })
        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(result.data["cell_size_m"], 10.0)

    def test_result_has_grid_dimensions(self):
        result = self._invoke({
            "layer": "incidencias",
            "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
            "cell_size_m": 50,
        })
        self.assertTrue(result.ok, result.error)
        self.assertIn("grid_cols", result.data)
        self.assertIn("grid_rows", result.data)

    def test_invalid_filter_fails(self):
        result = self._invoke({
            "layer": "incidencias",
            "bbox": {"west": -6.06, "south": 37.32, "east": -6.05, "north": 37.33},
            "filters": {"campo_no_existe": "x"},
        })
        self.assertFalse(result.ok)


# ── spatial.difference ───────────────────────────────────────────────────────

class DifferenceUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_difference import SpatialDifferenceTool
        tool = SpatialDifferenceTool()
        src = _make_layer("parcelas", fields=["ref"], filter_fields=["ref"])
        sub = _make_layer("edificios", fields=["uso"], filter_fields=["uso"])

        def layer_cfg(name):
            return src if name == "parcelas" else sub if name == "edificios" else None

        with patch("agents_gis.tools_difference._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_difference.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(42, "ref-01", 5000.0, 3200.0, 2)],
                 description=[("fid",), ("ref",), ("original_area_m2",), ("difference_area_m2",), ("subtracted_features",)],
             )):
            return tool.invoke(args=args)

    def test_basic_difference(self):
        result = self._invoke({
            "source_layer": "parcelas", "source_id": 42, "subtract_layer": "edificios",
        })
        self.assertTrue(result.ok, result.error)
        self.assertIn("difference_area_m2", result.data)
        self.assertIn("original_area_m2", result.data)

    def test_missing_source_id_fails(self):
        result = self._invoke({"source_layer": "parcelas", "subtract_layer": "edificios"})
        self.assertFalse(result.ok)
        self.assertIn("source_id", result.error)

    def test_invalid_subtract_filter(self):
        result = self._invoke({
            "source_layer": "parcelas", "source_id": 1, "subtract_layer": "edificios",
            "subtract_filters": {"campo_no_existe": "x"},
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)


# ── spatial.cluster_dbscan ───────────────────────────────────────────────────

class ClusterDbscanUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_cluster_dbscan import SpatialClusterDbscanTool
        tool = SpatialClusterDbscanTool()
        layer = _make_layer("incidencias", fields=["tipo"], filter_fields=["tipo"])

        features_rows = [(1, "averia", 5.0, 6.0, 0), (2, "averia", 5.1, 6.1, 0)]
        summary_rows = [(0, 2, 5.05, 6.05, False)]
        call_count = [0]

        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)

        def fetchall_side():
            call_count[0] += 1
            if call_count[0] == 1:
                mock_cur.description = [("fid",), ("tipo",), ("lon",), ("lat",), ("cluster_id",)]
                return features_rows
            mock_cur.description = [("cluster_id",), ("count",), ("centroid_lon",), ("centroid_lat",), ("is_noise",)]
            return summary_rows

        mock_cur.fetchall = MagicMock(side_effect=fetchall_side)
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("agents_gis.tools_cluster_dbscan._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_cluster_dbscan.get_gis_connection", return_value=mock_conn):
            return tool.invoke(args=args)

    def test_basic_cluster(self):
        result = self._invoke({"layer": "incidencias", "eps_m": 50})
        self.assertTrue(result.ok, result.error)
        self.assertIn("cluster_summary", result.data)
        self.assertIn("features", result.data)

    def test_missing_eps_fails(self):
        result = self._invoke({"layer": "incidencias", "eps_m": 0})
        self.assertFalse(result.ok)
        self.assertIn("eps_m", result.error)

    def test_unknown_layer_fails(self):
        from agents_gis.tools_cluster_dbscan import SpatialClusterDbscanTool
        tool = SpatialClusterDbscanTool()
        with patch("agents_gis.tools_cluster_dbscan._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "ghost", "eps_m": 50})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_invalid_filter_fails(self):
        result = self._invoke({
            "layer": "incidencias", "eps_m": 50,
            "filters": {"campo_no_existe": "x"},
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_limit_clamped(self):
        result = self._invoke({"layer": "incidencias", "eps_m": 50, "limit": 9999})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.data["features"].__class__, list)

    def test_result_keys(self):
        result = self._invoke({"layer": "incidencias", "eps_m": 50, "min_points": 2})
        self.assertTrue(result.ok, result.error)
        for k in ("layer", "eps_m", "min_points", "cluster_count", "noise_count", "total_features"):
            self.assertIn(k, result.data)
