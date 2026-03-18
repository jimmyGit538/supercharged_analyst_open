"""
agent_registry/snapshot.py

Writes a snapshot row to agent_snapshots (or skill_snapshots) whenever
content changes. Call snapshot_agent() / snapshot_skill() from:

  - A deployment script after you've edited a row in BigQuery
  - A scheduled job (e.g. daily) to capture periodic state
  - Manually from a notebook when you want to tag a version

Usage:
    from agent_registry.snapshot import snapshot_agent, snapshot_skill, diff_agent

    # Save a snapshot with an optional note
    snapshot_agent("extraction-agent", notes="improved pagination instructions")

    # Compare current content to the last snapshot
    diff = diff_agent("extraction-agent")
    print(diff)
"""

import os
import difflib
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

logger = logging.getLogger(__name__)

_BQ_PROJECT = os.getenv("BQ_PROJECT")
_BQ_DATASET = os.getenv("BQ_DATASET")

if not _BQ_PROJECT:
    raise EnvironmentError("BQ_PROJECT is not set in .env")
if not _BQ_DATASET:
    raise EnvironmentError("BQ_DATASET is not set in .env")


def _client() -> bigquery.Client:
    return bigquery.Client(project=_BQ_PROJECT)


# ── Snapshot writers ───────────────────────────────────────────────────────────

def snapshot_agent(name: str, notes: str = "", performance_tag: str = "") -> None:
    """Snapshot the current live content of the named agent."""
    _write_snapshot(source_table="agents", snapshot_table="agent_snapshots",
                    name=name, notes=notes, performance_tag=performance_tag)


def snapshot_skill(name: str, notes: str = "", performance_tag: str = "") -> None:
    """Snapshot the current live content of the named skill."""
    _write_snapshot(source_table="skills", snapshot_table="skill_snapshots",
                    name=name, notes=notes, performance_tag=performance_tag)


def _write_snapshot(source_table: str, snapshot_table: str,
                    name: str, notes: str, performance_tag: str) -> None:
    client = _client()

    # Fetch current live definition
    sql = f"""
        SELECT name, heading, content, version
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{source_table}`
        WHERE name = @name AND is_active = TRUE
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
    )
    rows = list(client.query(sql, job_config=job_config).result())

    if not rows:
        raise ValueError(f"No active row found in '{source_table}' for name='{name}'")

    row = rows[0]
    now = datetime.now(timezone.utc).isoformat()

    snapshot_row = {
        "name":            row["name"],
        "heading":         row["heading"],
        "content":         row["content"],
        "version":         row["version"],
        "snapshotted_at":  now,
        "notes":           notes or None,
        "performance_tag": performance_tag or None,
    }

    table_ref = f"{_BQ_PROJECT}.{_BQ_DATASET}.{snapshot_table}"
    errors = client.insert_rows_json(table_ref, [snapshot_row])

    if errors:
        raise RuntimeError(f"BigQuery insert errors for snapshot: {errors}")

    logger.info(
        "[snapshot] Saved snapshot for %s '%s' v%d → %s",
        source_table.rstrip("s"), name, row["version"], snapshot_table
    )
    print(f"[snapshot] {source_table.rstrip('s')} '{name}' v{row['version']} → {snapshot_table}")


# ── Diff helpers ───────────────────────────────────────────────────────────────

def diff_agent(name: str, n_context: int = 5) -> str:
    """
    Return a unified diff between the last two snapshots for the named agent.
    Returns an empty string if fewer than two snapshots exist.
    """
    return _diff(snapshot_table="agent_snapshots", name=name, n_context=n_context)


def diff_skill(name: str, n_context: int = 5) -> str:
    """Return a unified diff between the last two snapshots for the named skill."""
    return _diff(snapshot_table="skill_snapshots", name=name, n_context=n_context)


def _diff(snapshot_table: str, name: str, n_context: int) -> str:
    sql = f"""
        SELECT content, snapshotted_at, version
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{snapshot_table}`
        WHERE name = @name
        ORDER BY snapshotted_at DESC
        LIMIT 2
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
    )
    rows = list(_client().query(sql, job_config=job_config).result())

    if len(rows) < 2:
        return f"(fewer than 2 snapshots exist for '{name}' — nothing to diff)"

    newer, older = rows[0], rows[1]
    diff = difflib.unified_diff(
        older["content"].splitlines(keepends=True),
        newer["content"].splitlines(keepends=True),
        fromfile=f"v{older['version']} ({older['snapshotted_at']})",
        tofile=f"v{newer['version']} ({newer['snapshotted_at']})",
        n=n_context,
    )
    return "".join(diff) or "(no text changes between last two snapshots)"


# ── History lister ─────────────────────────────────────────────────────────────

def list_snapshots(name: str, table: str = "agent_snapshots", limit: int = 20) -> list[dict]:
    """
    Return the N most recent snapshots for a given name.
    Each dict has: version, snapshotted_at, notes, performance_tag.
    """
    sql = f"""
        SELECT version, snapshotted_at, notes, performance_tag
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{table}`
        WHERE name = @name
        ORDER BY snapshotted_at DESC
        LIMIT {limit}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
    )
    rows = list(_client().query(sql, job_config=job_config).result())
    return [dict(r) for r in rows]
