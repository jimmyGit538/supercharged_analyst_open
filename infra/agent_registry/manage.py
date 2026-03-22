"""
agent_registry/manage.py

CLI for managing agent and skill snapshots in BigQuery.

Commands:
    sync     -- scan all .claude/agents/ and .claude/skills/ files and snapshot any that changed
    diff     -- show unified diff between last two snapshots for a given name
    list     -- list snapshot history for a given name
    upsert   -- snapshot a single agent or skill from an explicit file path

Usage:
    python -m agent_registry.manage sync
    python -m agent_registry.manage diff   --type agent --name data-extractor
    python -m agent_registry.manage list   --type agent --name data-extractor
    python -m agent_registry.manage list   --type skill --name python-data-extraction --limit 10
    python -m agent_registry.manage upsert --type agent --name data-extractor --file .claude/agents/data-extractor.md --notes "initial seed"
"""

import argparse
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")

_BQ_PROJECT = os.getenv("BQ_PROJECT")
_BQ_DATASET = os.getenv("BQ_DATASET")

# Project root: infra/agent_registry/ -> infra/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CLAUDE_DIR = _PROJECT_ROOT / ".claude"


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_sync(args):
    """
    Scan all .claude/agents/*.md and .claude/skills/*/SKILL.md files.
    For each, load it via the registry (which auto-snapshots if content changed).
    """
    from agent_registry.loader import load_agent, load_skill

    agents_dir = _CLAUDE_DIR / "agents"
    skills_dir = _CLAUDE_DIR / "skills"

    agent_files = sorted(agents_dir.glob("*.md")) if agents_dir.exists() else []
    skill_files = sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []

    if not agent_files and not skill_files:
        print(f"No agent or skill files found under {_CLAUDE_DIR}")
        return

    for path in agent_files:
        name = path.stem
        try:
            load_agent(name)
        except Exception as e:
            print(f"[sync] ERROR loading agent '{name}': {e}", file=sys.stderr)

    for path in skill_files:
        name = path.parent.name
        try:
            load_skill(name)
        except Exception as e:
            print(f"[sync] ERROR loading skill '{name}': {e}", file=sys.stderr)

    print(f"[sync] Done — {len(agent_files)} agent(s), {len(skill_files)} skill(s) checked.")


def cmd_diff(args):
    from agent_registry.snapshot import diff
    table = "agent_snapshots" if args.type == "agent" else "skill_snapshots"
    print(diff(name=args.name, table=table))


def cmd_list(args):
    from agent_registry.snapshot import list_snapshots
    table = "agent_snapshots" if args.type == "agent" else "skill_snapshots"
    rows = list_snapshots(name=args.name, table=table, limit=args.limit)
    if not rows:
        print(f"No snapshots found for {args.type} '{args.name}'")
        return
    print(f"\nSnapshots for {args.type} '{args.name}':")
    print(f"{'version':<10} {'snapshotted_at':<32} {'tag':<20} notes")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['version']:<10} "
            f"{str(r['snapshotted_at']):<32} "
            f"{(r['performance_tag'] or ''):<20} "
            f"{r['notes'] or ''}"
        )


def cmd_upsert(args):
    """
    Snapshot a single agent or skill from an explicit file path.
    Writes a new snapshot only if the file content has changed since the last snapshot.
    """
    from agent_registry.parser import parse_md
    from agent_registry.snapshot import get_last_snapshot, write_snapshot

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    table = "agent_snapshots" if args.type == "agent" else "skill_snapshots"
    is_agent = args.type == "agent"
    content = file_path.read_text(encoding="utf-8")

    last = get_last_snapshot(name=args.name, table=table)
    if last is not None and last["content"] == content:
        print(f"[upsert] '{args.name}' unchanged — no snapshot written")
        return

    parsed = parse_md(content)
    version = (last["version"] + 1) if last else 1
    write_snapshot(
        name=args.name,
        content=content,
        version=version,
        table=table,
        description=parsed.get("description") or "",
        tools=parsed["tools"] if is_agent else None,
        skills=parsed["skills"] if is_agent else None,
        sections=parsed["sections"],
        notes=args.notes,
    )
    print(f"[upsert] '{args.name}' snapshot v{version} written to {table}")


# ── CLI entry ──────────────────────────────────────────────────────────────────

def main():
    if not _BQ_PROJECT or not _BQ_DATASET:
        print("ERROR: BQ_PROJECT and BQ_DATASET must be set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Manage Claude agent and skill snapshots in BigQuery")
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    sub.add_parser("sync", help="Snapshot any agents or skills whose files have changed")

    # diff
    p = sub.add_parser("diff", help="Show diff between last two snapshots")
    p.add_argument("--type", required=True, choices=["agent", "skill"])
    p.add_argument("--name", required=True)

    # list
    p = sub.add_parser("list", help="List snapshot history")
    p.add_argument("--type",  required=True, choices=["agent", "skill"])
    p.add_argument("--name",  required=True)
    p.add_argument("--limit", type=int, default=20)

    # upsert
    p = sub.add_parser("upsert", help="Snapshot a single agent or skill from an explicit file path")
    p.add_argument("--type",  required=True, choices=["agent", "skill"])
    p.add_argument("--name",  required=True)
    p.add_argument("--file",  required=True, help="Path to the .md file")
    p.add_argument("--notes", default=None, help="Optional notes for this snapshot")

    args = parser.parse_args()
    {"sync": cmd_sync, "diff": cmd_diff, "list": cmd_list, "upsert": cmd_upsert}[args.command](args)


if __name__ == "__main__":
    main()
