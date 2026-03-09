from django.test import SimpleTestCase

from agents_gis.inference import infer_intersection_layers


class InferIntersectionLayersTests(SimpleTestCase):
    def setUp(self):
        self.catalog = [
            {"name": "demo_points", "table": "demo_points", "fields": ["point_id"]},
            {"name": "demo_lines", "table": "network_lines", "fields": ["line_id", "cable"]},
            {"name": "demo_polygons", "table": "demo_polygons", "fields": ["zona"]},
        ]

    def test_infers_line_polygon_when_goal_mentions_lines(self):
        inferred = infer_intersection_layers(
            "Comprobar intersección de líneas con zonas",
            self.catalog,
        )

        self.assertEqual(inferred["source_layer"], "demo_lines")
        self.assertEqual(inferred["target_layer"], "demo_polygons")

    def test_infers_point_line_when_goal_mentions_both(self):
        inferred = infer_intersection_layers(
            "Ver si puntos intersectan líneas",
            self.catalog,
        )

        self.assertEqual(inferred["source_layer"], "demo_points")
        self.assertEqual(inferred["target_layer"], "demo_lines")
