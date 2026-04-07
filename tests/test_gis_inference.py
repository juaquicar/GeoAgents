"""
Tests de inferencia GIS: clasificación de geometría, selección de capas por goal,
e inferencia de intersecciones. Funciona con el catálogo de un agente (no settings global).

Ejecutar:
    python manage.py test tests.test_gis_inference
"""
from django.test import SimpleTestCase

from agents_gis.inference import (
    classify_layer_kind,
    find_best_line_layer,
    find_best_point_layer,
    find_best_polygon_layer,
    infer_intersection_layers,
    infer_nearby_layer,
    infer_network_layer,
    infer_query_layer,
)


# Catálogo de ejemplo — simula agent.gis_layers_catalog
CATALOG_SIMPLE = [
    {"name": "demo_points",   "table": "demo_points",   "geometry_kind": "point"},
    {"name": "demo_lines",    "table": "demo_lines",    "geometry_kind": "line"},
    {"name": "demo_polygons", "table": "demo_polygons", "geometry_kind": "polygon"},
]

# Catálogo con metadatos de geometry_kind en formato uppercase (como devuelve PostGIS)
CATALOG_UPPERCASE = [
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


class GISInferenceTests(SimpleTestCase):
    """Clasificación con geometry_kind explícito en minúsculas."""

    def test_classify_layer_kind_explicit(self):
        self.assertEqual(classify_layer_kind(CATALOG_SIMPLE[0]), "point")
        self.assertEqual(classify_layer_kind(CATALOG_SIMPLE[1]), "line")
        self.assertEqual(classify_layer_kind(CATALOG_SIMPLE[2]), "polygon")

    def test_find_best_layers(self):
        self.assertEqual(find_best_point_layer(CATALOG_SIMPLE), "demo_points")
        self.assertEqual(find_best_line_layer(CATALOG_SIMPLE), "demo_lines")
        self.assertEqual(find_best_polygon_layer(CATALOG_SIMPLE), "demo_polygons")

    def test_infer_network_layer(self):
        self.assertEqual(infer_network_layer("Traza una ruta de red", CATALOG_SIMPLE), "demo_lines")

    def test_infer_intersection_layers(self):
        result = infer_intersection_layers("Cruza puntos con polígonos", CATALOG_SIMPLE)
        self.assertEqual(result["source_layer"], "demo_points")
        self.assertEqual(result["target_layer"], "demo_polygons")


class GISInferenceUppercaseTests(SimpleTestCase):
    """Clasificación cuando geometry_kind viene en uppercase desde PostGIS."""

    def test_classify_layer_kind_prioritizes_explicit_geometry_metadata(self):
        self.assertEqual(classify_layer_kind(CATALOG_UPPERCASE[0]), "point")
        self.assertEqual(classify_layer_kind(CATALOG_UPPERCASE[1]), "line")
        self.assertEqual(classify_layer_kind(CATALOG_UPPERCASE[2]), "polygon")

    def test_infer_query_layer_returns_line_layer_for_lines_goal(self):
        inferred = infer_query_layer("Explora la capa de lineas en esta zona", CATALOG_UPPERCASE)
        self.assertEqual(inferred, "demo_lines")

    def test_infer_nearby_layer_returns_polygon_layer_for_zones_goal(self):
        inferred = infer_nearby_layer("¿Qué zonas hay cerca del centro del mapa?", CATALOG_UPPERCASE)
        self.assertEqual(inferred, "demo_polygons")

    def test_infers_line_polygon_when_goal_mentions_lines_and_zones(self):
        inferred = infer_intersection_layers("Comprobar intersección de líneas con zonas", CATALOG_UPPERCASE)
        self.assertEqual(inferred["source_layer"], "demo_lines")
        self.assertEqual(inferred["target_layer"], "demo_polygons")

    def test_infers_point_line_when_goal_mentions_points_and_lines(self):
        inferred = infer_intersection_layers("Ver si puntos intersectan líneas", CATALOG_UPPERCASE)
        self.assertEqual(inferred["source_layer"], "demo_points")
        self.assertEqual(inferred["target_layer"], "demo_lines")

    def test_infers_default_point_polygon_pair_when_goal_is_generic(self):
        inferred = infer_intersection_layers("Comprueba la relación espacial entre capas", CATALOG_UPPERCASE)
        self.assertEqual(inferred["source_layer"], "demo_points")
        self.assertEqual(inferred["target_layer"], "demo_polygons")


class GISInferenceFallbackTests(SimpleTestCase):
    """Fallback a hints textuales cuando no hay geometry_kind explícito."""

    def test_infer_query_layer_uses_textual_hints_when_geometry_metadata_is_missing(self):
        catalog = [
            {"name": "customer_nodes",  "table": "customer_nodes",  "fields": ["node_id"]},
            {"name": "fiber_segments",  "table": "network_segments", "fields": ["segment_id", "cable"]},
            {"name": "service_zones",   "table": "service_areas",    "fields": ["zone_name"]},
        ]
        inferred = infer_query_layer("Consulta las lineas en esta zona", catalog)
        self.assertEqual(inferred, "fiber_segments")
