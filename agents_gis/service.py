from django.conf import settings


def _fetchall_dict(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _get_layer_cfg(layer_name: str):
    layers = getattr(settings, "AGENTS_GIS_LAYERS", [])
    for l in layers:
        if l.get("name") == layer_name:
            return l
    return None