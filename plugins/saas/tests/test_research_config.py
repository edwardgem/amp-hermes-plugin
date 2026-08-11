"""Tests for research_config.load_research_topics (Phase 3B config validation)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from hermes.research_config import load_research_topics


def _write(tmp: str, content: str) -> str:
    path = Path(tmp) / "research_topics.yaml"
    path.write_text(content)
    return str(path)


class LoadResearchTopicsTests(unittest.TestCase):
    def test_valid_file_with_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, """
topics:
  - AI agent governance
  - Progressive autonomy
research_depth: deep
sources_per_topic: 3
lookback_days: 14
""")
            result = load_research_topics(path)
        self.assertEqual(result["topics"], ["AI agent governance", "Progressive autonomy"])
        self.assertEqual(result["research_depth"], "deep")
        self.assertEqual(result["sources_per_topic"], 3)
        self.assertEqual(result["lookback_days"], 14)

    def test_defaults_applied_when_optional_fields_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "topics:\n  - AI agent governance\n")
            result = load_research_topics(path)
        self.assertEqual(result["research_depth"], "standard")
        self.assertEqual(result["sources_per_topic"], 5)
        self.assertEqual(result["lookback_days"], 7)

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                load_research_topics(str(Path(tmp) / "does_not_exist.yaml"))
        self.assertIn("not found", str(ctx.exception).lower())

    def test_empty_topics_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "topics: []\n")
            with self.assertRaises(ValueError) as ctx:
                load_research_topics(path)
        self.assertIn("topics", str(ctx.exception).lower())

    def test_missing_topics_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "research_depth: standard\n")
            with self.assertRaises(ValueError):
                load_research_topics(path)

    def test_too_many_topics_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            topics = "\n".join(f"  - Topic {i}" for i in range(6))
            path = _write(tmp, f"topics:\n{topics}\n")
            with self.assertRaises(ValueError) as ctx:
                load_research_topics(path)
        self.assertIn("5", str(ctx.exception))

    def test_five_topics_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            topics = "\n".join(f"  - Topic {i}" for i in range(5))
            path = _write(tmp, f"topics:\n{topics}\n")
            result = load_research_topics(path)
        self.assertEqual(len(result["topics"]), 5)

    def test_malformed_yaml_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "topics: [unclosed\n  - broken: : :\n")
            with self.assertRaises(ValueError) as ctx:
                load_research_topics(path)
        self.assertIn("yaml", str(ctx.exception).lower())

    def test_non_mapping_yaml_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "- just\n- a\n- list\n")
            with self.assertRaises(ValueError):
                load_research_topics(path)

    def test_blank_topic_entries_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "topics:\n  - AI agent governance\n  - \"  \"\n  - Progressive autonomy\n")
            result = load_research_topics(path)
        self.assertEqual(result["topics"], ["AI agent governance", "Progressive autonomy"])


if __name__ == "__main__":
    unittest.main()
