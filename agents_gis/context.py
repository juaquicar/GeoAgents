"""
Context variable para el agente activo durante la ejecución de tools GIS.
Permite que get_gis_connection(), _get_layer_cfg(), etc. sean conscientes
del agente sin pasar el objeto por todos los niveles de llamada.
"""
from contextvars import ContextVar

_current_agent: ContextVar = ContextVar("_geoagent_current_agent", default=None)


def get_current_agent():
    """Devuelve el agente activo en el contexto actual, o None."""
    return _current_agent.get()


def set_agent_context(agent):
    """
    Establece el agente en el contexto actual.
    Devuelve un Token que debe usarse para restaurar el estado anterior.
    """
    return _current_agent.set(agent)
