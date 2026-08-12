from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
ROOT_PARENT = ROOT.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from hermes import AmpGovernancePlugin


_BASE_ENV = {
    "AMP_BACKEND_URL": "https://amp.example.com/",
    "AMP_API_KEY": "amp_k_test",
    "AMP_ORG_ID": "O-0001-EXAMPLE",
    "AMP_USERNAME": "tester@example.com",
    "AMP_AGENT_NAME": "hermes-agent-old",
}


class SessionReinitOnConfigChangeTests(unittest.TestCase):
    """A long-running Hermes session (same session_id) must not keep reusing
    a cached instance_id once the plugin has been reconfigured to point at a
    different AMP agent -- otherwise AMP never sees a fresh init_instance()
    call for the new agent (breaks "Agent connected" tracking), and every
    subsequent governed call keeps logging under the old agent's identity."""

    def _make_plugin(self, hermes_home: Path, env_overrides: dict) -> AmpGovernancePlugin:
        env = {"HERMES_HOME": str(hermes_home), **_BASE_ENV, **env_overrides}
        with mock.patch.dict(os.environ, env, clear=False):
            return AmpGovernancePlugin()

    def test_reuses_cached_instance_when_config_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            plugin = self._make_plugin(hermes_home, {})
            plugin._client.init_instance = Mock(return_value="inst-1")
            plugin._client.log = Mock()

            first = plugin._ensure_instance("sess-1", model="m", platform="slack")
            second = plugin._ensure_instance("sess-1", model="m", platform="slack")

            self.assertEqual(first, "inst-1")
            self.assertEqual(second, "inst-1")
            plugin._client.init_instance.assert_called_once()

    def test_reinitializes_when_agent_changes_under_the_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)

            plugin = self._make_plugin(hermes_home, {"AMP_AGENT_NAME": "hermes-agent-old"})
            plugin._client.init_instance = Mock(return_value="inst-old")
            plugin._client.log = Mock()
            first = plugin._ensure_instance("sess-1", model="m", platform="slack")
            self.assertEqual(first, "inst-old")

            # Simulate re-pointing this same Hermes session at a different
            # AMP agent (e.g. QSJ Connect step re-run with new credentials),
            # without a fresh session_id (persistent Slack thread).
            plugin._config = self._make_plugin(hermes_home, {"AMP_AGENT_NAME": "hermes-agent-new"})._config
            plugin._client.init_instance = Mock(return_value="inst-new")

            second = plugin._ensure_instance("sess-1", model="m", platform="slack")

            self.assertEqual(second, "inst-new")
            plugin._client.init_instance.assert_called_once()

    def test_reuses_cache_again_once_new_config_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp)
            plugin = self._make_plugin(hermes_home, {"AMP_AGENT_NAME": "hermes-agent-old"})
            plugin._client.init_instance = Mock(return_value="inst-old")
            plugin._client.log = Mock()
            plugin._ensure_instance("sess-1", model="m", platform="slack")

            plugin._config = self._make_plugin(hermes_home, {"AMP_AGENT_NAME": "hermes-agent-new"})._config
            plugin._client.init_instance = Mock(return_value="inst-new")
            plugin._ensure_instance("sess-1", model="m", platform="slack")

            # Same (new) config again -- should now hit the freshly-written cache.
            plugin._client.init_instance = Mock(return_value="inst-new-should-not-be-called")
            third = plugin._ensure_instance("sess-1", model="m", platform="slack")

            self.assertEqual(third, "inst-new")
            plugin._client.init_instance.assert_not_called()


if __name__ == "__main__":
    unittest.main()
