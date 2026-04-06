from django.conf import settings

# Máximo de campos a incluir en el catálogo enviado al planner.
_PLANNER_MAX_FIELDS = 25


def export_gis_layers_catalog(*, compact_for_planner: bool = False, agent=None):
    """
    Devuelve el catálogo de capas GIS.

    Prioridad:
    1. `agent` pasado explícitamente.
    2. Agente en contexto (si hay un run activo).
    3. settings.AGENTS_GIS_LAYERS (fallback global).
    """
    if agent is None:
        from agents_gis.context import get_current_agent
        agent = get_current_agent()

    if agent:
        layers = list(agent.gis_layers_catalog or [])
    else:
        layers = list(getattr(settings, "AGENTS_GIS_LAYERS", []) or [])

    out = []
    for layer in layers:
        fields = layer.get("fields", [])
        filter_fields = layer.get("filter_fields", [])

        if compact_for_planner and len(fields) > _PLANNER_MAX_FIELDS:
            fields = fields[:_PLANNER_MAX_FIELDS] + [
                f"...{len(layer.get('fields', [])) - _PLANNER_MAX_FIELDS}_more"
            ]
        if compact_for_planner and len(filter_fields) > _PLANNER_MAX_FIELDS:
            filter_fields = filter_fields[:_PLANNER_MAX_FIELDS] + [
                f"...{len(layer.get('filter_fields', [])) - _PLANNER_MAX_FIELDS}_more"
            ]

        out.append(
            {
                "name": layer.get("name", ""),
                "table": layer.get("table", ""),
                "geom_col": layer.get("geom_col", "the_geom"),
                "id_col": layer.get("id_col", "id"),
                "fields": fields,
                "filter_fields": filter_fields,
                "geometry_kind": layer.get("geometry_kind"),
                "geom_family": layer.get("geom_family"),
                "geometry_type": layer.get("geometry_type"),
                "geometry_types": layer.get("geometry_types"),
                "geom_type": layer.get("geom_type"),
                "geom_types": layer.get("geom_types"),
            }
        )
    return out


def export_gis_layers_catalog_for_agent(agent):
    """Atajo para exportar el catálogo de un agente concreto (sin contexto)."""
    return export_gis_layers_catalog(agent=agent)
