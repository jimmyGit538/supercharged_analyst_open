"""
agent_registry/parser.py

Parses a Claude agent or skill .md file into structured fields.

File format:
    ---
    name: my-agent
    description: >
      What this agent does.
    tools:
      - Read
      - Write
    skills:
      - python-data-extraction
    ---

    ## Section Heading

    Body text for that section...

    ## Another Section

    More body text...

Usage:
    from agent_registry.parser import parse_md

    parsed = parse_md(path.read_text())
    # parsed["description"]  -> str
    # parsed["tools"]        -> ["Read", "Write"]
    # parsed["sections"]     -> [{"heading": "## Section Heading", "body": "..."}, ...]
"""

import yaml


def parse_md(content: str) -> dict:
    """
    Parse a markdown file with optional YAML frontmatter.

    Returns a dict with:
        name        (str | None)       — from frontmatter
        description (str | None)       — from frontmatter
        tools       (list[str])        — from frontmatter, agents only (else [])
        skills      (list[str])        — from frontmatter, agents only (else [])
        sections    (list[dict])       — [{"heading": str, "body": str}, ...]
    """
    frontmatter, body = _split_frontmatter(content)
    fm = _parse_frontmatter(frontmatter)
    sections = _parse_sections(body)

    return {
        "name":        fm.get("name"),
        "description": _normalise_str(fm.get("description")),
        "tools":       _as_str_list(fm.get("tools")),
        "skills":      _as_str_list(fm.get("skills")),
        "sections":    sections,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _split_frontmatter(content: str) -> tuple[str, str]:
    """
    Split content into (frontmatter_text, body_text).
    If the file doesn't start with '---', frontmatter is empty.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", content

    # Find the closing ---
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            frontmatter = "".join(lines[1:i])
            body = "".join(lines[i + 1:])
            return frontmatter, body

    # No closing --- found — treat whole file as body
    return "", content


def _parse_frontmatter(text: str) -> dict:
    if not text.strip():
        return {}
    try:
        result = yaml.safe_load(text)
        return result if isinstance(result, dict) else {}
    except yaml.YAMLError:
        return {}


def _parse_sections(body: str) -> list[dict]:
    """
    Split the markdown body into sections on any heading line (starts with #).
    Returns [{"heading": "## Foo", "body": "..."}, ...].
    Content before the first heading is collected under a blank heading.
    """
    sections: list[dict] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in body.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            # Save previous section if it has any content
            body_text = "".join(current_lines).strip()
            if current_heading or body_text:
                sections.append({"heading": current_heading, "body": body_text})
            current_heading = line.rstrip()
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last section
    body_text = "".join(current_lines).strip()
    if current_heading or body_text:
        sections.append({"heading": current_heading, "body": body_text})

    return sections


def _normalise_str(value) -> str | None:
    """Convert YAML scalar to a clean string, or None if absent."""
    if value is None:
        return None
    return " ".join(str(value).split())  # collapse whitespace from YAML block scalars


def _as_str_list(value) -> list[str]:
    """Convert a YAML sequence to a list of strings, defaulting to []."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
