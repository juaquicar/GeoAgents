from django.test import SimpleTestCase

from agents_gis.inference import (
    classify_layer_kind,
    find_best_line_layer,
    find_best_point_layer,
    find_best_polygon_layer,
    infer_intersection_layers,
    infer_network_layer,
)


CATALOG = [
    {"name": "demo_points", "table": "demo_points", "geometry_kind": "point"},
    {"name": "demo_lines", "table": "demo_lines", "geometry_kind": "line"},
    {"name": "demo_polygons", "table": "demo_polygons", "geometry_kind": "polygon"},
]


class GISInferenceTests(SimpleTestCase):
    def test_classify_layer_kind_explicit(self):
        self.assertEqual(classify_layer_kind(CATALOG[0]), "point")
        self.assertEqual(classify_layer_kind(CATALOG[1]), "line")
        self.assertEqual(classify_layer_kind(CATALOG[2]), "polygon")

    def test_find_best_layers(self):
        self.assertEqual(find_best_point_layer(CATALOG), "demo_points")
        self.assertEqual(find_best_line_layer(CATALOG), "demo_lines")
        self.assertEqual(find_best_polygon_layer(CATALOG), "demo_polygons")

    def test_infer_network_layer(self):
        self.assertEqual(infer_network_layer("Traza una ruta de red", CATALOG), "demo_lines")

    def test_infer_intersection_layers(self):
        result = infer_intersection_layers("Cruza puntos con polígonos", CATALOG)
        self.assertEqual(result["source_layer"], "demo_points")
        self.assertEqual(result["target_layer"], "demo_polygons")