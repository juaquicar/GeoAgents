"""
Tests unitarios (mocks) para las 7 nuevas tools GIS:
  spatial.convex_hull, spatial.voronoi, spatial.measure,
  spatial.overlay, spatial.nearest_neighbor,
  spatial.within_distance, spatial.topology_check

Ejecutar:
    python manage.py test tests.test_gis_extra_tools
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
    cur.description = description or [("fid",), ("col",)]
    cur.fetchall = MagicMock(return_value=fetchall_val or [])
    conn.cursor = MagicMock(return_value=cur)
    return conn


# ── spatial.convex_hull ───────────────────────────────────────────────────────

class ConvexHullUnitTests(SimpleTestCase):

    def _invoke(self, args, layer=None):
        from agents_gis.tools_convex_hull import SpatialConvexHullTool
        tool = SpatialConvexHullTool()
        layer = layer or _make_layer("parcelas")

        with patch("agents_gis.tools_convex_hull._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_convex_hull.get_gis_connection", return_value=_mock_conn(
                 fetchone_val=(10, 50000.0, -6.055, 37.325, '{"type":"Polygon","coordinates":[]}'),
                 description=[("feature_count",), ("hull_area_m2",),
                               ("centroid_lon",), ("centroid_lat",), ("hull_geom",)],
             )):
            return tool.invoke(args=args)

    def test_basic_ok(self):
        result = self._invoke({"layer": "parcelas"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("hull_area_m2", result.data)
        self.assertIn("feature_count", result.data)

    def test_missing_layer(self):
        from agents_gis.tools_convex_hull import SpatialConvexHullTool
        tool = SpatialConvexHullTool()
        with patch("agents_gis.tools_convex_hull._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "ghost"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_invalid_filter_fails(self):
        result = self._invoke({"layer": "parcelas", "filters": {"campo_raro": "x"}})
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_no_features_fails(self):
        from agents_gis.tools_convex_hull import SpatialConvexHullTool
        tool = SpatialConvexHullTool()
        layer = _make_layer("parcelas")
        with patch("agents_gis.tools_convex_hull._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_convex_hull.get_gis_connection", return_value=_mock_conn(
                 fetchone_val=(0, None, None, None, None),
                 description=[("feature_count",), ("hull_area_m2",),
                               ("centroid_lon",), ("centroid_lat",), ("hull_geom",)],
             )):
            result = tool.invoke(args={"layer": "parcelas"})
        self.assertFalse(result.ok)

    def test_result_keys(self):
        result = self._invoke({"layer": "parcelas"})
        for k in ("layer", "feature_count", "hull_area_m2", "centroid_lon", "centroid_lat"):
            self.assertIn(k, result.data)

    def test_include_geom_present(self):
        result = self._invoke({"layer": "parcelas", "include_geom": True})
        self.assertTrue(result.ok)
        self.assertIn("hull_geom", result.data)


# ── spatial.voronoi ───────────────────────────────────────────────────────────

class VoronoiUnitTests(SimpleTestCase):

    def _invoke(self, args, layer=None):
        from agents_gis.tools_voronoi import SpatialVoronoiTool
        tool = SpatialVoronoiTool()
        layer = layer or _make_layer("farolas", geom_kind="point")

        with patch("agents_gis.tools_voronoi._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_voronoi.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(1, 1200.0), (2, 1400.0)],
                 description=[("fid",), ("voronoi_area_m2",)],
             )):
            return tool.invoke(args=args)

    def test_basic_ok(self):
        result = self._invoke({"layer": "farolas"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("polygons", result.data)

    def test_non_point_layer_fails(self):
        from agents_gis.tools_voronoi import SpatialVoronoiTool
        tool = SpatialVoronoiTool()
        layer = _make_layer("parcelas", geom_kind="polygon")
        with patch("agents_gis.tools_voronoi._get_layer_cfg", return_value=layer):
            result = tool.invoke(args={"layer": "parcelas"})
        self.assertFalse(result.ok)
        self.assertIn("point", result.error)

    def test_unknown_layer_fails(self):
        from agents_gis.tools_voronoi import SpatialVoronoiTool
        tool = SpatialVoronoiTool()
        with patch("agents_gis.tools_voronoi._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "ghost"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_limit_clamped(self):
        result = self._invoke({"layer": "farolas", "limit": 9999})
        self.assertTrue(result.ok)

    def test_invalid_filter_fails(self):
        result = self._invoke({"layer": "farolas", "filters": {"campo_oculto": "x"}})
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_result_keys(self):
        result = self._invoke({"layer": "farolas"})
        for k in ("layer", "polygon_count", "polygons"):
            self.assertIn(k, result.data)


# ── spatial.measure ───────────────────────────────────────────────────────────

class MeasureUnitTests(SimpleTestCase):

    def _invoke(self, args, layer=None):
        from agents_gis.tools_measure import SpatialMeasureTool
        tool = SpatialMeasureTool()
        layer = layer or _make_layer("red", geom_kind="linestring",
                                     fields=["tipo"], filter_fields=["tipo"])

        with patch("agents_gis.tools_measure._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_measure.get_gis_connection", return_value=_mock_conn(
                 fetchone_val=(25, 12500.0, 500.0, 200.0, 800.0),
                 fetchall_val=[("fibra", 10, 6000.0, 600.0, 200.0, 800.0)],
                 description=[("feature_count",), ("total_length_m",),
                               ("avg_length_m",), ("min_length_m",), ("max_length_m",)],
             )):
            return tool.invoke(args=args)

    def test_basic_line_ok(self):
        result = self._invoke({"layer": "red"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("totals", result.data)
        self.assertEqual(result.data["geometry_type"], "line")

    def test_group_by_ok(self):
        result = self._invoke({"layer": "red", "group_by": "tipo"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("groups", result.data)

    def test_invalid_group_by_fails(self):
        result = self._invoke({"layer": "red", "group_by": "campo_secreto"})
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_unknown_layer_fails(self):
        from agents_gis.tools_measure import SpatialMeasureTool
        tool = SpatialMeasureTool()
        with patch("agents_gis.tools_measure._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "ghost"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_polygon_layer(self):
        from agents_gis.tools_measure import SpatialMeasureTool
        tool = SpatialMeasureTool()
        layer = _make_layer("parcelas", geom_kind="polygon")
        with patch("agents_gis.tools_measure._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_measure.get_gis_connection", return_value=_mock_conn(
                 fetchone_val=(5, 25000.0, 5000.0, 3000.0, 8000.0, 800.0),
                 description=[("feature_count",), ("total_area_m2",), ("avg_area_m2",),
                               ("min_area_m2",), ("max_area_m2",), ("total_perimeter_m",)],
             )):
            result = tool.invoke(args={"layer": "parcelas"})
        self.assertTrue(result.ok)
        self.assertEqual(result.data["geometry_type"], "polygon")

    def test_invalid_filter_fails(self):
        result = self._invoke({"layer": "red", "filters": {"campo_oculto": "x"}})
        self.assertFalse(result.ok)


# ── spatial.overlay ───────────────────────────────────────────────────────────

class OverlayUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_overlay import SpatialOverlayTool
        tool = SpatialOverlayTool()
        layer_a = _make_layer("parcelas", fields=["ref"], filter_fields=["ref"])
        layer_b = _make_layer("edificios", fields=["uso"], filter_fields=["uso"])

        def layer_cfg(name):
            return layer_a if name == "parcelas" else layer_b if name == "edificios" else None

        with patch("agents_gis.tools_overlay._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_overlay.get_gis_connection", return_value=_mock_conn(
                 fetchone_val=(3200.0, False, None),
                 description=[("result_area_m2",), ("is_empty",), ("result_geom",)],
             )):
            return tool.invoke(args=args)

    def test_intersect_mode(self):
        result = self._invoke({"layer_a": "parcelas", "layer_b": "edificios", "mode": "intersect"})
        self.assertTrue(result.ok, result.error)
        self.assertIn("result_area_m2", result.data)

    def test_union_mode(self):
        result = self._invoke({"layer_a": "parcelas", "layer_b": "edificios", "mode": "union"})
        self.assertTrue(result.ok, result.error)

    def test_difference_mode(self):
        result = self._invoke({"layer_a": "parcelas", "layer_b": "edificios", "mode": "difference"})
        self.assertTrue(result.ok, result.error)

    def test_invalid_mode_fails(self):
        result = self._invoke({"layer_a": "parcelas", "layer_b": "edificios", "mode": "magic"})
        self.assertFalse(result.ok)
        self.assertIn("mode", result.error)

    def test_unknown_layer_a_fails(self):
        from agents_gis.tools_overlay import SpatialOverlayTool
        tool = SpatialOverlayTool()
        with patch("agents_gis.tools_overlay._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer_a": "ghost", "layer_b": "edificios", "mode": "intersect"})
        self.assertFalse(result.ok)

    def test_result_keys(self):
        result = self._invoke({"layer_a": "parcelas", "layer_b": "edificios", "mode": "intersect"})
        for k in ("layer_a", "layer_b", "mode", "result_area_m2", "is_empty"):
            self.assertIn(k, result.data)


# ── spatial.nearest_neighbor ─────────────────────────────────────────────────

class NearestNeighborUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_nearest_neighbor import SpatialNearestNeighborTool
        tool = SpatialNearestNeighborTool()
        src = _make_layer("incidencias", fields=["tipo"], filter_fields=["tipo"])
        nbr = _make_layer("farolas", fields=["estado"], filter_fields=["estado"])

        def layer_cfg(name):
            return src if name == "incidencias" else nbr if name == "farolas" else None

        with patch("agents_gis.tools_nearest_neighbor._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_nearest_neighbor.get_gis_connection", return_value=_mock_conn(
                 fetchall_val=[(1, -6.055, 37.32, "averia", 2, -6.056, 37.321, "encendida", 35.5)],
                 description=[("src_fid",), ("src_lon",), ("src_lat",), ("src_tipo",),
                               ("nbr_fid",), ("nbr_lon",), ("nbr_lat",), ("nbr_estado",),
                               ("distance_m",)],
             )):
            return tool.invoke(args=args)

    def test_basic_ok(self):
        result = self._invoke({
            "source_layer": "incidencias", "neighbor_layer": "farolas",
            "neighbor_fields": ["estado"],
        })
        self.assertTrue(result.ok, result.error)
        self.assertIn("pairs", result.data)

    def test_disallowed_neighbor_field_fails(self):
        result = self._invoke({
            "source_layer": "incidencias", "neighbor_layer": "farolas",
            "neighbor_fields": ["campo_secreto"],
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_unknown_source_fails(self):
        from agents_gis.tools_nearest_neighbor import SpatialNearestNeighborTool
        tool = SpatialNearestNeighborTool()
        with patch("agents_gis.tools_nearest_neighbor._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"source_layer": "ghost", "neighbor_layer": "farolas"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_invalid_source_filter_fails(self):
        result = self._invoke({
            "source_layer": "incidencias", "neighbor_layer": "farolas",
            "source_filters": {"campo_oculto": "x"},
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_result_keys(self):
        result = self._invoke({"source_layer": "incidencias", "neighbor_layer": "farolas"})
        for k in ("source_layer", "neighbor_layer", "pair_count", "pairs"):
            self.assertIn(k, result.data)

    def test_limit_clamped(self):
        result = self._invoke({
            "source_layer": "incidencias", "neighbor_layer": "farolas", "limit": 9999,
        })
        self.assertTrue(result.ok)


# ── spatial.within_distance ───────────────────────────────────────────────────

class WithinDistanceUnitTests(SimpleTestCase):

    def _invoke(self, args):
        from agents_gis.tools_within_distance import SpatialWithinDistanceTool
        tool = SpatialWithinDistanceTool()
        src = _make_layer("farolas", fields=["estado"], filter_fields=["estado"])
        ref = _make_layer("incidencias", fields=["tipo"], filter_fields=["tipo"])

        def layer_cfg(name):
            return src if name == "farolas" else ref if name == "incidencias" else None

        call_count = [0]
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.description = [("fid",), ("centroid_lon",), ("centroid_lat",), ("estado",)]

        def fetchall_side():
            return [(1, -6.055, 37.321, "encendida")]

        def fetchone_side():
            return [3]

        mock_cur.fetchall = MagicMock(side_effect=fetchall_side)
        mock_cur.fetchone = MagicMock(side_effect=fetchone_side)
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("agents_gis.tools_within_distance._get_layer_cfg", side_effect=layer_cfg), \
             patch("agents_gis.tools_within_distance.get_gis_connection", return_value=mock_conn):
            return tool.invoke(args=args)

    def test_basic_ok(self):
        result = self._invoke({
            "source_layer": "farolas", "reference_layer": "incidencias", "distance_m": 100,
        })
        self.assertTrue(result.ok, result.error)
        self.assertIn("features", result.data)
        self.assertIn("total_within_distance", result.data)

    def test_zero_distance_fails(self):
        result = self._invoke({
            "source_layer": "farolas", "reference_layer": "incidencias", "distance_m": 0,
        })
        self.assertFalse(result.ok)
        self.assertIn("distance_m", result.error)

    def test_unknown_source_fails(self):
        from agents_gis.tools_within_distance import SpatialWithinDistanceTool
        tool = SpatialWithinDistanceTool()
        with patch("agents_gis.tools_within_distance._get_layer_cfg", return_value=None):
            result = tool.invoke(args={
                "source_layer": "ghost", "reference_layer": "incidencias", "distance_m": 100,
            })
        self.assertFalse(result.ok)

    def test_invalid_source_filter_fails(self):
        result = self._invoke({
            "source_layer": "farolas", "reference_layer": "incidencias",
            "distance_m": 100, "source_filters": {"campo_raro": "x"},
        })
        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error)

    def test_result_keys(self):
        result = self._invoke({
            "source_layer": "farolas", "reference_layer": "incidencias", "distance_m": 50,
        })
        for k in ("source_layer", "reference_layer", "distance_m", "total_within_distance", "features"):
            self.assertIn(k, result.data)


# ── spatial.topology_check ────────────────────────────────────────────────────

class TopologyCheckUnitTests(SimpleTestCase):

    def _invoke(self, args, invalid_rows=None, total_invalid=0, total_features=10):
        from agents_gis.tools_topology_check import SpatialTopologyCheckTool
        tool = SpatialTopologyCheckTool()
        layer = _make_layer("parcelas", fields=["ref"], filter_fields=["ref"])

        call_count = [0]
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)

        def fetchone_side():
            call_count[0] += 1
            if call_count[0] == 1:
                return [total_features]
            return [total_invalid]

        mock_cur.fetchone = MagicMock(side_effect=fetchone_side)
        mock_cur.fetchall = MagicMock(return_value=invalid_rows or [])
        mock_cur.description = [("fid",), ("centroid_lon",), ("centroid_lat",), ("issue",)]
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("agents_gis.tools_topology_check._get_layer_cfg", return_value=layer), \
             patch("agents_gis.tools_topology_check.get_gis_connection", return_value=mock_conn):
            return tool.invoke(args=args)

    def test_clean_layer(self):
        result = self._invoke({"layer": "parcelas"})
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.data["is_topologically_clean"])
        self.assertEqual(result.data["invalid_geometry_count"], 0)

    def test_with_invalid_geometries(self):
        bad_rows = [(42, -6.055, 37.32, "invalid: Self-intersection")]
        result = self._invoke({"layer": "parcelas"}, invalid_rows=bad_rows, total_invalid=1)
        self.assertTrue(result.ok)
        self.assertFalse(result.data["is_topologically_clean"])
        self.assertEqual(result.data["invalid_geometry_count"], 1)
        self.assertEqual(len(result.data["invalid_features"]), 1)

    def test_unknown_layer_fails(self):
        from agents_gis.tools_topology_check import SpatialTopologyCheckTool
        tool = SpatialTopologyCheckTool()
        with patch("agents_gis.tools_topology_check._get_layer_cfg", return_value=None):
            result = tool.invoke(args={"layer": "ghost"})
        self.assertFalse(result.ok)
        self.assertIn("Unknown", result.error)

    def test_result_keys(self):
        result = self._invoke({"layer": "parcelas"})
        for k in ("layer", "total_features_checked", "is_topologically_clean", "invalid_geometry_count"):
            self.assertIn(k, result.data)

    def test_check_overlaps_key_present(self):
        result = self._invoke({"layer": "parcelas", "check_overlaps": False})
        self.assertTrue(result.ok)
        self.assertNotIn("overlapping_pairs_count", result.data)

    def test_limit_clamped(self):
        result = self._invoke({"layer": "parcelas", "limit": 9999})
        self.assertTrue(result.ok)
