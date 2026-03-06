import json
from typing import Any, Dict, List

from .client import chat_completion_text


SYNTHESIZER_SYSTEM_PROMPT = """
Eres un analista de resultados de un framework de agentes.
Debes redactar una respuesta final clara, útil y basada estrictamente en las evidencias disponibles.
No inventes datos.
Si hay contexto GIS, interprétalo espacialmente.
"""


def build_synthesizer_user_prompt(
    *,
    goal: str,
    agent_name: str,
    step_outputs: List[Dict[str, Any]],
) -> str:
    payload = {
        "goal": goal,
        "agent_name": agent_name,
        "step_outputs": step_outputs,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def synthesize_run(
    *,
    goal: str,
    agent_name: str,
    step_outputs: List[Dict[str, Any]],
) -> str:
    user_prompt = build_synthesizer_user_prompt(
        goal=goal,
        agent_name=agent_name,
        step_outputs=step_outputs,
    )
    return chat_completion_text(
        system_prompt=SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.2,
    )