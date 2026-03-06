from copy import deepcopy

from agents_gis.inference import (
    infer_intersection_layers,
    infer_nearby_layer,
)

def normalize_plan(
    plan: dict,
    payload: dict | None = None,
    agent_profile: str = "compact",
    gis_layers_catalog: list | None = None,
) -> dict:
    """
    Devuelve una versión saneada del plan del planner.
    Corrige redundancias, args incoherentes y aplica heurísticas GIS suaves.
    """
    payload = payload or {}
    goal = (payload.get("goal") or "").lower()
    map_context = payload.get("map_context") or {}
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

        # 1) enriquecer args desde map_context
        args = _inject_map_context(name, args, map_context)

        # 2) normalización de args por tool
        args = _normalize_tool_args(name, args)

        # 3) deduplicación exacta tool+args
        signature = _tool_signature(name, args)
        if signature in seen_tool_signatures:
            continue
        seen_tool_signatures.add(signature)

        step["args"] = args
        normalized_steps.append(step)

    # 4) reglas GIS orientadas al objetivo y perfil
    normalized_steps = _apply_gis_goal_rules(
        normalized_steps,
        goal,
        map_context,
        profile=profile,
        gis_layers_catalog=gis_layers_catalog,
    )

    # 5) eliminar redundancias lógicas
    normalized_steps = _remove_redundant_steps(normalized_steps)

    # 6) asegurar un único final al final
    non_final = [s for s in normalized_steps if s.get("type") != "final"]
    normalized_steps = non_final + [{"type": "final"}]

    plan["steps"] = normalized_steps
    return plan


def _tool_signature(name: str, args: dict) -> tuple:
    return name, repr(sorted(args.items())) if isinstance(args, dict) else repr(args)


def _inject_map_context(tool_name: str, args: dict, map_context: dict) -> dict:
    args = deepcopy(args or {})

    bbox = map_context.get("bbox")
    zoom = map_context.get("zoom")

    if tool_name in {
        "spatial.summary",
        "spatial.context_pack",
        "spatial.query_layer",
        "spatial.intersects",
    }:
        if "bbox" not in args and bbox:
            args["bbox"] = bbox

    if tool_name in {"spatial.summary", "spatial.context_pack"}:
        if "zoom" not in args and zoom is not None:
            args["zoom"] = zoom

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

    return args


def _is_compact(profile: str) -> bool:
    return profile == "compact"


def _is_rich(profile: str) -> bool:
    return profile == "rich"


def _is_investigate(profile: str) -> bool:
    return profile == "investigate"


def _step_has_required_intersects_args(step: dict) -> bool:
    if step.get("type") != "tool":
        return False
    if step.get("name") != "spatial.intersects":
        return False

    args = step.get("args") or {}
    return bool(args.get("source_layer")) and bool(args.get("target_layer"))


def _apply_gis_goal_rules(
    steps: list,
    goal: str,
    map_context: dict,
    profile: str = "compact",
    gis_layers_catalog: list | None = None,
) -> list:
    """
    Reescribe el plan con heurísticas GIS simples.
    Conservador: corrige/completa, no replantea todo el plan salvo casos claros.

    PRIORIDAD:
    1) intersección
    2) proximidad
    3) exploración de capa
    4) resumen general
    """
    goal = (goal or "").lower()
    gis_layers_catalog = gis_layers_catalog or []

    tool_steps = [s for s in steps if s.get("type") == "tool"]

    has_context_pack = any(s.get("name") == "spatial.context_pack" for s in tool_steps)
    has_nearby = any(s.get("name") == "spatial.nearby" for s in tool_steps)
    has_intersects = any(s.get("name") == "spatial.intersects" for s in tool_steps)
    has_query_layer = any(s.get("name") == "spatial.query_layer" for s in tool_steps)

    bbox = map_context.get("bbox")
    zoom = map_context.get("zoom")

    # ------------------------------------------------------------
    # 1) INTERSECTION FIRST
    # ------------------------------------------------------------
    if _goal_is_intersection(goal):
        valid_intersects_steps = [
            s for s in tool_steps if _step_has_required_intersects_args(s)
        ]
        has_valid_intersects = len(valid_intersects_steps) > 0

        if has_valid_intersects:
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
                    {
                        "type": "tool",
                        "name": "spatial.context_pack",
                        "args": {
                            "bbox": bbox,
                            "zoom": zoom,
                            "profile": "rich",
                        },
                        "required": False,
                    },
                )
            return steps

        inferred_layers = infer_intersection_layers(goal, gis_layers_catalog)
        source_layer = inferred_layers.get("source_layer")
        target_layer = inferred_layers.get("target_layer")

        intersects_step = {
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
                return [intersects_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, intersects_step)

        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                {
                    "type": "tool",
                    "name": "spatial.context_pack",
                    "args": {
                        "bbox": bbox,
                        "zoom": zoom,
                        "profile": "rich",
                    },
                    "required": False,
                },
            )

        return steps

    # ------------------------------------------------------------
    # 2) NEARBY SECOND
    # ------------------------------------------------------------
    if _goal_is_nearby(goal):
        if has_nearby:
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
                    {
                        "type": "tool",
                        "name": "spatial.context_pack",
                        "args": {
                            "bbox": bbox,
                            "zoom": zoom,
                            "profile": "rich",
                        },
                        "required": False,
                    },
                )
            return steps

        inferred_nearby_layer = infer_nearby_layer(goal, gis_layers_catalog)

        nearby_step = {
            "type": "tool",
            "name": "spatial.nearby",
            "args": {
                "layer": inferred_nearby_layer,
                "point": _bbox_center(bbox) if bbox else {"lon": 0.0, "lat": 0.0},
                "radius_m": 250,
                "limit": 10,
            },
            "required": bool(inferred_nearby_layer and _is_compact(profile)),
        }

        if _is_compact(profile):
            if inferred_nearby_layer:
                return [nearby_step, {"type": "final"}]
            return steps

        steps = _insert_before_final(steps, nearby_step)

        if _goal_requests_general_context(goal) and not has_context_pack and bbox:
            steps = _insert_before_final(
                steps,
                {
                    "type": "tool",
                    "name": "spatial.context_pack",
                    "args": {
                        "bbox": bbox,
                        "zoom": zoom,
                        "profile": "rich",
                    },
                    "required": False,
                },
            )
        return steps

    # ------------------------------------------------------------
    # 3) LAYER EXPLORATION
    # ------------------------------------------------------------
    if _goal_is_layer_exploration(goal):
        if has_query_layer:
            if _is_compact(profile):
                return _keep_only_tools(steps, {"spatial.query_layer"})
            return steps
        return steps

    # ------------------------------------------------------------
    # 4) GENERAL SUMMARY LAST
    # ------------------------------------------------------------
    if _goal_is_general_summary(goal):
        if has_context_pack:
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
            context_step = {
                "type": "tool",
                "name": "spatial.context_pack",
                "args": {
                    "bbox": bbox,
                    "zoom": zoom,
                    "profile": "compact" if _is_compact(profile) else "rich",
                },
                "required": True,
            }

            if _is_compact(profile):
                return [context_step, {"type": "final"}]

            return _insert_before_final(steps, context_step)

    return steps


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
    """
    Para perfiles intermedios: mantener tool principal y una secundaria útil.
    """
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
    """
    Reglas simples de redundancia.
    """
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
        "resume",
        "resumen",
        "analiza",
        "analizar",
        "qué hay",
        "que hay",
        "qué existe",
        "contexto espacial",
        "trozo de mapa",
        "elementos detectados",
        "hazme un resumen",
        "resumir",
    ]
    return any(k in goal for k in keywords)


def _goal_requests_general_context(goal: str) -> bool:
    keywords = [
        "contexto",
        "contexto general",
        "resumen",
        "resume",
        "analiza también",
        "explicando además el contexto",
        "además del contexto",
        "panorama general",
        "visión general",
    ]
    return any(k in goal for k in keywords)


def _goal_is_nearby(goal: str) -> bool:
    keywords = [
        "cerca",
        "cercano",
        "proximidad",
        "alrededor",
        "nearby",
        "near",
    ]
    return any(k in goal for k in keywords)


def _goal_is_intersection(goal: str) -> bool:
    keywords = [
        "intersección",
        "interseccion",
        "intersecta",
        "intersectan",
        "dentro de",
        "caen dentro",
        "están dentro",
        "estan dentro",
        "solapan",
        "solape",
        "cruzan",
        "cross",
        "within",
        "contains",
    ]
    return any(k in goal for k in keywords)


def _goal_is_layer_exploration(goal: str) -> bool:
    keywords = [
        "explora la capa",
        "explorar la capa",
        "consulta la capa",
        "query layer",
        "ver la capa",
    ]
    return any(k in goal for k in keywords)


def _bbox_center(bbox: dict | None) -> dict:
    if not bbox:
        return {"lon": 0.0, "lat": 0.0}

    return {
        "lon": (float(bbox["west"]) + float(bbox["east"])) / 2.0,
        "lat": (float(bbox["south"]) + float(bbox["north"])) / 2.0,
    }


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