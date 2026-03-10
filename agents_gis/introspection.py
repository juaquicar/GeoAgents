from django.conf import settings


def export_gis_layers_catalog():
    layers = getattr(settings, "AGENTS_GIS_LAYERS", []) or []

    out = []
    for layer in layers:
        out.append(
            {
                "name": layer.get("name", ""),
                "table": layer.get("table", ""),
                "geom_col": layer.get("geom_col", "the_geom"),
                "id_col": layer.get("id_col", "id"),
                "fields": layer.get("fields", []),
                "filter_fields": layer.get("filter_fields", []),

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