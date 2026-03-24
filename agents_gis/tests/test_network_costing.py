from django.test import SimpleTestCase

from agents_gis.tools_network_trace import _build_network_graph, _parse_route_cost_options


class NetworkCostingTests(SimpleTestCase):
    def test_cost_prefers_type_multiplier(self):
        rows = [
            {
                "id": 1,
                "name": "A-B slow",
                "segment_type": "slow",
                "start_lon": -6.0,
                "start_lat": 37.0,
                "end_lon": -6.0,
                "end_lat": 37.001,
                "length_m": 100,
            },
            {
                "id": 2,
                "name": "B-C slow",
                "segment_type": "slow",
                "start_lon": -6.0,
                "start_lat": 37.001,
                "end_lon": -6.0,
                "end_lat": 37.002,
                "length_m": 100,
            },
            {
                "id": 3,
                "name": "A-C fiber",
                "segment_type": "fiber",
                "start_lon": -6.0,
                "start_lat": 37.0,
                "end_lon": -6.0,
                "end_lat": 37.002,
                "length_m": 220,
            },
        ]

        cost_graph = _build_network_graph(
            rows,
            options=_parse_route_cost_options(
                {
                    "metric": "cost",
                    "segment_type_costs": {"slow": 2.0, "fiber": 0.5},
                }
            ),
        )

        self.assertEqual(cost_graph[(-6.0, 37.0)][(-6.0, 37.002)]["weight"], 110.0)
        self.assertEqual(cost_graph[(-6.0, 37.0)][(-6.0, 37.001)]["weight"], 200.0)

    def test_restrictions_remove_segments(self):
        rows = [
            {
                "id": 10,
                "name": "blocked",
                "segment_type": "duct",
                "start_lon": -6.0,
                "start_lat": 37.0,
                "end_lon": -6.001,
                "end_lat": 37.0,
                "length_m": 120,
            }
        ]

        graph = _build_network_graph(
            rows,
            options=_parse_route_cost_options(
                {
                    "restrictions": {
                        "forbidden_segment_ids": [10],
                    }
                }
            ),
        )

        self.assertEqual(graph.number_of_edges(), 0)
