"""
agent_registry/loader.py

Loads agent and skill definitions from BigQuery at runtime.
This replaces all .md file reads — BigQuery is the single source of truth.

Usage:
    from agent_registry.loader import load_agent, load_skill

    system_prompt = load_agent("extraction-agent")
    skill_text    = load_skill("python-data-extraction")
"""

import os
import logging
from functools import lru_cache
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


# ── Core loaders ───────────────────────────────────────────────────────────────

def load_agent(name: str) -> str:
    """
    Return the content (system prompt) for the named agent.
    Raises ValueError if the agent is not found or inactive.
    """
    return _load_definition(table="agents", name=name)


def load_skill(name: str) -> str:
    """
    Return the content for the named skill.
    Raises ValueError if the skill is not found or inactive.
    """
    return _load_definition(table="skills", name=name)


def _load_definition(table: str, name: str) -> str:
    sql = f"""
        SELECT content
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{table}`
        WHERE name = @name
          AND is_active = TRUE
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
    )
    rows = list(_client().query(sql, job_config=job_config).result())

    if not rows:
        raise ValueError(
            f"No active definition found in '{table}' for name='{name}'. "
            f"Check that the row exists and is_active=TRUE in BigQuery."
        )

    logger.info("[loader] Loaded %s '%s' from BigQuery", table.rstrip("s"), name)
    return rows[0]["content"]


# ── Cached loader (optional, for high-frequency agents) ───────────────────────

@lru_cache(maxsize=64)
def load_agent_cached(name: str) -> str:
    """
    Same as load_agent() but caches the result in-process for the lifetime
    of the Python interpreter. Useful when the same agent is called many
    times per second and you don't need real-time updates.

    To clear the cache manually:
        load_agent_cached.cache_clear()
    """
    return load_agent(name)


# ── Batch loader (load all active definitions at startup) ─────────────────────

def load_all_agents() -> dict[str, str]:
    """Return {name: content} for all active agents."""
    return _load_all("agents")


def load_all_skills() -> dict[str, str]:
    """Return {name: content} for all active skills."""
    return _load_all("skills")


def _load_all(table: str) -> dict[str, str]:
    sql = f"""
        SELECT name, content
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{table}`
        WHERE is_active = TRUE
        ORDER BY name
    """
    rows = list(_client().query(sql).result())
    result = {r["name"]: r["content"] for r in rows}
    logger.info("[loader] Loaded %d active %s from BigQuery", len(result), table)
    return result
