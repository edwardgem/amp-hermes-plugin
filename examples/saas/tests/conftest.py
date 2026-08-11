"""Makes ``from hermes import ...`` work in the test suite regardless of what
this checkout's directory is actually named on disk.

The tests import this plugin's own code as ``hermes`` by convention (not to
be confused with the Hermes agent framework itself, which installs as
``hermes_cli`` -- no naming collision). That convention only worked by
accident on a checkout whose directory happens to be named ``hermes``
(e.g. via ``~/.hermes/plugins/amp-governance`` symlinked to a dev checkout
at .../hermes); a plain ``git clone`` of this repo lands in a directory
named ``amp-hermes-plugin``, where the bare import fails. Registering the
package under ``sys.modules["hermes"]`` here, before test collection,
makes the import work either way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

if "hermes" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "hermes",
        _PLUGIN_ROOT / "__init__.py",
        submodule_search_locations=[str(_PLUGIN_ROOT)],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["hermes"] = _mod
    _spec.loader.exec_module(_mod)
