"""
Tests de selección de herramientas (heurísticas) para las nuevas tools GIS.
Verifica que select_initial_tools devuelve la tool correcta para preguntas
representativas de cada operación.

Ejecutar:
    python manage.py test tests.test_heuristics_new_tools
"""
from django.test import SimpleTestCase

from agents_core.heuristics import select_initial_tools


def _contains(goal: str, tool: str) -> bool:
    return tool in select_initial_tools(goal)


class ConvexHullHeuristicsTests(SimpleTestCase):

    def test_extension_keywords(self):
        self.assertTrue(_contains("¿Cuál es el área que ocupan todos los incidentes?", "spatial.convex_hull"))

    def test_contorno_envuelve(self):
        self.assertTrue(_contains("Dame el contorno que envuelve todos los activos de la zona", "spatial.convex_hull"))

    def test_envolvente(self):
        self.assertTrue(_contains("Calcula la envolvente exterior de los puntos de inspección", "spatial.convex_hull"))

    def test_hull_en(self):
        self.assertTrue(_contains("Compute convex hull of the layer", "spatial.convex_hull"))

    def test_extension_de(self):
        self.assertTrue(_contains("¿Cuál es la extensión de las farolas del barrio?", "spatial.convex_hull"))


class VoronoiHeuristicsTests(SimpleTestCase):

    def test_voronoi_keyword(self):
        self.assertTrue(_contains("Genera polígonos de Voronoi para los sensores", "spatial.voronoi"))

    def test_zona_de_influencia(self):
        self.assertTrue(_contains("¿Cuál es la zona de influencia de cada farola?", "spatial.voronoi"))

    def test_area_de_influencia(self):
        self.assertTrue(_contains("Calcula el área de influencia de cada punto de servicio", "spatial.voronoi"))

    def test_zona_cobertura(self):
        self.assertTrue(_contains("Dibuja las zonas de cobertura de los sensores", "spatial.voronoi"))

    def test_tesela(self):
        self.assertTrue(_contains("Crea una teselación a partir de los puntos de control", "spatial.voronoi"))


class MeasureHeuristicsTests(SimpleTestCase):

    def test_metros_de_red(self):
        self.assertTrue(_contains("¿Cuántos metros de red hay en esta zona?", "spatial.measure"))

    def test_longitud_total(self):
        self.assertTrue(_contains("Dame la longitud total de los tramos", "spatial.measure"))

    def test_area_total(self):
        self.assertTrue(_contains("¿Cuál es el área total de las parcelas?", "spatial.measure"))

    def test_superficie_total(self):
        self.assertTrue(_contains("Calcula la superficie total de las zonas verdes", "spatial.measure"))

    def test_longitud_media(self):
        self.assertTrue(_contains("Dame la longitud media de los tramos por categoría", "spatial.measure"))

    def test_perimetro(self):
        self.assertTrue(_contains("¿Cuál es el perímetro de los rodales forestales?", "spatial.measure"))

    def test_cuantos_metros(self):
        self.assertTrue(_contains("¿Cuántos metros de fibra hay instalados?", "spatial.measure"))


class OverlayHeuristicsTests(SimpleTestCase):

    def test_superposicion(self):
        self.assertTrue(_contains("Calcula la superposición entre parcelas y zona de protección", "spatial.overlay"))

    def test_superpone(self):
        self.assertTrue(_contains("¿Qué área se superpone entre los dos polígonos?", "spatial.overlay"))

    def test_overlay_en(self):
        self.assertTrue(_contains("Perform overlay analysis between both layers", "spatial.overlay"))

    def test_zona_comun(self):
        self.assertTrue(_contains("Dame la zona común entre las parcelas y el parque", "spatial.overlay"))

    def test_interseccion_de_capas(self):
        self.assertTrue(_contains("Obtén la intersección de capas entre edificios y zonificación", "spatial.overlay"))

    def test_diferencia_de_capas(self):
        self.assertTrue(_contains("Calcula la diferencia de capas entre parcelas y zona inundable", "spatial.overlay"))


class NearestNeighborHeuristicsTests(SimpleTestCase):

    def test_mas_cercano(self):
        self.assertTrue(_contains("Para cada incidencia, ¿cuál es la farola más cercana?", "spatial.nearest_neighbor"))

    def test_vecino_mas(self):
        self.assertTrue(_contains("Busca el vecino más próximo de cada sensor", "spatial.nearest_neighbor"))

    def test_nearest_neighbor_en(self):
        self.assertTrue(_contains("Find the nearest neighbor for each feature", "spatial.nearest_neighbor"))

    def test_punto_mas_proximo(self):
        self.assertTrue(_contains("¿Cuál es el punto más próximo a cada edificio?", "spatial.nearest_neighbor"))

    def test_feature_mas_cercano(self):
        self.assertTrue(_contains("Asigna a cada árbol el feature más cercano de la capa riegos", "spatial.nearest_neighbor"))


class WithinDistanceHeuristicsTests(SimpleTestCase):

    def test_a_menos_de(self):
        self.assertTrue(_contains("¿Qué farolas están a menos de 50 metros de una incidencia?", "spatial.within_distance"))

    def test_dentro_de_un_radio(self):
        self.assertTrue(_contains("Muestra los activos dentro de un radio de 100m de la zona de obras", "spatial.within_distance"))

    def test_en_un_radio(self):
        self.assertTrue(_contains("Features en un radio de 200 metros del punto contaminante", "spatial.within_distance"))

    def test_a_distancia_de(self):
        self.assertTrue(_contains("Tramos a distancia de 30m de edificios catalogados", "spatial.within_distance"))

    def test_within_distance_en(self):
        self.assertTrue(_contains("Get all assets within distance of the reference layer", "spatial.within_distance"))


class TopologyCheckHeuristicsTests(SimpleTestCase):

    def test_geometria_invalida(self):
        self.assertTrue(_contains("¿Hay geometrías inválidas en la capa de parcelas?", "spatial.topology_check"))

    def test_integridad(self):
        self.assertTrue(_contains("Comprueba la integridad de la capa de rodales", "spatial.topology_check"))

    def test_solapamiento(self):
        self.assertTrue(_contains("¿Existen solapamientos entre los polígonos de zonificación?", "spatial.topology_check"))

    def test_validez(self):
        self.assertTrue(_contains("Verifica la validez de las geometrías de la red", "spatial.topology_check"))

    def test_topolog(self):
        self.assertTrue(_contains("Analiza la calidad topológica de la capa de tramos", "spatial.topology_check"))

    def test_errores_geomet(self):
        self.assertTrue(_contains("Detecta errores geométricos en la capa de edificios", "spatial.topology_check"))

    def test_invalida_shortform(self):
        self.assertTrue(_contains("La capa tiene features inválidas, compruébalo", "spatial.topology_check"))


# ── Regresión: las tools anteriores siguen funcionando ───────────────────────

class ExistingToolsRegressionTests(SimpleTestCase):
    """Verifica que las nuevas heurísticas no rompen la selección de tools ya existentes."""

    def test_cluster_dbscan(self):
        self.assertTrue(_contains("¿Dónde se concentran los incidentes?", "spatial.cluster_dbscan"))

    def test_count_within(self):
        self.assertTrue(_contains("¿Cuántos hay por zona?", "spatial.count_within"))

    def test_spatial_join(self):
        self.assertTrue(_contains("¿A qué barrio pertenece cada farola?", "spatial.spatial_join"))

    def test_difference(self):
        self.assertTrue(_contains("¿Cuál es el área libre de la parcela?", "spatial.difference"))

    def test_grid_stats(self):
        self.assertTrue(_contains("Dame un mapa de calor de la distribución espacial", "spatial.grid_stats"))

    def test_dissolve(self):
        self.assertTrue(_contains("Fusiona las parcelas del mismo propietario", "spatial.dissolve"))

    def test_centroid(self):
        self.assertTrue(_contains("Dame el centroide de cada zona", "spatial.centroid"))

    def test_buffer(self):
        self.assertTrue(_contains("Busca elementos en un radio de 100 metros", "spatial.buffer"))

    def test_nearby(self):
        self.assertTrue(_contains("Busca puntos cercanos al origen", "spatial.nearby"))

    def test_aggregate(self):
        self.assertTrue(_contains("¿Cuántos hay por tipo en la zona?", "spatial.aggregate"))

    def test_network_trace(self):
        self.assertTrue(_contains("Traza la ruta de red", "spatial.network_trace"))
