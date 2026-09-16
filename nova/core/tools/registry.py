"""The controlled tool layer.

Every capability Nova has is a registered tool with a JSON schema. The LLM can
only ask for tools by name with validated arguments -- it never gets a shell.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import get_logger

log = get_logger("tools")

JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


@dataclass
class ToolResult:
    ok: bool
    message: str                       # short sentence Nova can speak
    data: dict[str, Any] = field(default_factory=dict)
    needs_confirmation: bool = False
    confirmation: Any = None

    def to_llm(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "message": self.message}
        if self.data:
            out.update(self.data)
        return out

    @staticmethod
    def fail(message: str, **data: Any) -> ToolResult:
        return ToolResult(False, message, data)

    @staticmethod
    def success(message: str, **data: Any) -> ToolResult:
        return ToolResult(True, message, data)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]         # JSON-schema-ish: {"name": {"type":..., "required":...}}
    func: Callable[..., Any]
    category: str = "general"
    requires_llm: bool = False

    def schema(self) -> dict[str, Any]:
        props, required = {}, []
        for pname, spec in self.parameters.items():
            prop = {"type": spec.get("type", "string"), "description": spec.get("description", "")}
            if "enum" in spec:
                prop["enum"] = spec["enum"]
            if spec.get("type") == "array":
                prop["items"] = spec.get("items", {"type": "string"})
            props[pname] = prop
            if spec.get("required"):
                required.append(pname)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }


class ValidationError(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            log.debug("Replacing already-registered tool %s", tool.name)
        self._tools[tool.name] = tool

    def tool(self, name: str, description: str, parameters: dict | None = None, category: str = "general",
             requires_llm: bool = False) -> Callable:
        def deco(fn: Callable) -> Callable:
            self.register(Tool(name, description, parameters or {}, fn, category, requires_llm))
            return fn

        return deco

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self, only: list[str] | None = None) -> list[dict[str, Any]]:
        tools = [t for t in self._tools.values() if only is None or t.name in only]
        return [t.schema() for t in tools]

    # ---------- validation ----------
    def validate(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(name)
        if tool is None:
            raise ValidationError(f"There is no tool called '{name}'.")
        clean: dict[str, Any] = {}
        for pname, spec in tool.parameters.items():
            if pname not in args or args[pname] is None:
                if spec.get("required"):
                    raise ValidationError(f"'{name}' needs a value for '{pname}'.")
                if "default" in spec:
                    clean[pname] = spec["default"]
                continue
            value = args[pname]
            expected = JSON_TYPES.get(spec.get("type", "string"), str)
            # tolerate LLMs sending numbers as strings and vice-versa
            if not isinstance(value, expected):  # type: ignore[arg-type]
                try:
                    if spec.get("type") == "integer":
                        value = int(value)
                    elif spec.get("type") == "number":
                        value = float(value)
                    elif spec.get("type") == "boolean":
                        value = str(value).strip().lower() in {"true", "1", "yes"}
                    elif spec.get("type") == "string":
                        value = str(value)
                    elif spec.get("type") == "array" and isinstance(value, str):
                        value = [value]
                    else:
                        raise TypeError
                except (TypeError, ValueError) as e:
                    raise ValidationError(
                        f"'{pname}' for '{name}' should be a {spec.get('type')}, got {type(value).__name__}."
                    ) from e
            if "enum" in spec and value not in spec["enum"]:
                raise ValidationError(f"'{pname}' must be one of {spec['enum']}.")
            clean[pname] = value
        unknown = set(args) - set(tool.parameters)
        if unknown:
            log.debug("Ignoring unexpected arguments for %s: %s", name, sorted(unknown))
        return clean

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Validate then execute. Sync tools run directly; async tools are awaited."""
        try:
            clean = self.validate(name, args)
        except ValidationError as e:
            return ToolResult.fail(str(e))
        tool = self._tools[name]
        try:
            result = tool.func(**clean)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResult):
                return result
            return ToolResult.success(str(result))
        except Exception as e:  # tools must never crash the agent
            log.exception("Tool %s failed", name)
            return ToolResult.fail(f"{name} failed: {e}")


registry = ToolRegistry()
