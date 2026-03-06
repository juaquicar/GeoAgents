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
            }
        )
    return out