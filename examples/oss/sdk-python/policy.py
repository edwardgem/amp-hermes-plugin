from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class NormalizedAction:
    raw_tool_name: str
    tool: str
    action: str
    context: Dict[str, Any]


def normalize_tool_call(tool_name: str, args: Any) -> Optional[NormalizedAction]:
    """Trimmed to four representative Hermes tools — a scaled-down version
    of amp-governance's own policy.py, enough to demonstrate exec/read/write
    governance end-to-end without porting the full tool-mapping table."""
    if not isinstance(args, dict):
        args = {}

    if tool_name == "terminal":
        command = str(args.get("command") or args.get("cmd") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name, tool="exec", action="exec",
            context={"command": command, "workdir": args.get("workdir") or ""},
        )

    if tool_name == "read_file":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name, tool="read", action="read",
            context={"path": path},
        )

    if tool_name == "write_file":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name, tool="write", action="write",
            context={"path": path, "file_path": path},
        )

    if tool_name == "patch":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name, tool="write", action="edit",
            context={"path": path, "file_path": path},
        )

    return None
