import math
from typing import Dict, List, Tuple

import networkx as nx
from django.db import connection

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import _fetchall_dict, _get_layer_cfg


def _haversine_m(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _node_key(lon: float, lat: float, precision: int = 7) -> Tuple[float, float]:
    return (round(float(lon), precision), round(float(lat), precision))


@register_tool
class SpatialNetworkTraceTool(BaseTool):
    name = "spatial.network_trace"
    description = "Traza un camino por una red lineal entre dos puntos sobre una capa de líneas."
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "start_point": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                },
                "required": ["lon", "lat"],
            },
            "end_point": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number"},
                    "lat": {"type": "number"},
                },
                "required": ["lon", "lat"],
            },
            "bbox": {
                "type": "object",
                "properties": {
                    "west": {"type": "number"},
                    "south": {"type": "number"},
                    "east": {"type": "number"},
                    "north": {"type": "number"},
                },
                "required": ["west", "south", "east", "north"],
            },
            "include_geom": {"type": "boolean"},
            "max_snap_distance_m": {"type": "number"},
        },
        "required": ["layer", "start_point", "end_point"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        start_point = args.get("start_point") or {}
        end_point = args.get("end_point") or {}

        if start_point.get("lon") is None or start_point.get("lat") is None:
            return ToolResult(ok=False, error="start_point.lon and start_point.lat are required")

        if end_point.get("lon") is None or end_point.get("lat") is None:
            return ToolResult(ok=False, error="end_point.lon and end_point.lat are required")

        try:
            start_lon = float(start_point["lon"])
            start_lat = float(start_point["lat"])
            end_lon = float(end_point["lon"])
            end_lat = float(end_point["lat"])
        except Exception:
            return ToolResult(ok=False, error="start_point/end_point must contain numeric lon/lat")

        include_geom = bool(args.get("include_geom") or False)

        max_snap_distance_m = float(args.get("max_snap_distance_m") or 250.0)
        max_snap_distance_m = max(1.0, min(max_snap_distance_m, 5000.0))

        bbox = args.get("bbox") or {}

        table = layer["table"]
        geom_col = layer.get("geom_col", "the_geom")
        id_col = layer.get("id_col", "id")

        where_clauses = [f"{geom_col} IS NOT NULL"]
        where_params: List[float] = []

        if bbox:
            required_bbox_keys = {"west", "south", "east", "north"}
            if not required_bbox_keys.issubset(bbox.keys()):
                return ToolResult(ok=False, error="bbox must contain west/south/east/north")

            try:
                west = float(bbox["west"])
                south = float(bbox["south"])
                east = float(bbox["east"])
                north = float(bbox["north"])
            except Exception:
                return ToolResult(ok=False, error="bbox values must be numeric")

            where_clauses.append(
                f"ST_Intersects({geom_col}, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            where_params.extend([west, south, east, north])

        where_sql = " AND ".join(where_clauses)

        geom_geojson_sql = ""
        if include_geom:
            geom_geojson_sql = f", ST_AsGeoJSON({geom_col}) AS geom_geojson"

        sql = f"""
            SELECT
                {id_col} AS id,
                name,
                ST_X(ST_StartPoint({geom_col}))::float AS start_lon,
                ST_Y(ST_StartPoint({geom_col}))::float AS start_lat,
                ST_X(ST_EndPoint({geom_col}))::float AS end_lon,
                ST_Y(ST_EndPoint({geom_col}))::float AS end_lat,
                ST_Length({geom_col}::geography)::float AS length_m
                {geom_geojson_sql}
            FROM {table}
            WHERE {where_sql}
        """

        with connection.cursor() as cur:
            cur.execute(sql, where_params)
            rows = _fetchall_dict(cur)

        if not rows:
            return ToolResult(
                ok=True,
                data={
                    "layer": layer_name,
                    "path_found": False,
                    "reason": "no_segments_in_scope",
                    "start_point": {"lon": start_lon, "lat": start_lat},
                    "end_point": {"lon": end_lon, "lat": end_lat},
                    "segment_ids": [],
                    "segment_names": [],
                    "total_length_m": 0.0,
                    "node_count": 0,
                    "include_geom": include_geom,
                },
            )

        graph = nx.Graph()

        for row in rows:
            if (
                row.get("start_lon") is None
                or row.get("start_lat") is None
                or row.get("end_lon") is None
                or row.get("end_lat") is None
            ):
                continue

            a = _node_key(row["start_lon"], row["start_lat"])
            b = _node_key(row["end_lon"], row["end_lat"])
            length_m = float(row["length_m"] or 0.0)

            graph.add_node(a, lon=a[0], lat=a[1])
            graph.add_node(b, lon=b[0], lat=b[1])

            graph.add_edge(
                a,
                b,
                weight=length_m,
                segment_id=row["id"],
                segment_name=row.get("name"),
                length_m=length_m,
                geom_geojson=row.get("geom_geojson"),
            )

        if graph.number_of_nodes() == 0:
            return ToolResult(
                ok=True,
                data={
                    "layer": layer_name,
                    "path_found": False,
                    "reason": "no_valid_network_nodes",
                    "start_point": {"lon": start_lon, "lat": start_lat},
                    "end_point": {"lon": end_lon, "lat": end_lat},
                    "segment_ids": [],
                    "segment_names": [],
                    "total_length_m": 0.0,
                    "node_count": 0,
                    "include_geom": include_geom,
                },
            )

        def nearest_graph_node(lon: float, lat: float):
            best_node = None
            best_dist = None

            for node in graph.nodes:
                d = _haversine_m(lon, lat, node[0], node[1])
                if best_dist is None or d < best_dist:
                    best_dist = d
                    best_node = node

            return best_node, best_dist

        start_node, start_snap_m = nearest_graph_node(start_lon, start_lat)
        end_node, end_snap_m = nearest_graph_node(end_lon, end_lat)

        if start_node is None or end_node is None:
            return ToolResult(
                ok=True,
                data={
                    "layer": layer_name,
                    "path_found": False,
                    "reason": "unable_to_snap_nodes",
                    "start_point": {"lon": start_lon, "lat": start_lat},
                    "end_point": {"lon": end_lon, "lat": end_lat},
                    "segment_ids": [],
                    "segment_names": [],
                    "total_length_m": 0.0,
                    "node_count": 0,
                    "include_geom": include_geom,
                },
            )

        if start_snap_m > max_snap_distance_m or end_snap_m > max_snap_distance_m:
            return ToolResult(
                ok=True,
                data={
                    "layer": layer_name,
                    "path_found": False,
                    "reason": "snap_distance_exceeded",
                    "start_point": {"lon": start_lon, "lat": start_lat},
                    "end_point": {"lon": end_lon, "lat": end_lat},
                    "start_snap_m": start_snap_m,
                    "end_snap_m": end_snap_m,
                    "segment_ids": [],
                    "segment_names": [],
                    "total_length_m": 0.0,
                    "node_count": 0,
                    "include_geom": include_geom,
                },
            )

        try:
            path_nodes = nx.shortest_path(
                graph,
                source=start_node,
                target=end_node,
                weight="weight",
            )
        except nx.NetworkXNoPath:
            return ToolResult(
                ok=True,
                data={
                    "layer": layer_name,
                    "path_found": False,
                    "reason": "no_path",
                    "start_point": {"lon": start_lon, "lat": start_lat},
                    "end_point": {"lon": end_lon, "lat": end_lat},
                    "start_snap_m": start_snap_m,
                    "end_snap_m": end_snap_m,
                    "segment_ids": [],
                    "segment_names": [],
                    "total_length_m": 0.0,
                    "node_count": 0,
                    "include_geom": include_geom,
                },
            )

        segment_ids = []
        segment_names = []
        total_length_m = 0.0
        path_items = []

        for i in range(len(path_nodes) - 1):
            a = path_nodes[i]
            b = path_nodes[i + 1]
            edge = graph[a][b]

            segment_ids.append(edge["segment_id"])
            segment_names.append(edge.get("segment_name"))
            total_length_m += float(edge.get("length_m") or 0.0)

            item = {
                "segment_id": edge["segment_id"],
                "segment_name": edge.get("segment_name"),
                "length_m": float(edge.get("length_m") or 0.0),
            }

            if include_geom and edge.get("geom_geojson"):
                geom = edge["geom_geojson"]
                if isinstance(geom, str) and len(geom) > 20_000:
                    geom = geom[:20_000] + "...(truncated)"
                item["geom_geojson"] = geom

            path_items.append(item)

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "path_found": True,
                "start_point": {"lon": start_lon, "lat": start_lat},
                "end_point": {"lon": end_lon, "lat": end_lat},
                "start_snap_node": {"lon": start_node[0], "lat": start_node[1]},
                "end_snap_node": {"lon": end_node[0], "lat": end_node[1]},
                "start_snap_m": start_snap_m,
                "end_snap_m": end_snap_m,
                "segment_ids": segment_ids,
                "segment_names": segment_names,
                "total_length_m": total_length_m,
                "node_count": len(path_nodes),
                "path_items": path_items,
                "include_geom": include_geom,
                "max_snap_distance_m": max_snap_distance_m,
            },
        )
