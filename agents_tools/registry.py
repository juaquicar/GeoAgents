from __future__ import annotations
from typing import Dict, List, Type

from .base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError("Tool must have name")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]

    def list(self) -> List[BaseTool]:
        return sorted(self._tools.values(), key=lambda t: t.name)


REGISTRY = ToolRegistry()


def register_tool(cls: Type[BaseTool]) -> Type[BaseTool]:
    """
    Decorador para registrar tools al importarlas.
    """
    REGISTRY.register(cls())
    return cls