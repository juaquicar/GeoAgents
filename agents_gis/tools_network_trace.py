import math
from typing import Any, Dict, List, Set, Tuple

import networkx as nx

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from agents_gis.service import (
    _fetchall_dict, _get_layer_cfg, get_gis_connection, qualified_table, quote_col,
    get_layer_srid, geom_to_4326, bbox_in_layer_srid,
)


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


def _parse_id_set(values: Any) -> Set[str]:
    if not values:
        return set()
    return {str(v).strip() for v in values if str(v).strip()}


def _parse_float_mapping(raw: Any) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = str(k).strip()
        if not key:
            continue
        try:
            out[key] = float(v)
        except Exception:
            continue
    return out


def _parse_route_cost_options(args: Dict[str, Any]) -> Dict[str, Any]:
    metric = str(args.get("metric") or "cost").strip().lower()
    if metric not in {"length", "cost"}:
        metric = "cost"

    length_weight = float(args.get("length_weight") or 1.0)
    length_weight = max(0.0001, min(length_weight, 1000.0))

    segment_type_costs = _parse_float_mapping(args.get("segment_type_costs"))
    segment_penalties = _parse_float_mapping(args.get("segment_penalties"))
    segment_type_penalties = _parse_float_mapping(args.get("segment_type_penalties"))

    restrictions = args.get("restrictions") or {}
    forbidden_segment_ids = _parse_id_set(restrictions.get("forbidden_segment_ids"))
    forbidden_segment_types = _parse_id_set(restrictions.get("forbidden_segment_types"))

    max_segment_length_m = restrictions.get("max_segment_length_m")
    if max_segment_length_m is not None:
        max_segment_length_m = max(0.0, float(max_segment_length_m))

    return {
        "metric": metric,
        "length_weight": length_weight,
        "segment_type_costs": segment_type_costs,
        "segment_penalties": segment_penalties,
        "segment_type_penalties": segment_type_penalties,
        "forbidden_segment_ids": forbidden_segment_ids,
        "forbidden_segment_types": forbidden_segment_types,
        "max_segment_length_m": max_segment_length_m,
    }


def _compute_edge_cost(length_m: float, segment_id: Any, segment_type: Any, options: Dict[str, Any]) -> float:
    segment_id_key = str(segment_id)
    segment_type_key = "" if segment_type is None else str(segment_type)

    base_cost = float(length_m or 0.0)
    if options["metric"] == "cost":
        base_cost *= options["length_weight"]
        if segment_type_key:
            base_cost *= options["segment_type_costs"].get(segment_type_key, 1.0)

        base_cost += options["segment_penalties"].get(segment_id_key, 0.0)
        if segment_type_key:
            base_cost += options["segment_type_penalties"].get(segment_type_key, 0.0)

    return max(0.0, base_cost)


def _build_network_graph(
    rows: List[Dict[str, Any]],
    *,
    options: Dict[str, Any] | None = None,
) -> nx.Graph:
    options = options or _parse_route_cost_options({})
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
        length_m = float(row.get("length_m") or 0.0)
        segment_id = row.get("id")
        segment_type = row.get("segment_type")

        if str(segment_id) in options["forbidden_segment_ids"]:
            continue
        if segment_type is not None and str(segment_type) in options["forbidden_segment_types"]:
            continue
        if options["max_segment_length_m"] is not None and length_m > options["max_segment_length_m"]:
            continue

        graph.add_node(a, lon=a[0], lat=a[1])
        graph.add_node(b, lon=b[0], lat=b[1])

        graph.add_edge(
            a,
            b,
            weight=_compute_edge_cost(length_m, segment_id, segment_type, options),
            segment_id=segment_id,
            segment_name=row.get("name"),
            segment_type=segment_type,
            length_m=length_m,
            geom_geojson=row.get("geom_geojson"),
        )

    return graph


def _nearest_graph_node(graph: nx.Graph, lon: float, lat: float):
    best_node = None
    best_dist = None

    for node in graph.nodes:
        d = _haversine_m(lon, lat, node[0], node[1])
        if best_dist is None or d < best_dist:
            best_dist = d
            best_node = node

    return best_node, best_dist


def _compute_service_area_from_graph(
    graph: nx.Graph,
    *,
    origin_node: Tuple[float, float],
    max_cost: float | None,
    max_distance_m: float | None,
):
    cost_distances = nx.single_source_dijkstra_path_length(graph, source=origin_node, weight="weight")
    distance_limits = None
    if max_distance_m is not None:
        distance_limits = nx.single_source_dijkstra_path_length(graph, source=origin_node, weight="length_m")

    def within_limit(node: Tuple[float, float], cost_value: float) -> bool:
        if max_cost is not None and cost_value > max_cost:
            return False
        if max_distance_m is None:
            return True
        distance_value = float((distance_limits or {}).get(node, float("inf")))
        return distance_value <= max_distance_m

    reachable_nodes = [node for node, cost in cost_distances.items() if within_limit(node, cost)]
    reachable_set = set(reachable_nodes)
    return reachable_nodes, reachable_set, cost_distances


def _extract_bbox_clause(args: Dict[str, Any], geom_col: str, srid: int = 4326):
    bbox = args.get("bbox") or {}
    qgeom = quote_col(geom_col)
    where_clauses = [f"{qgeom} IS NOT NULL"]
    where_params: List[float] = []

    if bbox:
        required_bbox_keys = {"west", "south", "east", "north"}
        if not required_bbox_keys.issubset(bbox.keys()):
            raise ValueError("bbox must contain west/south/east/north")

        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])

        envelope_sql = bbox_in_layer_srid(srid)
        where_clauses.append(f"ST_Intersects({qgeom}, {envelope_sql})")
        where_params.extend([west, south, east, north])

    return " AND ".join(where_clauses), where_params


def _fetch_polygon_boundary_edges(
    layer: Dict[str, Any],
    args: Dict[str, Any],
    include_geom: bool,
    max_polygons: int = 300,
) -> List[Dict[str, Any]]:
    """
    Para capas de tipo polygon/multipolygon, extrae las aristas individuales de
    los límites exteriores de cada geometría como tramos de red.

    Cada par de vértices consecutivos en el anillo exterior forma un tramo con
    sus propios start_lon/lat y end_lon/lat en WGS84.
    """
    table = qualified_table(layer)
    geom_col = layer.get("geom_col", "the_geom")
    srid = get_layer_srid(layer)
    id_col = layer.get("id_col", "id")

    qgeom = quote_col(geom_col)
    qid = quote_col(id_col)

    # La geometría se transforma a 4326 para que las coordenadas de salida sean WGS84
    if srid != 4326:
        geom_4326_expr = f"ST_Transform({qgeom}, 4326)"
    else:
        geom_4326_expr = qgeom

    where_sql, where_params = _extract_bbox_clause(args, geom_col, srid)

    geom_geojson_sql = ""
    if include_geom:
        geom_geojson_sql = """
            , ST_AsGeoJSON(
                ST_MakeLine(
                    ST_PointN(rings.ring, gs2.seg_n),
                    ST_PointN(rings.ring, gs2.seg_n + 1)
                )
            ) AS geom_geojson
        """

    sql = f"""
        SELECT
            (rings.src_id::text || '_' || rings.poly_n::text || '_' || gs2.seg_n::text) AS id,
            NULL::text AS name,
            NULL::text AS segment_type,
            ST_X(ST_PointN(rings.ring, gs2.seg_n))::float        AS start_lon,
            ST_Y(ST_PointN(rings.ring, gs2.seg_n))::float        AS start_lat,
            ST_X(ST_PointN(rings.ring, gs2.seg_n + 1))::float    AS end_lon,
            ST_Y(ST_PointN(rings.ring, gs2.seg_n + 1))::float    AS end_lat,
            ST_Length(
                ST_MakeLine(
                    ST_PointN(rings.ring, gs2.seg_n),
                    ST_PointN(rings.ring, gs2.seg_n + 1)
                )::geography
            )::float AS length_m
            {geom_geojson_sql}
        FROM (
            SELECT
                {qid} AS src_id,
                gs1.poly_n,
                ST_ExteriorRing(
                    ST_GeometryN({geom_4326_expr}, gs1.poly_n)
                ) AS ring,
                ST_NPoints(
                    ST_ExteriorRing(ST_GeometryN({geom_4326_expr}, gs1.poly_n))
                ) AS n_pts
            FROM {table}
            CROSS JOIN generate_series(1, ST_NumGeometries({qgeom})) AS gs1(poly_n)
            WHERE {where_sql}
            LIMIT %s
        ) AS rings
        CROSS JOIN LATERAL generate_series(1, rings.n_pts - 1) AS gs2(seg_n)
        WHERE rings.n_pts > 1
    """

    params = where_params + [max_polygons]

    with get_gis_connection().cursor() as cur:
        cur.execute(sql, params)
        return _fetchall_dict(cur)


def _fetch_network_rows(layer: Dict[str, Any], args: Dict[str, Any], include_geom: bool):
    # Para capas de polígono, extraer las aristas de los límites como red
    geometry_kind = (layer.get("geometry_kind") or "line").lower()
    if geometry_kind in ("polygon", "multipolygon"):
        return _fetch_polygon_boundary_edges(layer, args, include_geom)

    table = qualified_table(layer)
    geom_col = layer.get("geom_col", "the_geom")
    srid = get_layer_srid(layer)
    id_col = layer.get("id_col", "id")

    segment_type_field = str(args.get("segment_type_field") or "segment_type").strip()
    extra_cols = set(layer.get("fields") or [])
    has_segment_type = segment_type_field in extra_cols

    # Determinar columna de nombre: "name" si existe, si no buscar *_name o usar NULL
    name_col = None
    if "name" in extra_cols:
        name_col = "name"
    else:
        for f in (layer.get("fields") or []):
            if f.endswith("_name") or f.startswith("name_"):
                name_col = f
                break

    qgeom = quote_col(geom_col)
    geom4326 = geom_to_4326(qgeom, srid)
    where_sql, where_params = _extract_bbox_clause(args, geom_col, srid)

    segment_type_sql = "NULL::text AS segment_type"
    if has_segment_type:
        segment_type_sql = f"{quote_col(segment_type_field)}::text AS segment_type"

    name_sql = "NULL::text AS name" if name_col is None else f"{quote_col(name_col)}::text AS name"

    # ST_Dump explota MULTILINESTRING en LINESTRING simples para que ST_StartPoint/ST_EndPoint
    # funcionen correctamente. Para LINESTRING simple devuelve exactamente 1 fila por feature.
    geom_dump_4326 = f"ST_Transform((ST_Dump({qgeom})).geom, 4326)" if srid != 4326 \
        else f"(ST_Dump({qgeom})).geom"

    geom_geojson_sql = ""
    if include_geom:
        geom_geojson_sql = f", ST_AsGeoJSON({geom_dump_4326}) AS geom_geojson"

    sql = f"""
        SELECT
            {quote_col(id_col)} AS id,
            {name_sql},
            {segment_type_sql},
            ST_X(ST_StartPoint({geom_dump_4326}))::float AS start_lon,
            ST_Y(ST_StartPoint({geom_dump_4326}))::float AS start_lat,
            ST_X(ST_EndPoint({geom_dump_4326}))::float AS end_lon,
            ST_Y(ST_EndPoint({geom_dump_4326}))::float AS end_lat,
            ST_Length({geom_dump_4326}::geography)::float AS length_m
            {geom_geojson_sql}
        FROM {table}
        WHERE {where_sql}
    """

    with get_gis_connection().cursor() as cur:
        cur.execute(sql, where_params)
        return _fetchall_dict(cur)


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

        try:
            rows = _fetch_network_rows(layer, args, include_geom)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))

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

        graph = _build_network_graph(rows)

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

        start_node, start_snap_m = _nearest_graph_node(graph, start_lon, start_lat)
        end_node, end_snap_m = _nearest_graph_node(graph, end_lon, end_lat)

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


@register_tool
class SpatialRouteCostTool(BaseTool):
    name = "spatial.route_cost"
    description = "Calcula la ruta óptima en red con coste configurable por longitud, tipo, penalizaciones y restricciones."
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "start_point": {
                "type": "object",
                "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
                "required": ["lon", "lat"],
            },
            "end_point": {
                "type": "object",
                "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
                "required": ["lon", "lat"],
            },
            "metric": {"type": "string", "enum": ["length", "cost"]},
            "length_weight": {"type": "number"},
            "segment_type_field": {"type": "string"},
            "segment_type_costs": {"type": "object"},
            "segment_penalties": {"type": "object"},
            "segment_type_penalties": {"type": "object"},
            "restrictions": {
                "type": "object",
                "properties": {
                    "forbidden_segment_ids": {"type": "array"},
                    "forbidden_segment_types": {"type": "array"},
                    "max_segment_length_m": {"type": "number"},
                },
            },
            "bbox": {"type": "object"},
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

        options = _parse_route_cost_options(args)

        try:
            rows = _fetch_network_rows(layer, args, include_geom)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))

        graph = _build_network_graph(rows, options=options)
        if graph.number_of_nodes() == 0:
            return ToolResult(ok=True, data={"layer": layer_name, "path_found": False, "reason": "empty_graph"})

        start_node, start_snap_m = _nearest_graph_node(graph, start_lon, start_lat)
        end_node, end_snap_m = _nearest_graph_node(graph, end_lon, end_lat)
        if start_node is None or end_node is None:
            return ToolResult(ok=True, data={"layer": layer_name, "path_found": False, "reason": "unable_to_snap_nodes"})
        if start_snap_m > max_snap_distance_m or end_snap_m > max_snap_distance_m:
            return ToolResult(ok=True, data={"layer": layer_name, "path_found": False, "reason": "snap_distance_exceeded"})

        try:
            path_nodes = nx.shortest_path(graph, source=start_node, target=end_node, weight="weight")
        except nx.NetworkXNoPath:
            return ToolResult(ok=True, data={"layer": layer_name, "path_found": False, "reason": "no_path"})

        path_items = []
        segment_ids = []
        segment_types = []
        total_length_m = 0.0
        total_cost = 0.0

        for i in range(len(path_nodes) - 1):
            edge = graph[path_nodes[i]][path_nodes[i + 1]]
            segment_ids.append(edge["segment_id"])
            segment_types.append(edge.get("segment_type"))
            total_length_m += float(edge.get("length_m") or 0.0)
            total_cost += float(edge.get("weight") or 0.0)

            item = {
                "segment_id": edge["segment_id"],
                "segment_name": edge.get("segment_name"),
                "segment_type": edge.get("segment_type"),
                "length_m": float(edge.get("length_m") or 0.0),
                "edge_cost": float(edge.get("weight") or 0.0),
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
                "metric": options["metric"],
                "path_found": True,
                "start_point": {"lon": start_lon, "lat": start_lat},
                "end_point": {"lon": end_lon, "lat": end_lat},
                "start_snap_node": {"lon": start_node[0], "lat": start_node[1]},
                "end_snap_node": {"lon": end_node[0], "lat": end_node[1]},
                "start_snap_m": start_snap_m,
                "end_snap_m": end_snap_m,
                "segment_ids": segment_ids,
                "segment_types": segment_types,
                "total_length_m": total_length_m,
                "total_cost": total_cost,
                "node_count": len(path_nodes),
                "path_items": path_items,
                "cost_config": {
                    "length_weight": options["length_weight"],
                    "segment_type_costs": options["segment_type_costs"],
                    "segment_penalties": options["segment_penalties"],
                    "segment_type_penalties": options["segment_type_penalties"],
                },
                "restrictions_applied": {
                    "forbidden_segment_ids": sorted(options["forbidden_segment_ids"]),
                    "forbidden_segment_types": sorted(options["forbidden_segment_types"]),
                    "max_segment_length_m": options["max_segment_length_m"],
                },
            },
        )


@register_tool
class SpatialNetworkServiceAreaTool(BaseTool):
    name = "spatial.network_service_area"
    description = "Calcula el área/alcance de servicio sobre topología de red desde un origen con límites por coste o distancia."
    input_schema = {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "origin_point": {
                "type": "object",
                "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
                "required": ["lon", "lat"],
            },
            "max_cost": {"type": "number"},
            "max_distance_m": {"type": "number"},
            "metric": {"type": "string", "enum": ["length", "cost"]},
            "length_weight": {"type": "number"},
            "segment_type_field": {"type": "string"},
            "segment_type_costs": {"type": "object"},
            "segment_penalties": {"type": "object"},
            "segment_type_penalties": {"type": "object"},
            "restrictions": {"type": "object"},
            "bbox": {"type": "object"},
            "include_geom": {"type": "boolean"},
            "max_snap_distance_m": {"type": "number"},
        },
        "required": ["layer", "origin_point"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        layer_name = (args.get("layer") or "").strip()
        if not layer_name:
            return ToolResult(ok=False, error="layer is required")

        layer = _get_layer_cfg(layer_name)
        if not layer:
            return ToolResult(ok=False, error=f"Unknown layer: {layer_name}")

        origin = args.get("origin_point") or {}
        if origin.get("lon") is None or origin.get("lat") is None:
            return ToolResult(ok=False, error="origin_point.lon and origin_point.lat are required")

        try:
            origin_lon = float(origin["lon"])
            origin_lat = float(origin["lat"])
        except Exception:
            return ToolResult(ok=False, error="origin_point must contain numeric lon/lat")

        include_geom = bool(args.get("include_geom") or False)
        max_snap_distance_m = float(args.get("max_snap_distance_m") or 250.0)
        max_snap_distance_m = max(1.0, min(max_snap_distance_m, 5000.0))

        options = _parse_route_cost_options(args)
        max_cost = args.get("max_cost")
        max_distance_m = args.get("max_distance_m")

        if max_cost is None and max_distance_m is None:
            max_cost = 1500.0

        if max_cost is not None:
            max_cost = max(0.0, float(max_cost))
        if max_distance_m is not None:
            max_distance_m = max(0.0, float(max_distance_m))

        try:
            rows = _fetch_network_rows(layer, args, include_geom)
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))

        graph = _build_network_graph(rows, options=options)
        if graph.number_of_nodes() == 0:
            return ToolResult(ok=True, data={"layer": layer_name, "reachable": False, "reason": "empty_graph"})

        origin_node, origin_snap_m = _nearest_graph_node(graph, origin_lon, origin_lat)
        if origin_node is None:
            return ToolResult(ok=True, data={"layer": layer_name, "reachable": False, "reason": "unable_to_snap_origin"})
        if origin_snap_m > max_snap_distance_m:
            return ToolResult(ok=True, data={"layer": layer_name, "reachable": False, "reason": "snap_distance_exceeded"})

        reachable_nodes, reachable_set, distances = _compute_service_area_from_graph(
            graph,
            origin_node=origin_node,
            max_cost=max_cost,
            max_distance_m=max_distance_m,
        )

        segment_ids = []
        segment_types = []
        total_reachable_length_m = 0.0
        total_reachable_cost = 0.0
        segments = []

        for a, b, edge in graph.edges(data=True):
            if a not in reachable_set or b not in reachable_set:
                continue
            segment_ids.append(edge["segment_id"])
            segment_types.append(edge.get("segment_type"))
            total_reachable_length_m += float(edge.get("length_m") or 0.0)
            total_reachable_cost += float(edge.get("weight") or 0.0)

            item = {
                "segment_id": edge["segment_id"],
                "segment_name": edge.get("segment_name"),
                "segment_type": edge.get("segment_type"),
                "length_m": float(edge.get("length_m") or 0.0),
                "edge_cost": float(edge.get("weight") or 0.0),
            }
            if include_geom and edge.get("geom_geojson"):
                geom = edge["geom_geojson"]
                if isinstance(geom, str) and len(geom) > 20_000:
                    geom = geom[:20_000] + "...(truncated)"
                item["geom_geojson"] = geom
            segments.append(item)

        total_network_segments = graph.number_of_edges()
        total_network_length_m = sum(float(edge.get("length_m") or 0.0) for _, _, edge in graph.edges(data=True))
        total_network_cost = sum(float(edge.get("weight") or 0.0) for _, _, edge in graph.edges(data=True))

        coverage_bbox = None
        if reachable_nodes:
            lons = [n[0] for n in reachable_nodes]
            lats = [n[1] for n in reachable_nodes]
            coverage_bbox = {
                "west": min(lons),
                "south": min(lats),
                "east": max(lons),
                "north": max(lats),
            }

        return ToolResult(
            ok=True,
            data={
                "layer": layer_name,
                "reachable": bool(reachable_nodes),
                "origin_point": {"lon": origin_lon, "lat": origin_lat},
                "origin_snap_node": {"lon": origin_node[0], "lat": origin_node[1]},
                "origin_snap_m": origin_snap_m,
                "metric": options["metric"],
                "limits": {
                    "max_cost": max_cost,
                    "max_distance_m": max_distance_m,
                },
                "reachable_node_count": len(reachable_nodes),
                "reachable_segment_count": len(segment_ids),
                "reachable_segment_ids": segment_ids,
                "reachable_segment_types": segment_types,
                "total_reachable_length_m": total_reachable_length_m,
                "total_reachable_cost": total_reachable_cost,
                "coverage_summary": {
                    "total_network_nodes": graph.number_of_nodes(),
                    "total_network_segments": total_network_segments,
                    "total_network_length_m": total_network_length_m,
                    "total_network_cost": total_network_cost,
                    "node_coverage_ratio": (
                        float(len(reachable_nodes)) / float(graph.number_of_nodes())
                        if graph.number_of_nodes() > 0
                        else 0.0
                    ),
                    "segment_coverage_ratio": (
                        float(len(segment_ids)) / float(total_network_segments)
                        if total_network_segments > 0
                        else 0.0
                    ),
                    "length_coverage_ratio": (
                        float(total_reachable_length_m) / float(total_network_length_m)
                        if total_network_length_m > 0
                        else 0.0
                    ),
                    "cost_coverage_ratio": (
                        float(total_reachable_cost) / float(total_network_cost)
                        if total_network_cost > 0
                        else 0.0
                    ),
                },
                "reachable_nodes": [
                    {
                        "lon": node[0],
                        "lat": node[1],
                        "cost_from_origin": float(distances.get(node) or 0.0),
                    }
                    for node in reachable_nodes[:500]
                ],
                "coverage_bbox": coverage_bbox,
                "service_segments": segments,
            },
        )
