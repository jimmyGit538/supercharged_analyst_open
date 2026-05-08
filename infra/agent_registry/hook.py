"""
agent_registry/hook.py

Claude Code PostToolUse hook — triggered after Write or Edit tool calls.
Reads the hook payload from stdin, checks if the changed file is under .claude/
or is CLAUDE.md, and runs `manage sync` if so.

No bash required — invoke with plain `python infra/agent_registry/hook.py`.
"""

import json
import sys
from pathlib import Path

payload = json.loads(sys.stdin.read())

tool_input = payload.get("tool_input", {})
file_path = Path(
    tool_input.get("file_path") or
    payload.get("tool_response", {}).get("filePath", "")
)

project_root = Path(__file__).resolve().parent.parent.parent
is_claude_file = any(p.name == ".claude" for p in file_path.parents)
is_claude_md = file_path.name == "CLAUDE.md"

if not (is_claude_file or is_claude_md):
    sys.exit(0)

# Add infra/ to sys.path so agent_registry is importable
sys.path.insert(0, str(project_root / "infra"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from agent_registry.manage import cmd_sync
cmd_sync(None)
