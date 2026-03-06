from .registry import REGISTRY


def export_tools_catalog(tool_names=None):
    """
    Devuelve catálogo serializable de tools registradas.
    Si tool_names viene informado, filtra por esos nombres.
    """
    allowed = set(tool_names or [])
    out = []

    for tool in REGISTRY.list():
        if allowed and tool.name not in allowed:
            continue

        out.append(
            {
                "name": tool.name,
                "description": getattr(tool, "description", ""),
                "input_schema": getattr(tool, "input_schema", {}),
            }
        )

    return out


