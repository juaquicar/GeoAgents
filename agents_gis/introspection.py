from django.conf import settings

# Máximo de campos a incluir en el catálogo enviado al planner.
# Con capas de 70+ campos, el prompt puede superar los límites de contexto del LLM.
_PLANNER_MAX_FIELDS = 25


def export_gis_layers_catalog(*, compact_for_planner: bool = False):
    layers = getattr(settings, "AGENTS_GIS_LAYERS", []) or []

    out = []
    for layer in layers:
        fields = layer.get("fields", [])
        filter_fields = layer.get("filter_fields", [])

        if compact_for_planner and len(fields) > _PLANNER_MAX_FIELDS:
            fields = fields[:_PLANNER_MAX_FIELDS] + [f"...{len(layer.get('fields', [])) - _PLANNER_MAX_FIELDS}_more"]
        if compact_for_planner and len(filter_fields) > _PLANNER_MAX_FIELDS:
            filter_fields = filter_fields[:_PLANNER_MAX_FIELDS] + [f"...{len(layer.get('filter_fields', [])) - _PLANNER_MAX_FIELDS}_more"]

        out.append(
            {
                "name": layer.get("name", ""),
                "table": layer.get("table", ""),
                "geom_col": layer.get("geom_col", "the_geom"),
                "id_col": layer.get("id_col", "id"),
                "fields": fields,
                "filter_fields": filter_fields,

                # Metadatos geométricos explícitos
                "geometry_kind": layer.get("geometry_kind"),
                "geom_family": layer.get("geom_family"),
                "geometry_type": layer.get("geometry_type"),
                "geometry_types": layer.get("geometry_types"),
                "geom_type": layer.get("geom_type"),
                "geom_types": layer.get("geom_types"),
            }
        )
    return out