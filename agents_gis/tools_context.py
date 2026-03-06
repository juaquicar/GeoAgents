from django.conf import settings

from agents_tools.base import BaseTool, ToolResult
from agents_tools.registry import register_tool

from .tools_spatial import SpatialSummaryTool
from .tools_nearby import SpatialNearbyTool
from .tools_intersects import SpatialIntersectsTool


def _layer_priority_key(layer_item: dict):
    """
    Orden simple de relevancia:
    1) más count
    2) si tiene geom_types
    """
    return (
        int(layer_item.get("count", 0)),
        len(layer_item.get("geom_types", []) or []),
    )


def _build_highlights(summary_data: dict) -> list[str]:
    highlights = []

    layers = summary_data.get("layers", []) or []
    non_empty = [l for l in layers if int(l.get("count", 0)) > 0]

    if not non_empty:
        return ["No se han encontrado elementos en las capas consultadas dentro del bbox."]

    highlights.append(f"Se han detectado {len(non_empty)} capas con elementos dentro del bbox.")

    # capa más poblada
    top_layer = max(non_empty, key=lambda x: int(x.get("count", 0)))
    highlights.append(
        f"La capa con mayor presencia es '{top_layer.get('name')}' con {top_layer.get('count')} elementos."
    )

    # tipos geométricos dominantes
    geom_msgs = []
    for layer in non_empty[:5]:
        geom_types = layer.get("geom_types", []) or []
        if geom_types:
            dominant = geom_types[0]
            geom_msgs.append(
                f"{layer.get('name')}: predominan geometrías {dominant.get('geom_type')} ({dominant.get('n')})."
            )
    highlights.extend(geom_msgs[:3])

    return highlights


@register_tool
class SpatialContextPackTool(BaseTool):
    name = "spatial.context_pack"
    description = "Construye un paquete de contexto espacial compacto listo para análisis por LLM."
    input_schema = {
        "type": "object",
        "properties": {
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
            "zoom": {"type": "integer"},
            "profile": {"type": "string"},          # compact | rich
            "layers": {"type": "array"},
            "per_layer_limit": {"type": "integer"},
            "include_geom": {"type": "boolean"},
            "simplify_meters": {"type": "number"},
            "nearby": {"type": "array"},
            "intersections": {"type": "array"},
        },
        "required": ["bbox"],
    }

    def invoke(self, *, args, run=None, user=None, **kwargs) -> ToolResult:
        bbox = args["bbox"]
        zoom = args.get("zoom")
        profile = (args.get("profile") or "compact").strip().lower()
        if profile not in {"compact", "rich"}:
            profile = "compact"

        layers = args.get("layers")
        per_layer_limit = int(args.get("per_layer_limit") or (5 if profile == "compact" else 10))
        include_geom = bool(args.get("include_geom") or False)
        simplify_meters = float(args.get("simplify_meters") or 0.0)

        nearby_requests = args.get("nearby") or []
        intersections_requests = args.get("intersections") or []

        # 1) Summary base
        summary_tool = SpatialSummaryTool()
        summary_res = summary_tool.invoke(
            args={
                "bbox": bbox,
                "zoom": zoom,
                "layers": layers,
                "per_layer_limit": per_layer_limit,
                "random_sample": profile == "rich",
                "include_geom": include_geom if profile == "rich" else False,
                "simplify_meters": simplify_meters,
            },
            run=run,
            user=user,
        )
        if not summary_res.ok:
            return summary_res

        summary_data = summary_res.data

        # 2) Ordenar capas por relevancia
        layers_sorted = sorted(
            summary_data.get("layers", []),
            key=_layer_priority_key,
            reverse=True,
        )

        # 3) Compactar samples para LLM
        compact_layers = []
        for layer in layers_sorted:
            samples = layer.get("samples", []) or []
            compact_samples = []

            for s in samples:
                item = {
                    k: v
                    for k, v in s.items()
                    if k not in {"geom_geojson"}  # en compact evitamos payload pesado
                }

                if profile == "rich" and include_geom and "geom_geojson" in s:
                    item["geom_geojson"] = s["geom_geojson"]

                compact_samples.append(item)

            compact_layers.append(
                {
                    "name": layer.get("name"),
                    "table": layer.get("table"),
                    "count": layer.get("count", 0),
                    "geom_types": layer.get("geom_types", []),
                    "samples": compact_samples,
                }
            )

        # 4) Highlights heurísticos
        highlights = _build_highlights(
            {
                "layers": compact_layers
            }
        )

        # 5) Nearby opcional
        nearby_results = []
        if nearby_requests:
            nearby_tool = SpatialNearbyTool()
            for req in nearby_requests[:10]:
                req_args = dict(req)
                req_args.setdefault("limit", 5)
                req_args.setdefault("include_geom", False if profile == "compact" else include_geom)
                req_args.setdefault("simplify_meters", simplify_meters)

                res = nearby_tool.invoke(args=req_args, run=run, user=user)
                nearby_results.append(
                    {
                        "request": req_args,
                        "ok": res.ok,
                        "data": res.data if res.ok else {},
                        "error": res.error if not res.ok else "",
                    }
                )

        # 6) Intersections opcional
        intersections_results = []
        if intersections_requests:
            inter_tool = SpatialIntersectsTool()
            for req in intersections_requests[:10]:
                req_args = dict(req)
                req_args.setdefault("bbox", bbox)
                req_args.setdefault("limit", 5)
                req_args.setdefault("include_geom", False if profile == "compact" else include_geom)
                req_args.setdefault("simplify_meters", simplify_meters)

                res = inter_tool.invoke(args=req_args, run=run, user=user)
                intersections_results.append(
                    {
                        "request": req_args,
                        "ok": res.ok,
                        "data": res.data if res.ok else {},
                        "error": res.error if not res.ok else "",
                    }
                )

        # 7) Resumen ejecutivo
        total_features = sum(int(l.get("count", 0)) for l in compact_layers)
        non_empty_layers = [l for l in compact_layers if int(l.get("count", 0)) > 0]

        executive_summary = {
            "total_layers_consulted": len(compact_layers),
            "non_empty_layers": len(non_empty_layers),
            "total_features_detected": total_features,
            "top_layers": [
                {
                    "name": l.get("name"),
                    "count": l.get("count", 0),
                }
                for l in compact_layers[:5]
            ],
        }

        return ToolResult(
            ok=True,
            data={
                "bbox": summary_data.get("bbox"),
                "zoom": summary_data.get("zoom"),
                "profile": profile,
                "executive_summary": executive_summary,
                "highlights": highlights,
                "layers": compact_layers,
                "nearby": nearby_results,
                "intersections": intersections_results,
            },
        )