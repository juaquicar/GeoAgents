from django.test import SimpleTestCase

from agents_core.heuristics import select_initial_tools, select_fallback_tools


class HeuristicsSelectionTests(SimpleTestCase):
    def test_select_initial_tools_network(self):
        tools = select_initial_tools("Traza una ruta de red")
        self.assertEqual(tools[0], "spatial.network_trace")

    def test_select_initial_tools_nearby(self):
        tools = select_initial_tools("Busca puntos cercanos")
        self.assertIn("spatial.nearby", tools)

    def test_select_initial_tools_respects_allowlist(self):
        tools = select_initial_tools(
            "Traza una ruta de red",
            allowlist=["spatial.query_layer"],
        )
        self.assertEqual(tools, ["spatial.query_layer"])

    def test_select_fallback_tools_for_network_trace(self):
        tools = select_fallback_tools(
            "Traza una ruta de red",
            failed_tool="spatial.network_trace",
        )
        self.assertIn("spatial.query_layer", tools)

    def test_select_initial_tools_route_cost(self):
        tools = select_initial_tools("Optimiza la ruta con coste y penalizaciones")
        self.assertIn("spatial.route_cost", tools)

    def test_select_initial_tools_service_area(self):
        tools = select_initial_tools("Calcula la cobertura de servicio alcanzable en red")
        self.assertIn("spatial.network_service_area", tools)
