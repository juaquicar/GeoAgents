from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


class BaseTool:
    """
    Tool mínima (MVP):
    - name: identificador único tipo 'utils.ping'
    - description: texto
    - input_schema: JSON schema-like (muy simple) para validar presence/type básico
    """

    name: str = ""
    description: str = ""
    input_schema: Dict[str, Any] = {}  # ejemplo: {"type":"object","properties":{...},"required":[...]}

    def validate(self, args: Dict[str, Any]) -> Optional[str]:
        """
        Validación básica y barata (MVP).
        Más adelante: Pydantic/JSONSchema completo.
        """
        schema = self.input_schema or {}
        required = schema.get("required", [])
        props = schema.get("properties", {})

        if not isinstance(args, dict):
            return "args must be an object"

        for k in required:
            if k not in args:
                return f"missing required field: {k}"

        # type checking mínimo
        for k, spec in props.items():
            if k not in args:
                continue
            t = spec.get("type")
            if not t:
                continue
            v = args[k]
            if t == "string" and not isinstance(v, str):
                return f"field '{k}' must be string"
            if t == "number" and not isinstance(v, (int, float)):
                return f"field '{k}' must be number"
            if t == "integer" and not isinstance(v, int):
                return f"field '{k}' must be integer"
            if t == "boolean" and not isinstance(v, bool):
                return f"field '{k}' must be boolean"
            if t == "object" and not isinstance(v, dict):
                return f"field '{k}' must be object"
            if t == "array" and not isinstance(v, list):
                return f"field '{k}' must be array"

        return None

    def invoke(self, *, args: Dict[str, Any], run=None, user=None, **kwargs) -> ToolResult:
        """
        Implementa en subclases.
        """
        raise NotImplementedError