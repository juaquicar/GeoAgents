import json
import re
from typing import Any, Dict, List, Optional


def _extract_step_refs_from_args(args: Any) -> List[str]:
    """Extrae ids de steps referenciados via '$step:ID.xxx' en los args."""
    text = json.dumps(args) if not isinstance(args, str) else args
    return list({m for m in re.findall(r"\$step:([a-zA-Z0-9_\-]+)\.", text)})




def validate_plan(plan: dict) -> dict:
    steps = plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise ValueError("Planner returned invalid or empty steps")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Planner step {i} is not an object")

        step_type = step.get("type")
        if step_type not in {"tool", "final"}:
            raise ValueError(f"Planner step {i} has invalid type: {step_type}")

        if step_type == "tool":
            if not step.get("id"):
                step["id"] = f"s{i+1}"
            if not step.get("name"):
                raise ValueError(f"Planner tool step {i} missing name")
            if "args" not in step:
                step["args"] = {}
            if not isinstance(step.get("args"), dict):
                raise ValueError(f"Planner tool step {i} args must be an object")

            if "required" not in step:
                step["required"] = True
            if "depends_on" not in step:
                step["depends_on"] = []
            if not isinstance(step.get("depends_on"), list):
                raise ValueError(f"Planner tool step {i} has invalid depends_on")

            if "on_fail" not in step:
                step["on_fail"] = "abort" if step["required"] else "continue"
            if step.get("on_fail") not in {"abort", "continue"}:
                raise ValueError(f"Planner tool step {i} has invalid on_fail")

            hypothesis = step.get("hypothesis")
            if hypothesis is not None and not isinstance(hypothesis, str):
                raise ValueError(f"Planner tool step {i} has invalid hypothesis")

            verification_target = step.get("verification_target")
            if verification_target is not None and not isinstance(verification_target, str):
                raise ValueError(f"Planner tool step {i} has invalid verification_target")

            step["success_criteria"] = _normalize_success_criteria(step.get("success_criteria"))

            timeout_s = step.get("timeout_s", 0) or 0
            max_retries = step.get("max_retries", 0) or 0
            retry_backoff_s = step.get("retry_backoff_s", 0) or 0

            if not isinstance(timeout_s, (int, float)) or timeout_s < 0:
                raise ValueError(f"Planner tool step {i} has invalid timeout_s")
            if not isinstance(max_retries, int) or max_retries < 0:
                raise ValueError(f"Planner tool step {i} has invalid max_retries")
            if not isinstance(retry_backoff_s, (int, float)) or retry_backoff_s < 0:
                raise ValueError(f"Planner tool step {i} has invalid retry_backoff_s")

            step["timeout_s"] = timeout_s
            step["max_retries"] = max_retries
            step["retry_backoff_s"] = retry_backoff_s
            step["can_replan"] = bool(step.get("can_replan", False))

        if step_type == "final":
            step.pop("required", None)
            step.pop("depends_on", None)
            step.pop("on_fail", None)
            step.pop("hypothesis", None)
            step.pop("verification_target", None)
            step.pop("success_criteria", None)
            step.pop("timeout_s", None)
            step.pop("max_retries", None)
            step.pop("retry_backoff_s", None)
            step.pop("can_replan", None)

    # Auto-rename ids duplicados: si el LLM genera dos steps con el mismo id, renombrar
    # el duplicado (sufijo _b, _c, ...) en lugar de rechazar el plan.
    tool_step_ids = [s.get("id") for s in steps if s.get("type") == "tool"]
    if len(tool_step_ids) != len(set(tool_step_ids)):
        seen_ids: set = set()
        for step in steps:
            if step.get("type") != "tool":
                continue
            orig_id = step.get("id") or ""
            if orig_id in seen_ids:
                suffix_ord = ord("b")
                new_id = orig_id + "_b"
                while new_id in seen_ids:
                    suffix_ord += 1
                    new_id = orig_id + "_" + chr(suffix_ord)
                step["id"] = new_id
            seen_ids.add(step.get("id") or "")

    # Inferir depends_on implícitos desde referencias $step:ID en los args.
    # El LLM a veces usa "$step:s1.data.items.0.lon" sin declarar depends_on: [s1].
    all_ids_set = {s.get("id") for s in steps if s.get("type") == "tool"}
    for step in steps:
        if step.get("type") != "tool":
            continue
        inferred = _extract_step_refs_from_args(step.get("args") or {})
        existing_deps = set(step.get("depends_on") or [])
        new_deps = [ref for ref in inferred if ref in all_ids_set and ref not in existing_deps]
        if new_deps:
            step["depends_on"] = list(existing_deps) + new_deps

    # Ordenar topológicamente los tool steps para tolerar planes donde el LLM
    # generó los pasos en orden incorrecto pero con depends_on correcto.
    plan["steps"] = _toposort_steps(steps)
    steps = plan["steps"]

    # Limpiar dependencias a steps desconocidos (el LLM a veces referencia ids que no existen)
    all_tool_ids = {s.get("id") for s in steps if s.get("type") == "tool"}
    for step in steps:
        if step.get("type") == "tool":
            valid_deps = [dep for dep in step.get("depends_on", []) if dep in all_tool_ids]
            step["depends_on"] = valid_deps

    # Verificar que no hay forward references después del toposort (indicaría ciclo)
    seen_ids: set = set()
    for i, step in enumerate(steps):
        if step.get("type") != "tool":
            continue
        step_id = step.get("id")
        for dep in step.get("depends_on", []):
            if dep not in seen_ids:
                raise ValueError(
                    f"Planner step {i} depends on future step id after toposort: {dep} (ciclo detectado)"
                )
        seen_ids.add(step_id)

    if steps[-1].get("type") != "final":
        raise ValueError("Planner must end with a final step")

    return plan


def _toposort_steps(steps: list) -> list:
    """
    Reordena los tool steps según sus depends_on usando Kahn's algorithm.
    Los steps de tipo 'final' se preservan al final.
    Si no hay dependencias forward, el orden original se mantiene.
    """
    tool_steps = [s for s in steps if s.get("type") == "tool"]
    final_steps = [s for s in steps if s.get("type") != "tool"]

    if not tool_steps:
        return steps

    # Grado de entrada y mapa de hijos
    step_by_id = {s["id"]: s for s in tool_steps}
    in_degree = {s["id"]: 0 for s in tool_steps}
    children: dict[str, list[str]] = {s["id"]: [] for s in tool_steps}

    for step in tool_steps:
        for dep in step.get("depends_on", []):
            if dep in in_degree:
                in_degree[step["id"]] += 1
                children[dep].append(step["id"])

    # Inicializar cola con nodos sin dependencias (en orden original para estabilidad)
    queue = [s["id"] for s in tool_steps if in_degree[s["id"]] == 0]
    sorted_ids: list[str] = []

    while queue:
        node = queue.pop(0)
        sorted_ids.append(node)
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(sorted_ids) != len(tool_steps):
        # Hay un ciclo — devolver el orden original y dejar que la validación falle
        return steps

    return [step_by_id[sid] for sid in sorted_ids] + final_steps


def _normalize_success_criteria(criteria: Any) -> Dict[str, Any]:
    if criteria is None:
        return {}

    if not isinstance(criteria, dict):
        raise ValueError("Planner success_criteria must be an object")

    normalized = dict(criteria)

    path = normalized.get("path")
    if path is not None and not isinstance(path, str):
        raise ValueError("Planner success_criteria.path must be a string")

    supported_ops = {
        "equals",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "non_empty",
        "in",
    }
    present_ops = [op for op in supported_ops if op in normalized]
    if normalized and not path:
        raise ValueError("Planner success_criteria requires path when operators are present")
    if len(present_ops) > 1:
        raise ValueError("Planner success_criteria supports only one operator per step")

    return normalized




def validate_plan_gis_references(plan: dict, gis_layers_catalog: list) -> dict:
    valid_layer_names = {layer.get("name") for layer in gis_layers_catalog}

    for i, step in enumerate(plan.get("steps", [])):
        if step.get("type") != "tool":
            continue

        name = step.get("name")
        args = step.get("args") or {}

        if name in {"spatial.query_layer", "spatial.nearby"}:
            layer = args.get("layer")
            if layer and layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown GIS layer at step {i}: {layer}")

        if name == "spatial.intersects":
            source_layer = args.get("source_layer")
            target_layer = args.get("target_layer")

            if source_layer and source_layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown source_layer at step {i}: {source_layer}")
            if target_layer and target_layer not in valid_layer_names:
                raise ValueError(f"Planner proposed unknown target_layer at step {i}: {target_layer}")

        if name == "spatial.context_pack":
            nearby = args.get("nearby") or []
            intersections = args.get("intersections") or []

            for j, item in enumerate(nearby):
                layer = item.get("layer")
                if layer and layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown nearby.layer at step {i}, item {j}: {layer}"
                    )

            for j, item in enumerate(intersections):
                source_layer = item.get("source_layer")
                target_layer = item.get("target_layer")

                if source_layer and source_layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown intersections.source_layer at step {i}, item {j}: {source_layer}"
                    )
                if target_layer and target_layer not in valid_layer_names:
                    raise ValueError(
                        f"Planner proposed unknown intersections.target_layer at step {i}, item {j}: {target_layer}"
                    )

    return plan
