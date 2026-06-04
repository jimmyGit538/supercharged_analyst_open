"""
agent_registry/hook.py

Claude Code PostToolUse hook — triggered after Write or Edit tool calls.
Reads the hook payload from stdin, checks if the changed file is under .claude/
or is CLAUDE.md, and runs `manage sync` if so.

No bash required — invoke with plain `python infra/agent_registry/hook.py`.
"""

import fnmatch
import json
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

payload = json.loads(sys.stdin.read())

tool_input = payload.get("tool_input", {})
file_path = Path(
    tool_input.get("file_path") or
    payload.get("tool_response", {}).get("filePath", "")
)

project_root = Path(__file__).resolve().parent.parent.parent
is_claude_file = any(p.name == ".claude" for p in file_path.parents)
is_claude_md = file_path.name == "CLAUDE.md"

try:
    rel_posix = file_path.resolve().relative_to(project_root).as_posix()
    is_structural = any(fnmatch.fnmatch(rel_posix, p) for p in STRUCTURAL_PATTERNS)
except ValueError:
    is_structural = False

if is_structural and not (is_claude_file or is_claude_md):
    print(f"[CLAUDE.md] You modified a structural file: {rel_posix}")
    print("[CLAUDE.md] Check whether CLAUDE.md's Directory Structure section needs updating.")
    print("[CLAUDE.md] Run: python scripts/validate_claude_md.py  to see what's missing.")
    sys.exit(0)

if not (is_claude_file or is_claude_md):
    sys.exit(0)

# Add infra/ to sys.path so agent_registry is importable
sys.path.insert(0, str(project_root / "infra"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from agent_registry.manage import cmd_sync
cmd_sync(None)
