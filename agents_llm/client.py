import json
from typing import Any, Dict, Optional

from openai import OpenAI
from django.conf import settings


def _coerce_float(value: Any, default: float) -> float:
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return default


def get_openai_client() -> OpenAI:
    timeout = _coerce_float(
        getattr(settings, "AGENTS_OPENAI_TIMEOUT_SECONDS", None),
        60.0,
    )
    return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=timeout)


def chat_completion_json(
    *,
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    client = get_openai_client()

    response = client.chat.completions.create(
        model=model or getattr(settings, "AGENTS_DEFAULT_LLM_MODEL", "gpt-4o-mini"),
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def chat_completion_text(
    *,
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    client = get_openai_client()

    response = client.chat.completions.create(
        model=model or getattr(settings, "AGENTS_DEFAULT_LLM_MODEL", "gpt-4o-mini"),
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content or ""
