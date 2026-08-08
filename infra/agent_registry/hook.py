"""
agent_registry/hook.py

Claude Code PostToolUse hook — triggered after Write or Edit tool calls.
Reads the hook payload from stdin and:

  - if the edited file is an agent or skill definition (.claude/agents/<name>.md
    or .claude/skills/<name>/SKILL.md), snapshots THAT ONE definition to
    BigQuery;
  - if the edited file is structural (Terraform, workflows, extractors, dbt
    models), reminds Claude to check CLAUDE.md's Directory Structure section.

Set AGENT_REGISTRY_HOOK_DISABLED=1 to stop the hook writing snapshots at all —
useful while testing or making bulk edits. Catch up afterwards with
`python -m agent_registry.manage sync` from infra/.

Design rules for this file:

  1. It NEVER exits non-zero and never raises. A PostToolUse hook that fails
     turns into a blocking error on a tool call that already succeeded, which
     is far worse than a missed registry snapshot. Every failure path is
     swallowed and reported as a note.
  2. It NEVER depends on the shell's working directory. The project root is
     derived from __file__, so the hook works regardless of where the tool call
     left the cwd. Configure it in settings.json with an absolute path:
     `python "$CLAUDE_PROJECT_DIR/infra/agent_registry/hook.py"`.
  3. It is a no-op when the registry is not configured (no BQ_PROJECT, missing
     dependencies). A fresh fork should not see hook noise before its first
     `terraform apply`.
"""

import contextlib
import fnmatch
import io
import json
import os
import sys
from pathlib import Path

STRUCTURAL_PATTERNS = [
    "infra/terraform/*.tf",
    "infra/terraform/terraform.tfvars",
    "infra/workflows/*.yaml",
    "infra/workflows/*.yml",
    "01_extraction/*/main.py",
    "01_extraction/*/Dockerfile",
    "02_dbt/models/**/*.sql",
    "infra/agent_registry/*",
    ".github/workflows/*.yml",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def emit(payload: dict) -> None:
    """Write a hook JSON response to stdout."""
    print(json.dumps(payload))


def note(message: str) -> None:
    """Surface a non-fatal problem without failing the tool call."""
    emit({"systemMessage": f"[agent-registry hook] {message}", "suppressOutput": True})


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 — a hook must never fail its own tool call
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def resolve_edited_path(payload: dict) -> Path | None:
    raw_path = (
        payload.get("tool_input", {}).get("file_path")
        or payload.get("tool_response", {}).get("filePath")
        or ""
    )
    if not raw_path:
        return None
    try:
        return Path(raw_path).resolve()
    except (OSError, ValueError):
        return None


def relative_to_project(file_path: Path) -> str | None:
    """Repo-relative POSIX path, or None if the file is outside the project."""
    try:
        return file_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def classify_definition(file_path: Path) -> tuple[str, str] | None:
    """Map an edited .claude/ file to ("agent"|"skill", name), or None.

    Only these two shapes are registry definitions:
        .claude/agents/<name>.md
        .claude/skills/<name>/SKILL.md
    Anything else under .claude/ (settings.json, worktrees, scratch files) is
    not a definition and must not trigger a snapshot.
    """
    rel = relative_to_project(file_path)
    if rel is None:
        return None

    parts = rel.split("/")
    if len(parts) == 4 and parts[:2] == [".claude", "skills"] and parts[3] == "SKILL.md":
        return "skill", parts[2]
    if len(parts) == 3 and parts[:2] == [".claude", "agents"] and parts[2].endswith(".md"):
        return "agent", parts[2][: -len(".md")]
    return None


def sync_registry(kind: str, name: str) -> None:
    """Snapshot ONE definition to BigQuery. Never raises.

    Deliberately not `manage sync`: that loads every agent and skill, issuing a
    get_last_snapshot query per definition — 14 BigQuery queries for a one-file
    edit. The hook already knows which file changed, so it snapshots only that.
    """
    # infra/ on sys.path so `agent_registry` resolves as a package — the same
    # requirement deploy.sh satisfies by cd'ing to infra/ before running
    # `python -m agent_registry.manage`.
    sys.path.insert(0, str(PROJECT_ROOT / "infra"))

    try:
        from dotenv import load_dotenv
    except ImportError:
        # Registry deps not installed — nothing to sync, and that is fine.
        return

    load_dotenv(PROJECT_ROOT / ".env")

    if not os.getenv("BQ_PROJECT"):
        # Registry not configured yet (fresh fork). Stay silent.
        return

    # The loader prints a line per definition. Capture it — hook stdout is the
    # JSON response channel, and raw chatter there is noise, not signal.
    captured = io.StringIO()
    try:
        from agent_registry.loader import load_agent, load_skill

        load = load_agent if kind == "agent" else load_skill
        with contextlib.redirect_stdout(captured):
            load(name)
    except ImportError as exc:
        note(f"could not import agent_registry ({exc}). Skipped snapshot.")
    except Exception as exc:  # noqa: BLE001 — auth, network and BigQuery errors
        note(f"snapshot skipped for {kind} '{name}': {type(exc).__name__}: {exc}")
    else:
        # loader prints "[registry] '<name>' changed — snapshot vN written ..."
        # only when a new version was actually recorded. Silence means unchanged.
        written = next(
            (
                line
                for line in captured.getvalue().splitlines()
                if line.startswith("[registry]")
            ),
            None,
        )
        if written:
            emit({"systemMessage": written, "suppressOutput": True})


def main() -> None:
    payload = read_payload()
    file_path = resolve_edited_path(payload)
    if file_path is None:
        return

    definition = classify_definition(file_path)
    if definition is not None:
        if os.getenv("AGENT_REGISTRY_HOOK_DISABLED"):
            # Escape hatch for tests, experiments and bulk edits — set this to
            # stop the hook writing snapshots, then run
            # `python -m agent_registry.manage sync` from infra/ when ready.
            return
        sync_registry(*definition)
        return

    rel_posix = relative_to_project(file_path)
    if rel_posix is None:
        return

    if any(fnmatch.fnmatch(rel_posix, p) for p in STRUCTURAL_PATTERNS):
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"You modified a structural file: {rel_posix}. "
                        "CLAUDE.md's Directory Structure section may need updating — "
                        "run `python scripts/validate_claude_md.py` to check. "
                        "CI runs this same script and fails the lint job on drift."
                    ),
                }
            }
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — last line of defence, see module docstring
        note(f"unexpected error, ignored: {type(exc).__name__}: {exc}")
    sys.exit(0)
