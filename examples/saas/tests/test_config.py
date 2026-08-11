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
    def test_reads_env_file_and_agent_name_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            (hermes_home / ".env").write_text(
                "\n".join(
                    [
                        "AMP_BACKEND_URL=https://amp.example.com/",
                        "AMP_API_KEY=Bearer amp_k_test",
                        "AMP_ORG_ID=O-0001-EXAMPLE",
                        "AMP_USERNAME=tester@example.com",
                        "AGENT_NAME=hermes-agent-dev",
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


if __name__ == "__main__":
    unittest.main()

