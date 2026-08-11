from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config


class LoadConfigTests(unittest.TestCase):
    def test_reads_env_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "\n".join(
                    [
                        "AMP_BACKEND_URL=https://amp.example.com/",
                        "AMP_API_KEY=Bearer amp_k_test",
                        "AMP_ORG_ID=O-0001-EXAMPLE",
                        "AMP_USERNAME=tester@example.com",
                        "AMP_AGENT_NAME=hermes-agent-dev",
                        "AMP_HITL_TIMEOUT_MINUTES=15",
                        "AMP_HITL_POLL_INTERVAL_SECONDS=5",
                        "AMP_FAIL_CLOSED=false",
                    ]
                )
                + "\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()

        self.assertEqual(cfg.backend_url, "https://amp.example.com")
        self.assertEqual(cfg.api_key, "amp_k_test")
        self.assertEqual(cfg.org_id, "O-0001-EXAMPLE")
        self.assertEqual(cfg.username, "tester@example.com")
        self.assertEqual(cfg.agent_name, "hermes-agent-dev")
        self.assertEqual(cfg.hitl_timeout_minutes, 15)
        self.assertEqual(cfg.hitl_poll_interval_seconds, 5)
        self.assertFalse(cfg.fail_closed)

    def test_new_config_defaults_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "\n".join(
                    [
                        "AMP_BACKEND_URL=https://amp.example.com",
                        "AMP_API_KEY=amp_k_test",
                        "AMP_ORG_ID=O-0001",
                        "AMP_USERNAME=tester@example.com",
                        "AMP_AGENT_NAME=hermes-test",
                    ]
                )
                + "\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()

        # Notification bridge: enabled by default
        self.assertTrue(cfg.notifications_enabled)
        # LLM governance: enabled by default (observe mode) so the research
        # skill's cost tracking works out of the box in this reference repo
        self.assertTrue(cfg.llm_governance_enabled)
        self.assertEqual(cfg.llm_governance_mode, "observe")
        self.assertFalse(cfg.llm_governance_fail_closed)
        self.assertTrue(cfg.llm_governance_include_subagents)

    def test_new_config_reads_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "\n".join(
                    [
                        "AMP_BACKEND_URL=https://amp.example.com",
                        "AMP_API_KEY=amp_k_test",
                        "AMP_ORG_ID=O-0001",
                        "AMP_USERNAME=tester@example.com",
                        "AMP_AGENT_NAME=hermes-test",
                        "AMP_NOTIFICATIONS_ENABLED=false",
                        "AMP_LLM_GOVERNANCE_ENABLED=true",
                        "AMP_LLM_GOVERNANCE_MODE=enforce",
                        "AMP_LLM_GOVERNANCE_FAIL_CLOSED=true",
                        "AMP_LLM_GOVERNANCE_INCLUDE_SUBAGENTS=false",
                    ]
                )
                + "\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()

        self.assertFalse(cfg.notifications_enabled)
        self.assertTrue(cfg.llm_governance_enabled)
        self.assertEqual(cfg.llm_governance_mode, "enforce")
        self.assertTrue(cfg.llm_governance_fail_closed)
        self.assertFalse(cfg.llm_governance_include_subagents)

    def test_invalid_llm_governance_mode_falls_back_to_observe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "\n".join(
                    [
                        "AMP_BACKEND_URL=https://amp.example.com",
                        "AMP_API_KEY=amp_k_test",
                        "AMP_ORG_ID=O-0001",
                        "AMP_USERNAME=tester@example.com",
                        "AMP_AGENT_NAME=hermes-test",
                        "AMP_LLM_GOVERNANCE_MODE=invalid-value",
                    ]
                )
                + "\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()

        self.assertEqual(cfg.llm_governance_mode, "observe")

    def test_notifications_enabled_true_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "AMP_BACKEND_URL=https://amp.example.com\n"
                "AMP_API_KEY=k\nAMP_ORG_ID=O\nAMP_USERNAME=u\nAMP_AGENT_NAME=a\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()
        self.assertTrue(cfg.notifications_enabled)

    def test_llm_governance_enabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "AMP_BACKEND_URL=https://amp.example.com\n"
                "AMP_API_KEY=k\nAMP_ORG_ID=O\nAMP_USERNAME=u\nAMP_AGENT_NAME=a\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()
        self.assertTrue(cfg.llm_governance_enabled)

    def test_llm_governance_can_be_explicitly_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "AMP_BACKEND_URL=https://amp.example.com\n"
                "AMP_API_KEY=k\nAMP_ORG_ID=O\nAMP_USERNAME=u\nAMP_AGENT_NAME=a\n"
                "AMP_LLM_GOVERNANCE_ENABLED=false\n"
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home)}, clear=False):
                cfg = load_config()
        self.assertFalse(cfg.llm_governance_enabled)


if __name__ == "__main__":
    unittest.main()
