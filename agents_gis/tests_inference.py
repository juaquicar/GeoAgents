from unittest import TestCase

from agents_gis.inference import (
    classify_layer_kind,
    infer_intersection_layers,
    infer_nearby_layer,
    infer_query_layer,
)


class InferenceTests(TestCase):
    def setUp(self):
        self.catalog = [
            {
                "name": "demo_points",
                "table": "inventory_assets",
                "fields": ["asset_id"],
                "geometry_kind": "POINT",
            },
            {
                "name": "demo_lines",
                "table": "tbl_edges",
                "fields": ["edge_id"],
                "geometry_kind": "MULTILINESTRING",
            },
            {
                "name": "demo_polygons",
                "table": "management_areas",
                "fields": ["zone_id"],
                "geometry_kind": "MULTIPOLYGON",
            },
        ]

    def test_classify_layer_kind_prioritizes_explicit_geometry_metadata(self):
        self.assertEqual(classify_layer_kind(self.catalog[0]), "point")
        self.assertEqual(classify_layer_kind(self.catalog[1]), "line")
        self.assertEqual(classify_layer_kind(self.catalog[2]), "polygon")

    def test_infer_query_layer_returns_line_layer_for_lines_goal(self):
        inferred = infer_query_layer(
            "Explora la capa de lineas en esta zona",
            self.catalog,
        )
        self.assertEqual(inferred, "demo_lines")

    def test_infer_nearby_layer_returns_polygon_layer_for_zones_goal(self):
        inferred = infer_nearby_layer(
            "¿Qué zonas hay cerca del centro del mapa?",
            self.catalog,
        )
        self.assertEqual(inferred, "demo_polygons")

    def test_infers_line_polygon_when_goal_mentions_lines_and_zones(self):
        inferred = infer_intersection_layers(
            "Comprobar intersección de líneas con zonas",
            self.catalog,
        )
        self.assertEqual(inferred["source_layer"], "demo_lines")
        self.assertEqual(inferred["target_layer"], "demo_polygons")

    def test_infers_point_line_when_goal_mentions_points_and_lines(self):
        inferred = infer_intersection_layers(
            "Ver si puntos intersectan líneas",
            self.catalog,
        )
        self.assertEqual(inferred["source_layer"], "demo_points")
        self.assertEqual(inferred["target_layer"], "demo_lines")

    def test_infers_default_point_polygon_pair_when_goal_is_generic(self):
        inferred = infer_intersection_layers(
            "Comprueba la relación espacial entre capas",
            self.catalog,
        )
        self.assertEqual(inferred["source_layer"], "demo_points")
        self.assertEqual(inferred["target_layer"], "demo_polygons")


class InferenceHeuristicFallbackTests(TestCase):
    def test_infer_query_layer_uses_textual_hints_when_geometry_metadata_is_missing(self):
        catalog = [
            {"name": "customer_nodes", "table": "customer_nodes", "fields": ["node_id"]},
            {"name": "fiber_segments", "table": "network_segments", "fields": ["segment_id", "cable"]},
            {"name": "service_zones", "table": "service_areas", "fields": ["zone_name"]},
        ]

        inferred = infer_query_layer("Consulta las lineas en esta zona", catalog)
        self.assertEqual(inferred, "fiber_segments")