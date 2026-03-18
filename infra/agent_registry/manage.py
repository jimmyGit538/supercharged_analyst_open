"""
agent_registry/manage.py

CLI for managing agents and skills in BigQuery.

Commands:
    upsert   -- create or update an agent/skill from a .md file (one-time migration)
    snapshot -- save a snapshot of the current live definition
    diff     -- show unified diff between last two snapshots
    list     -- list snapshot history for a name

Usage:
    python -m agent_registry.manage upsert   --type agent --name extraction-agent --file agent.md
    python -m agent_registry.manage snapshot --type agent --name extraction-agent --notes "v2 improved"
    python -m agent_registry.manage diff     --type agent --name extraction-agent
    python -m agent_registry.manage list     --type agent --name extraction-agent
"""

import argparse
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")

_BQ_PROJECT = os.getenv("BQ_PROJECT")
_BQ_DATASET = os.getenv("BQ_DATASET")


def _client():
    return bigquery.Client(project=_BQ_PROJECT)


def _table_for(type_: str) -> tuple[str, str]:
    """Return (live_table, snapshot_table) for agent or skill."""
    if type_ == "agent":
        return "agents", "agent_snapshots"
    elif type_ == "skill":
        return "skills", "skill_snapshots"
    else:
        raise ValueError(f"Unknown type '{type_}' — must be 'agent' or 'skill'")


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_upsert(args):
    """
    Create or update a definition in BigQuery from a file.
    Heading defaults to the first ## line found, or the name if not present.
    Also writes an initial snapshot.
    """
    live_table, _ = _table_for(args.type)
    content = Path(args.file).read_text(encoding="utf-8")

    # Extract heading from first ## line if present
    heading = args.name
    for line in content.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            break

    client = _client()

    # Check if it already exists to determine new version number
    check_sql = f"""
        SELECT version FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{live_table}`
        WHERE name = @name LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", args.name)]
    )
    existing = list(client.query(check_sql, job_config=job_config).result())
    new_version = (existing[0]["version"] + 1) if existing else 1

    # BigQuery has no native UPSERT via DML from the Python client for streaming,
    # so we use a MERGE statement.
    merge_sql = f"""
        MERGE `{_BQ_PROJECT}.{_BQ_DATASET}.{live_table}` T
        USING (SELECT @name AS name, @heading AS heading,
                      @content AS content, @version AS version) S
        ON T.name = S.name
        WHEN MATCHED THEN
            UPDATE SET
                heading    = S.heading,
                content    = S.content,
                version    = S.version,
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (name, heading, content, version, is_active, updated_at)
            VALUES (S.name, S.heading, S.content, S.version, TRUE, CURRENT_TIMESTAMP())
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("name",    "STRING", args.name),
            bigquery.ScalarQueryParameter("heading", "STRING", heading),
            bigquery.ScalarQueryParameter("content", "STRING", content),
            bigquery.ScalarQueryParameter("version", "INT64",  new_version),
        ]
    )
    client.query(merge_sql, job_config=job_config).result()
    print(f"[upsert] {args.type} '{args.name}' v{new_version} → {live_table}")

    # Auto-snapshot after every upsert
    from agent_registry.snapshot import snapshot_agent, snapshot_skill
    fn = snapshot_agent if args.type == "agent" else snapshot_skill
    fn(args.name, notes=args.notes or f"upserted from {args.file}")


def cmd_snapshot(args):
    from agent_registry.snapshot import snapshot_agent, snapshot_skill
    fn = snapshot_agent if args.type == "agent" else snapshot_skill
    fn(args.name, notes=args.notes or "", performance_tag=args.tag or "")


def cmd_diff(args):
    from agent_registry.snapshot import diff_agent, diff_skill
    fn = diff_agent if args.type == "agent" else diff_skill
    print(fn(args.name))


def cmd_list(args):
    from agent_registry.snapshot import list_snapshots
    _, snap_table = _table_for(args.type)
    rows = list_snapshots(args.name, table=snap_table, limit=args.limit)
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


# ── CLI entry ──────────────────────────────────────────────────────────────────

def main():
    if not _BQ_PROJECT or not _BQ_DATASET:
        print("ERROR: BQ_PROJECT and BQ_DATASET must be set in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Manage Claude agents and skills in BigQuery")
    sub = parser.add_subparsers(dest="command", required=True)

    # upsert
    p = sub.add_parser("upsert", help="Create or update a definition from a file")
    p.add_argument("--type",  required=True, choices=["agent", "skill"])
    p.add_argument("--name",  required=True)
    p.add_argument("--file",  required=True, help="Path to .md or .txt file")
    p.add_argument("--notes", default="")

    # snapshot
    p = sub.add_parser("snapshot", help="Save a snapshot of the current live definition")
    p.add_argument("--type",  required=True, choices=["agent", "skill"])
    p.add_argument("--name",  required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--tag",   default="", help="Performance tag for A/B comparison")

    # diff
    p = sub.add_parser("diff", help="Show diff between last two snapshots")
    p.add_argument("--type", required=True, choices=["agent", "skill"])
    p.add_argument("--name", required=True)

    # list
    p = sub.add_parser("list", help="List snapshot history")
    p.add_argument("--type",  required=True, choices=["agent", "skill"])
    p.add_argument("--name",  required=True)
    p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    {"upsert": cmd_upsert, "snapshot": cmd_snapshot,
     "diff": cmd_diff, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    main()
