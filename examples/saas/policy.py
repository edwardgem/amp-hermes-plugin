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
    if not isinstance(args, dict):
        args = {}

    if tool_name == "terminal":
        command = str(args.get("command") or args.get("cmd") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="exec",
            action="exec",
            context={
                "command": command,
                "workdir": args.get("workdir") or "",
            },
        )

    if tool_name == "read_file":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="read",
            action="read",
            context={"path": path},
        )

    if tool_name == "search_files":
        path = str(args.get("path") or "").strip()
        pattern = str(args.get("pattern") or "").strip()
        target = str(args.get("target") or "content").strip() or "content"
        file_glob = str(args.get("file_glob") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="read",
            action="search",
            context={
                "path": path,
                "pattern": pattern,
                "query": pattern,
                "target": target,
                "file_glob": file_glob,
            },
        )

    if tool_name == "write_file":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="write",
            action="write",
            context={
                "path": path,
                "file_path": path,
            },
        )

    if tool_name == "patch":
        path = str(args.get("path") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="write",
            action="edit",
            context={
                "path": path,
                "file_path": path,
            },
        )

    if tool_name == "web_search":
        query = str(args.get("query") or "").strip()
        return NormalizedAction(
            raw_tool_name=tool_name,
            tool="exec",
            action="web_search",
            context={"query": query},
        )

    return None
