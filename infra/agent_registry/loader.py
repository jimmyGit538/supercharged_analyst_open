"""
agent_registry/loader.py

Loads agent and skill definitions from .claude/ in the project root.
On each load, compares the current file content to the last BigQuery snapshot
and automatically writes a new snapshot if the content has changed.

File locations:
    Agents: <project_root>/.claude/agents/<name>.md
    Skills: <project_root>/.claude/skills/<name>/SKILL.md

Usage:
    from agent_registry.loader import load_agent, load_skill

    system_prompt = load_agent("data-extractor")
    skill_text    = load_skill("python-data-extraction")
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Project root is three levels up from this file:
# infra/agent_registry/loader.py -> infra/agent_registry/ -> infra/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CLAUDE_DIR = _PROJECT_ROOT / ".claude"

_BQ_ENABLED = bool(os.getenv("BQ_PROJECT") and os.getenv("BQ_DATASET"))
if not _BQ_ENABLED:
    logger.warning(
        "[loader] BQ_PROJECT or BQ_DATASET not set — snapshots will be skipped."
    )


# ── Public loaders ─────────────────────────────────────────────────────────────

def load_agent(name: str) -> str:
    """
    Read the agent definition from .claude/agents/<name>.md.
    Auto-snapshots to BigQuery if the content has changed since the last snapshot.
    """
    path = _CLAUDE_DIR / "agents" / f"{name}.md"
    return _load(name=name, path=path, table="agent_snapshots")


def load_skill(name: str) -> str:
    """
    Read the skill definition from .claude/skills/<name>/SKILL.md.
    Auto-snapshots to BigQuery if the content has changed since the last snapshot.
    """
    path = _CLAUDE_DIR / "skills" / name / "SKILL.md"
    return _load(name=name, path=path, table="skill_snapshots")


# ── Internal ───────────────────────────────────────────────────────────────────

def _load(name: str, path: Path, table: str) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Definition file not found: {path}\n"
            f"Expected at: .claude/agents/<name>.md or .claude/skills/<name>/SKILL.md"
        )

    content = path.read_text(encoding="utf-8")
    logger.info("[loader] Loaded '%s' from %s", name, path.relative_to(_PROJECT_ROOT))

    if _BQ_ENABLED:
        _auto_snapshot(name=name, content=content, table=table)

    return content


def _auto_snapshot(name: str, content: str, table: str) -> None:
    """Write a new snapshot if content differs from the last recorded snapshot."""
    from agent_registry.parser import parse_md
    from agent_registry.snapshot import get_last_snapshot, write_snapshot

    last = get_last_snapshot(name=name, table=table)

    if last is not None and last["content"] == content:
        logger.debug("[loader] '%s' unchanged — no snapshot written", name)
        return

    parsed = parse_md(content)
    version = (last["version"] + 1) if last else 1
    is_agent = table == "agent_snapshots"

    write_snapshot(
        name=name,
        content=content,
        version=version,
        table=table,
        description=parsed.get("description") or "",
        tools=parsed["tools"] if is_agent else None,
        skills=parsed["skills"] if is_agent else None,
        sections=parsed["sections"],
    )
    logger.info("[loader] Auto-snapshotted '%s' as v%d", name, version)
    print(f"[registry] '{name}' changed — snapshot v{version} written to {table}")
