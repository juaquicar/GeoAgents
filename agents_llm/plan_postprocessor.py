from copy import deepcopy

from agents_gis.inference import (
    infer_intersection_layers,
    infer_nearby_layer,
    infer_query_layer,
    infer_network_layer,
)


def normalize_plan(
    plan: dict,
    payload: dict | None = None,
    agent_profile: str = "compact",
    gis_layers_catalog: list | None = None,
) -> dict:
    payload = payload or {}
    goal = (payload.get("goal") or "").lower()
    map_context = payload.get("map_context") or {}
    trace_context = payload.get("trace_context") or {}
    profile = agent_profile or "compact"
    gis_layers_catalog = gis_layers_catalog or []

    plan = deepcopy(plan)
    steps = plan.get("steps", [])

    normalized_steps = []
    seen_tool_signatures = set()

    for step in steps:
        step_type = step.get("type")

        if step_type != "tool":
            normalized_steps.append(step)
            continue

        name = step.get("name", "")
        args = step.get("args") or {}

        args = _inject_map_context(name, args, map_context, trace_context)
        args = _inject_gis_inference(name, args, goal, gis_layers_catalog)
        args = _normalize_tool_args(name, args)

        signature = _tool_signature(name, args)
        if signature in seen_tool_signatures:
            continue
        seen_tool_signatures.add(signature)

        step["args"] = args
        normalized_steps.append(step)

    normalized_steps = _apply_gis_goal_rules(
        normalized_steps,
        goal,
        map_context,
        trace_context,
        profile=profile,
        gis_layers_catalog=gis_layers_catalog,
    )

    normalized_steps = _remove_redundant_steps(normalized_steps)

    non_final = [s for s in normalized_steps if s.get("type") != "final"]
    normalized_steps = non_final + [{"type": "final"}]

    plan["steps"] = normalized_steps
    return plan


def _tool_signature(name: str, args: dict) -> tuple:
    return name, repr(sorted(args.items())) if isinstance(args, dict) else repr(args)


def _inject_map_context(
    tool_name: str,
    args: dict,
    map_context: dict,
    trace_context: dict | None = None,
) -> dict:
    args = deepcopy(args or {})
    trace_context = trace_context or {}

    bbox = map_context.get("bbox")
    zoom = map_context.get("zoom")

    if tool_name in {
        "spatial.summary",
        "spatial.context_pack",
        "spatial.query_layer",
        "spatial.intersects",
        "spatial.network_trace",
    }:
        if "bbox" not in args and bbox:
            args["bbox"] = bbox

    if tool_name in {"spatial.summary", "spatial.context_pack"}:
        if "zoom" not in args and zoom is not None:
            args["zoom"] = zoom

    if tool_name == "spatial.network_trace":
        if "start_point" not in args and trace_context.get("start_point"):
            args["start_point"] = trace_context["start_point"]
        if "end_point" not in args and trace_context.get("end_point"):
            args["end_point"] = trace_context["end_point"]



    return args


def _inject_gis_inference(
    tool_name: str,
    args: dict,
    goal: str,
    gis_layers_catalog: list | None,
) -> dict:
    args = deepcopy(args or {})
    gis_layers_catalog = gis_layers_catalog or []

    if tool_name == "spatial.intersects":
        inferred = infer_intersection_layers(goal, gis_layers_catalog)
        if not args.get("source_layer"):
            args["source_layer"] = inferred.get("source_layer")
        if not args.get("target_layer"):
            args["target_layer"] = inferred.get("target_layer")

    elif tool_name == "spatial.nearby":
        if not args.get("layer"):
            args["layer"] = infer_nearby_layer(goal, gis_layers_catalog)

    elif tool_name == "spatial.query_layer":
        if not args.get("layer"):
            args["layer"] = infer_query_layer(goal, gis_layers_catalog)

    elif tool_name == "spatial.network_trace":
        if not args.get("layer"):
            args["layer"] = infer_network_layer(goal, gis_layers_catalog)

    return args


def _normalize_tool_args(tool_name: str, args: dict) -> dict:
    args = deepcopy(args or {})

    if tool_name in {"spatial.summary", "spatial.context_pack"}:
        if "per_layer_limit" in args:
            try:
                args["per_layer_limit"] = max(1, min(int(args["per_layer_limit"]), 50))
            except Exception:
                args["per_layer_limit"] = 10

        if "simplify_meters" in args:
            try:
                args["simplify_meters"] = max(0.0, min(float(args["simplify_meters"]), 50.0))
            except Exception:
                args["simplify_meters"] = 0.0

        if args.get("layers") == []:
            args.pop("layers", None)

        if "random_sample" in args:
            args["random_sample"] = bool(args["random_sample"])

        if "include_geom" in args:
            args["include_geom"] = bool(args["include_geom"])

    if tool_name in {"spatial.query_layer", "spatial.nearby", "spatial.intersects"}:
        if "limit" in args:
            try:
                args["limit"] = max(1, min(int(args["limit"]), 200))
            except Exception:
                args["limit"] = 50
        else:
            args["limit"] = 50

        if "offset" in args:
            try:
                args["offset"] = max(0, int(args["offset"]))
            except Exception:
                args["offset"] = 0
        else:
            args["offset"] = 0

        if "simplify_meters" in args:
            try:
                args["simplify_meters"] = max(0.0, min(float(args["simplify_meters"]), 50.0))
            except Exception:
                args["simplify_meters"] = 0.0

        if "include_geom" in args:
            args["include_geom"] = bool(args["include_geom"])

    if tool_name == "spatial.nearby":
        if "radius_m" in args:
            try:
                args["radius_m"] = max(1.0, min(float(args["radius_m"]), 50000.0))
            except Exception:
                args["radius_m"] = 250.0
        else:
            args["radius_m"] = 250.0

    if tool_name == "spatial.network_trace":
        if "include_geom" in args:
            args["include_geom"] = bool(args["include_geom"])
        else:
            args["include_geom"] = True

        if "max_snap_distance_m" in args:
            try:
                args["max_snap_distance_m"] = max(1.0, min(float(args["max_snap_distance_m"]), 5000.0))
            except Exception:
                args["max_snap_distance_m"] = 250.0
        else:
            args["max_snap_distance_m"] = 250.0

    return args


def _is_compact(profile: str) -> bool:
    return profile == "compact"


def _is_rich(profile: str) -> bool:
    return profile == "rich"


def _is_investigate(profile: str) -> bool:
    return profile == "investigate"


def _step_has_required_intersects_args(step: dict) -> bool:
    if step.get("type") != "tool" or step.get("name") != "spatial.intersects":
        return False
    args = step.get("args") or {}
    return bool(args.get("source_layer")) and bool(args.get("target_layer"))


def _step_has_required_nearby_args(step: dict) -> bool:
    if step.get("type") != "tool" or step.get("name") != "spatial.nearby":
        return False
    args = step.get("args") or {}
    return bool(args.get("layer")) and bool(args.get("point"))


def _step_has_required_query_layer_args(step: dict) -> bool:
    if step.get("type") != "tool" or step.get("name") != "spatial.query_layer":
        return False
    args = step.get("args") or {}
    return bool(args.get("layer"))

def _is_valid_lonlat_point(point: dict | None) -> bool:
    if not isinstance(point, dict):
        return False
    if point.get("lon") is None or point.get("lat") is None:
        return False
    return True

def _step_has_required_network_trace_args(step: dict) -> bool:
    if step.get("type") != "tool":
        return False

    if step.get("name") != "spatial.network_trace":
        return False

    args = step.get("args") or {}
    has_layer = bool(args.get("layer"))
    has_start = _is_valid_lonlat_point(args.get("start_point"))
    has_end = _is_valid_lonlat_point(args.get("end_point"))

    return (
        has_layer and has_start and has_end
    )


def _apply_gis_goal_rules(
    steps: list,
    goal: str,
    map_context: dict,
    trace_context: dict | None = None,
    profile: str = "compact",
    gis_layers_catalog: list | None = None,
) -> list:
    goal = (goal or "").lower()
    trace_context = trace_context or {}
    gis_layers_catalog = gis_layers_catalog or []

    tool_steps = [s for s in steps if s.get("type") == "tool"]
    has_context_pack = any(s.get("name") == "spatial.context_pack" for s in tool_steps)

    bbox = map_context.get("bbox")
    zoom = map_context.get("zoom")

    # 1) INTERSECTION
    if _goal_is_intersection(goal):
        valid_steps = [s for s in tool_steps if _step_has_required_intersects_args(s)]
        has_valid = len(valid_steps) > 0

        if has_valid:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.intersects"})
            if _is_rich(profile):
                if _goal_requests_general_context(goal):
                    return _prefer_primary_plus_optional(
                        steps,
                        primary={"spatial.intersects"},
                        secondary={"spatial.context_pack"},
                    )
                return _keep_only_tools(steps, {"spatial.intersects"})
            if _goal_requests_general_context(goal) and not has_context_pack and bbox:
                steps = _insert_before_final(
                    steps,
                    _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
                )
            return steps

        inferred = infer_intersection_layers(goal, gis_layers_catalog)
        source_layer = inferred.get("source_layer")
        target_layer = inferred.get("target_layer")

        new_step = {
            "type": "tool",
            "name": "spatial.intersects",
            "args": {
                "source_layer": source_layer,
                "target_layer": target_layer,
                "bbox": bbox,
                "limit": 20,
            },
            "required": bool(source_layer and target_layer and _is_compact(profile)),
        }

        if _is_compact(profile):
            if source_layer and target_layer:
                return [new_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, new_step)
        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
            )
        return steps

    # 2) NETWORK TRACE
    if _goal_is_network_trace(goal):
        valid_steps = [s for s in tool_steps if _step_has_required_network_trace_args(s)]
        has_valid = len(valid_steps) > 0

        if has_valid:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.network_trace"})
            if _is_rich(profile):
                if _goal_requests_general_context(goal):
                    return _prefer_primary_plus_optional(
                        steps,
                        primary={"spatial.network_trace"},
                        secondary={"spatial.context_pack"},
                    )
                return _keep_only_tools(steps, {"spatial.network_trace"})
            if _goal_requests_general_context(goal) and not has_context_pack and bbox:
                steps = _insert_before_final(
                    steps,
                    _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
                )
            return steps

        inferred_layer = infer_network_layer(goal, gis_layers_catalog)
        start_point = trace_context.get("start_point") or _bbox_corner_start(bbox)
        end_point = trace_context.get("end_point") or _bbox_corner_end(bbox)

        new_step = {
            "type": "tool",
            "name": "spatial.network_trace",
            "args": {
                "layer": inferred_layer,
                "bbox": bbox,
                "start_point": start_point,
                "end_point": end_point,
                "include_geom": True,
                "max_snap_distance_m": 250,
            },
            "required": bool(inferred_layer and start_point and end_point and _is_compact(profile)),
        }

        if _is_compact(profile):
            if inferred_layer and start_point and end_point:
                return [new_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, new_step)
        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
            )
        return steps

    # 3) NEARBY
    if _goal_is_nearby(goal):
        valid_steps = [s for s in tool_steps if _step_has_required_nearby_args(s)]
        has_valid = len(valid_steps) > 0

        if has_valid:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.nearby"})
            if _is_rich(profile):
                if _goal_requests_general_context(goal):
                    return _prefer_primary_plus_optional(
                        steps,
                        primary={"spatial.nearby"},
                        secondary={"spatial.context_pack"},
                    )
                return _keep_only_tools(steps, {"spatial.nearby"})
            if _goal_requests_general_context(goal) and not has_context_pack and bbox:
                steps = _insert_before_final(
                    steps,
                    _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
                )
            return steps

        inferred_layer = infer_nearby_layer(goal, gis_layers_catalog)

        new_step = {
            "type": "tool",
            "name": "spatial.nearby",
            "args": {
                "layer": inferred_layer,
                "point": _bbox_center(bbox) if bbox else {"lon": 0.0, "lat": 0.0},
                "radius_m": 250,
                "limit": 10,
            },
            "required": bool(inferred_layer and _is_compact(profile)),
        }

        if _is_compact(profile):
            if inferred_layer:
                return [new_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, new_step)
        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
            )
        return steps

    # 4) QUERY LAYER
    if _goal_is_layer_exploration(goal):
        valid_steps = [s for s in tool_steps if _step_has_required_query_layer_args(s)]
        has_valid = len(valid_steps) > 0

        if has_valid:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.query_layer"})
            if _is_rich(profile):
                if _goal_requests_general_context(goal):
                    return _prefer_primary_plus_optional(
                        steps,
                        primary={"spatial.query_layer"},
                        secondary={"spatial.context_pack"},
                    )
                return _keep_only_tools(steps, {"spatial.query_layer"})
            if _goal_requests_general_context(goal) and not has_context_pack and bbox:
                steps = _insert_before_final(
                    steps,
                    _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
                )
            return steps

        inferred_layer = infer_query_layer(goal, gis_layers_catalog)

        new_step = {
            "type": "tool",
            "name": "spatial.query_layer",
            "args": {
                "layer": inferred_layer,
                "bbox": bbox,
                "limit": 50,
            },
            "required": bool(inferred_layer and _is_compact(profile)),
        }

        if _is_compact(profile):
            if inferred_layer:
                return [new_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, new_step)
        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                _build_context_pack_step(bbox, zoom, required=False, profile="rich"),
            )
        return steps

    # 5) SUMMARY
    if _goal_is_general_summary(goal):
        has_context_pack_step = any(
            s.get("type") == "tool" and s.get("name") == "spatial.context_pack"
            for s in tool_steps
        )

        if has_context_pack_step:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.context_pack"})
            if _is_rich(profile):
                return _prefer_primary_plus_optional(
                    steps,
                    primary={"spatial.context_pack"},
                    secondary={"spatial.query_layer"},
                )
            return steps

        if bbox:
            context_step = _build_context_pack_step(
                bbox=bbox,
                zoom=zoom,
                required=True,
                profile="compact" if _is_compact(profile) else "rich",
            )

            if _is_compact(profile):
                return [context_step, {"type": "final"}]

            return _insert_before_final(steps, context_step)

    return steps


def _build_context_pack_step(
    bbox: dict | None,
    zoom: float | int | None,
    required: bool,
    profile: str = "rich",
) -> dict:
    return {
        "type": "tool",
        "name": "spatial.context_pack",
        "args": {
            "bbox": bbox,
            "zoom": zoom,
            "profile": profile,
        },
        "required": required,
    }


def _keep_only_tools(steps: list, allowed_tool_names: set[str]) -> list:
    out = []
    for step in steps:
        step_type = step.get("type")
        if step_type == "tool":
            if step.get("name") in allowed_tool_names:
                out.append(step)
        elif step_type != "final":
            out.append(step)
    return out + [{"type": "final"}]


def _prefer_primary_plus_optional(
    steps: list,
    primary: set[str],
    secondary: set[str],
) -> list:
    out = []
    kept_secondary = False

    for step in steps:
        step_type = step.get("type")
        if step_type == "tool":
            name = step.get("name")
            if name in primary:
                out.append(step)
            elif name in secondary and not kept_secondary:
                out.append(step)
                kept_secondary = True
        elif step_type != "final":
            out.append(step)

    return out + [{"type": "final"}]


def _remove_redundant_steps(steps: list) -> list:
    has_context_pack = any(
        s.get("type") == "tool" and s.get("name") == "spatial.context_pack"
        for s in steps
    )

    filtered = []
    for step in steps:
        if has_context_pack and step.get("type") == "tool":
            if step.get("name") == "spatial.summary":
                continue
        filtered.append(step)

    non_final = [s for s in filtered if s.get("type") != "final"]
    return non_final + [{"type": "final"}]


def _goal_is_general_summary(goal: str) -> bool:
    keywords = [
        "resume", "resumen", "analiza", "analizar",
        "qué hay", "que hay", "qué existe",
        "contexto espacial", "trozo de mapa",
        "elementos detectados", "hazme un resumen", "resumir",
    ]
    return any(k in goal for k in keywords)


def _goal_requests_general_context(goal: str) -> bool:
    keywords = [
        "contexto", "contexto general", "resumen", "resume",
        "analiza también", "explicando además el contexto",
        "además del contexto", "panorama general", "visión general",
    ]
    return any(k in goal for k in keywords)


def _goal_is_nearby(goal: str) -> bool:
    keywords = [
        "cerca", "cercano", "proximidad",
        "alrededor", "nearby", "near",
    ]
    return any(k in goal for k in keywords)


def _goal_is_intersection(goal: str) -> bool:
    keywords = [
        "intersección", "interseccion",
        "intersecta", "intersectan",
        "dentro de", "caen dentro",
        "están dentro", "estan dentro",
        "solapan", "solape",
        "cruzan", "cross", "within", "contains",
    ]
    return any(k in goal for k in keywords)


def _goal_is_layer_exploration(goal: str) -> bool:
    keywords = [
        "explora la capa", "explorar la capa",
        "consulta la capa", "query layer", "ver la capa",
    ]
    return any(k in goal for k in keywords)


def _goal_is_network_trace(goal: str) -> bool:
    keywords = [
        "traza", "trace",
        "camino", "path",
        "ruta", "route",
        "conecta", "conectar",
        "conectividad",
        "red", "network",
        "segmentos que conectan",
        "tramos que conectan",
    ]
    return any(k in goal for k in keywords)


def _bbox_center(bbox: dict | None) -> dict:
    if not bbox:
        return {"lon": 0.0, "lat": 0.0}

    west = _to_float_or_default(bbox.get("west"), 0.0)
    east = _to_float_or_default(bbox.get("east"), 0.0)
    south = _to_float_or_default(bbox.get("south"), 0.0)
    north = _to_float_or_default(bbox.get("north"), 0.0)

    return {
        "lon": (west + east) / 2.0,
        "lat": (south + north) / 2.0,
    }


def _bbox_corner_start(bbox: dict | None) -> dict:
    if not bbox:
        return {"lon": 0.0, "lat": 0.0}
    return {
        "lon": _to_float_or_default(bbox.get("west"), 0.0),
        "lat": _to_float_or_default(bbox.get("south"), 0.0),
    }


def _bbox_corner_end(bbox: dict | None) -> dict:
    if not bbox:
        return {"lon": 0.0, "lat": 0.0}
    return {
        "lon": _to_float_or_default(bbox.get("east"), 0.0),
        "lat": _to_float_or_default(bbox.get("north"), 0.0),
    }


def _to_float_or_default(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _insert_before_final(steps: list, new_step: dict) -> list:
    existing_tool_names = {
        s.get("name") for s in steps if s.get("type") == "tool"
    }
    if new_step.get("name") in existing_tool_names:
        return steps

    out = []
    inserted = False

    for step in steps:
        if not inserted and step.get("type") == "final":
            out.append(new_step)
            inserted = True
        out.append(step)

    if not inserted:
        out.append(new_step)
        out.append({"type": "final"})

    return out
