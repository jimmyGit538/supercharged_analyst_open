"""
agent_registry/snapshot.py

Low-level BigQuery helpers for writing and reading snapshots.
Content is passed in directly — this module does not read from any live table.

Called automatically by loader.py whenever a file change is detected.
Can also be called manually for diff/list operations.
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


def _client() -> bigquery.Client:
    return bigquery.Client(project=_BQ_PROJECT)


# ── Snapshot writer ────────────────────────────────────────────────────────────

def write_snapshot(
    name: str,
    content: str,
    version: int,
    table: str,
    description: str = "",
    tools: list[str] | None = None,
    skills: list[str] | None = None,
    sections: list[dict] | None = None,
    notes: str = "",
    performance_tag: str = "",
) -> None:
    """Insert a snapshot row into the given snapshot table."""
    row = {
        "name":            name,
        "description":     description or None,
        "content":         content,
        "sections":        sections or [],
        "version":         version,
        "snapshotted_at":  datetime.now(timezone.utc).isoformat(),
        "notes":           notes or None,
        "performance_tag": performance_tag or None,
    }
    # tools and skills are agent-only — omit entirely for skill_snapshots
    if tools is not None:
        row["tools"] = tools
    if skills is not None:
        row["skills"] = skills
    table_ref = f"{_BQ_PROJECT}.{_BQ_DATASET}.{table}"
    errors = _client().insert_rows_json(table_ref, [row])
    if errors:
        raise RuntimeError(f"BigQuery insert errors for snapshot: {errors}")
    logger.info("[snapshot] v%d of '%s' -> %s", version, name, table)


# ── Last snapshot reader ───────────────────────────────────────────────────────

def get_last_snapshot(name: str, table: str) -> dict | None:
    """
    Return the most recent snapshot for the given name, or None if none exist.
    Dict contains: version, content, snapshotted_at.
    """
    if not _BQ_PROJECT or not _BQ_DATASET:
        return None
    sql = f"""
        SELECT version, content, snapshotted_at
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{table}`
        WHERE name = @name
        ORDER BY snapshotted_at DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
    )
    rows = list(_client().query(sql, job_config=job_config).result())
    return dict(rows[0]) if rows else None


# ── Diff helpers ───────────────────────────────────────────────────────────────

def diff(name: str, table: str, n_context: int = 5) -> str:
    """Return a unified diff between the last two snapshots. Empty string if < 2 exist."""
    sql = f"""
        SELECT content, snapshotted_at, version
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{table}`
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
    result = difflib.unified_diff(
        older["content"].splitlines(keepends=True),
        newer["content"].splitlines(keepends=True),
        fromfile=f"v{older['version']} ({older['snapshotted_at']})",
        tofile=f"v{newer['version']} ({newer['snapshotted_at']})",
        n=n_context,
    )
    return "".join(result) or "(no text changes between last two snapshots)"


# ── History lister ─────────────────────────────────────────────────────────────

def list_snapshots(name: str, table: str, limit: int = 20) -> list[dict]:
    """Return the N most recent snapshots for a given name."""
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
