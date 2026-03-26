from django.test import SimpleTestCase

from agents_gis.tools_network_trace import (
    _build_network_graph,
    _compute_service_area_from_graph,
    _parse_route_cost_options,
)


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

    def test_service_area_respects_cost_and_distance_limits(self):
        rows = [
            {
                "id": 1,
                "name": "A-B",
                "segment_type": "fiber",
                "start_lon": -6.0,
                "start_lat": 37.0,
                "end_lon": -6.001,
                "end_lat": 37.0,
                "length_m": 120,
            },
            {
                "id": 2,
                "name": "B-C",
                "segment_type": "fiber",
                "start_lon": -6.001,
                "start_lat": 37.0,
                "end_lon": -6.002,
                "end_lat": 37.0,
                "length_m": 120,
            },
            {
                "id": 3,
                "name": "C-D",
                "segment_type": "fiber",
                "start_lon": -6.002,
                "start_lat": 37.0,
                "end_lon": -6.003,
                "end_lat": 37.0,
                "length_m": 120,
            },
        ]

        graph = _build_network_graph(rows, options=_parse_route_cost_options({"metric": "length"}))

        reachable_nodes, _, _ = _compute_service_area_from_graph(
            graph,
            origin_node=(-6.0, 37.0),
            max_cost=9999.0,
            max_distance_m=240.0,
        )
        self.assertEqual(len(reachable_nodes), 3)
        self.assertIn((-6.002, 37.0), reachable_nodes)
        self.assertNotIn((-6.003, 37.0), reachable_nodes)

        reachable_nodes_cost, _, _ = _compute_service_area_from_graph(
            graph,
            origin_node=(-6.0, 37.0),
            max_cost=100.0,
            max_distance_m=None,
        )
        self.assertEqual(len(reachable_nodes_cost), 1)
        self.assertIn((-6.0, 37.0), reachable_nodes_cost)
