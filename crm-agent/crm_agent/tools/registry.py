"""Step 5 - The tool-use framework.

A small, explicit registry that turns plain Python functions into Claude tools:

    registry = ToolRegistry()

    @registry.tool(
        description="Find accounts ...",
        properties={"industry": {"type": "string"}},
        required=[],
        mutating=False,
    )
    def search_accounts(ctx, industry=None): ...

What the framework handles so individual tools don't have to:

* **Schemas** - ``registry.schemas()`` renders the ``tools=[...]`` list for the
  Messages API, in a stable order (stable bytes keep the prompt cache warm).
* **Validation** - arguments are checked against the JSON schema (required fields,
  types, enums, unknown keys) before the handler runs; failures go back to Claude as
  ``is_error`` tool results it can recover from.
* **Write guard** - tools marked ``mutating=True`` go through an approval callback
  (CLI prompt, web-UI toggle, or auto-approve in tests) before they touch data.
* **Errors** - any exception becomes an error tool result instead of crashing the loop.
* **Serialization** - results (with datetimes, ObjectIds...) become compact JSON.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ToolInputError(ValueError):
    pass


def _json_default(o: Any):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=_json_default, ensure_ascii=False)


def validate(schema: dict, args: dict) -> None:
    if not isinstance(args, dict):
        raise ToolInputError("tool input must be a JSON object")
    props = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise ToolInputError(f"missing required field(s): {', '.join(missing)}")
    unknown = [k for k in args if k not in props]
    if unknown:
        raise ToolInputError(f"unknown field(s): {', '.join(unknown)}; allowed: {', '.join(props)}")
    for key, value in args.items():
        spec = props[key]
        if value is None:
            continue
        expected = _JSON_TYPES.get(spec.get("type"))
        if expected and (not isinstance(value, expected) or
                         (spec.get("type") in ("integer", "number") and isinstance(value, bool))):
            raise ToolInputError(f"field '{key}' must be of type {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolInputError(f"field '{key}' must be one of {spec['enum']}")
        if spec.get("type") == "array" and "items" in spec and "enum" in spec["items"]:
            bad = [v for v in value if v not in spec["items"]["enum"]]
            if bad:
                raise ToolInputError(f"field '{key}' has invalid values {bad}")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]
    mutating: bool = False

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolResult:
    tool_use_id: str
    name: str
    input: dict
    output: Any
    is_error: bool = False
    duration_ms: int = 0

    def to_block(self) -> dict:
        content = self.output if isinstance(self.output, str) else to_json(self.output)
        block = {"type": "tool_result", "tool_use_id": self.tool_use_id, "content": content}
        if self.is_error:
            block["is_error"] = True
        return block


# approve(tool_name, args) -> bool
Approver = Callable[[str, dict], bool]


@dataclass
class ToolContext:
    """Everything a tool handler may need. Passed as the first argument."""
    db: Any
    retriever: Any
    user: str = "CRM User"
    approve: Approver = field(default=lambda name, args: True)
    on_write: Callable[[], None] = field(default=lambda: None)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(self, *, description: str, properties: dict | None = None, required: list[str] | None = None,
             mutating: bool = False, name: str | None = None):
        def decorator(fn):
            tool_name = name or fn.__name__
            if tool_name in self._tools:
                raise ValueError(f"duplicate tool name {tool_name}")
            self._tools[tool_name] = Tool(
                name=tool_name,
                description=description.strip(),
                input_schema={"type": "object", "properties": properties or {}, "required": required or []},
                handler=fn,
                mutating=mutating,
            )
            return fn
        return decorator

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, ctx: ToolContext, tool_use_id: str, name: str, args: dict) -> ToolResult:
        start = time.perf_counter()

        def done(output, is_error=False):
            return ToolResult(tool_use_id, name, args, output, is_error,
                              int((time.perf_counter() - start) * 1000))

        tool = self._tools.get(name)
        if tool is None:
            return done(f"Error: unknown tool '{name}'.", True)
        try:
            validate(tool.input_schema, args)
        except ToolInputError as e:
            return done(f"Invalid input for {name}: {e}", True)
        if tool.mutating and not ctx.approve(name, args):
            return done(f"The user declined the write action '{name}'. Do not retry it; tell the user what you "
                        "would have changed so they can approve it or do it themselves.", True)
        try:
            output = tool.handler(ctx, **args)
        except LookupError as e:
            return done(f"Not found: {e}", True)
        except Exception as e:  # noqa: BLE001 - surfaced to the model as a recoverable error
            return done(f"Error while running {name}: {type(e).__name__}: {e}", True)
        if tool.mutating:
            ctx.on_write()
        return done(output)
