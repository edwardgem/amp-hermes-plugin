from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from policy import normalize_tool_call


class NormalizeToolCallTests(unittest.TestCase):
    def test_terminal_maps_to_exec(self) -> None:
        action = normalize_tool_call("terminal", {"command": "rm -rf /tmp/x"})
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.tool, "exec")
        self.assertEqual(action.action, "exec")
        self.assertEqual(action.context["command"], "rm -rf /tmp/x")

    def test_read_file_maps_to_read(self) -> None:
        action = normalize_tool_call("read_file", {"path": "/tmp/a.txt"})
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.tool, "read")
        self.assertEqual(action.context["path"], "/tmp/a.txt")

    def test_search_files_maps_to_read_search(self) -> None:
        action = normalize_tool_call(
            "search_files",
            {"pattern": "*policy*", "target": "files", "path": "/tmp/agents"},
        )
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.tool, "read")
        self.assertEqual(action.action, "search")
        self.assertEqual(action.context["pattern"], "*policy*")
        self.assertEqual(action.context["query"], "*policy*")
        self.assertEqual(action.context["target"], "files")
        self.assertEqual(action.context["path"], "/tmp/agents")

    def test_patch_maps_to_write_edit(self) -> None:
        action = normalize_tool_call("patch", {"path": "/tmp/b.txt"})
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.tool, "write")
        self.assertEqual(action.action, "edit")
        self.assertEqual(action.context["file_path"], "/tmp/b.txt")

    def test_unsupported_tool_is_ignored(self) -> None:
        self.assertIsNone(normalize_tool_call("browser_navigate", {"url": "https://example.com"}))


if __name__ == "__main__":
    unittest.main()
