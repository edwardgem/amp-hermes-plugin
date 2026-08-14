"""CLI commands for AMP governance plugin setup.

Handles: hermes amp connect
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Dict

from hermes_constants import get_env_path


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="amp_action")

    connect_p = subs.add_parser("connect", help="Connect this Hermes agent to AMP")
    connect_p.add_argument("--api-key", required=True, help="AMP API key")
    connect_p.add_argument("--org-id", required=True, help="AMP org id")
    connect_p.add_argument("--username", required=True, help="AMP account username")
    connect_p.add_argument("--agent-name", required=True, help="Name for this agent")
    connect_p.add_argument("--backend-url", default="http://localhost:3000", help="AMP backend URL")
    connect_p.add_argument("--hitl-timeout", type=int, default=10, help="HITL approval timeout in minutes")


def _write_env_file(env_path: Path, values: Dict[str, str]) -> None:
    """Merge AMP_* keys into .env, updating existing lines in place and
    preserving everything else (other plugins' config, comments, ordering) —
    this file is shared, not ours alone, unlike OpenClaw's dedicated
    amp_config.json."""
    lines = []
    seen = set()
    if env_path.exists():
        for raw_line in env_path.read_text().splitlines():
            stripped = raw_line.strip()
            key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                lines.append(raw_line)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n")


def amp_command(args: argparse.Namespace) -> int:
    """Doesn't (and structurally can't) cover plugin install — a plugin's own
    CLI command only exists once the plugin is already loaded, so
    `hermes plugins install ... --enable` stays a separate first step. Shells
    out to the real `hermes gateway restart` (stdout/stderr inherited)
    rather than reimplementing it, so behavior matches running it by hand."""
    action = getattr(args, "amp_action", None)
    if action != "connect":
        print("Usage: hermes amp connect --api-key ... --org-id ... --username ... --agent-name ...")
        return 2

    env_path = get_env_path()
    print(f"→ Writing config to {env_path}")
    try:
        _write_env_file(env_path, {
            "AMP_BACKEND_URL": args.backend_url,
            "AMP_API_KEY": args.api_key,
            "AMP_AGENT_NAME": args.agent_name,
            "AMP_USERNAME": args.username,
            "AMP_ORG_ID": args.org_id,
            "AMP_HITL_TIMEOUT_MINUTES": str(args.hitl_timeout),
        })
        print("✓ Config written.")
    except Exception as exc:
        print(f"✗ Failed to write config: {exc}")
        return 1

    print("→ Restarting Hermes gateway (hermes gateway restart)...")
    try:
        subprocess.run(["hermes", "gateway", "restart"], check=True)
    except Exception as exc:
        print(f"✗ Failed to restart gateway: {exc}")
        return 1

    print(f'✓ Connected — agent "{args.agent_name}" is now governed by AMP.')
    return 0
