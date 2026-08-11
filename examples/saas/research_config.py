from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

MIN_TOPICS = 1
MAX_TOPICS = 5

_DEFAULTS = {
    "research_depth": "standard",
    "sources_per_topic": 5,
    "lookback_days": 7,
}


def load_research_topics(path: str) -> Dict[str, Any]:
    """Load and validate a research_topics.yaml file (Phase 3B research skill).

    Requires 1-5 non-empty topics. Applies defaults for research_depth,
    sources_per_topic, and lookback_days when omitted. Raises ValueError
    with a specific message for every invalid input — callers (the
    amp_load_research_topics tool) turn that into a tool-error response
    rather than crashing the session.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"Research topics file not found: {p}")

    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"Research topics file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Research topics file must contain a YAML mapping (topics/research_depth/...).")

    topics = raw.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ValueError("Research topics file must have a non-empty 'topics' list.")

    topics = [str(t).strip() for t in topics if str(t).strip()]
    if not topics:
        raise ValueError("Research topics file must have a non-empty 'topics' list.")
    if len(topics) < MIN_TOPICS:
        raise ValueError(f"At least {MIN_TOPICS} topic is required.")
    if len(topics) > MAX_TOPICS:
        raise ValueError(f"At most {MAX_TOPICS} topics are supported (got {len(topics)}).")

    return {
        "topics": topics,
        "research_depth": str(raw.get("research_depth") or _DEFAULTS["research_depth"]),
        "sources_per_topic": int(raw.get("sources_per_topic") or _DEFAULTS["sources_per_topic"]),
        "lookback_days": int(raw.get("lookback_days") or _DEFAULTS["lookback_days"]),
    }
