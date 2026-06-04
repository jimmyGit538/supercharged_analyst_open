#!/usr/bin/env python3
"""
Validates that CLAUDE.md's Directory Structure section matches the actual repo state.

Checks:
  A. Every .tf file listed in CLAUDE.md exists at infra/terraform/
  B. Every .tf file in infra/terraform/ is listed in CLAUDE.md
  C. Every extraction source (01_extraction/<name>/main.py) is mentioned in CLAUDE.md
  D. Every .yaml file in infra/workflows/ is listed in CLAUDE.md, and vice versa

Exit 0 if all checks pass, exit 1 if any fail.
"""

import fnmatch
import re
import sys
from pathlib import Path


RUNTIME_IGNORES = {
    "terraform.tfstate",
    "terraform.tfstate.backup",
    ".terraform",
    "tfplan",
}

DIR_BLOCK_RE = re.compile(
    r"## Directory Structure\s*\n```[^\n]*\n(.*?)```",
    re.DOTALL,
)
TF_TOKEN_RE = re.compile(r"^\s+(\w[\w\-.]+\.tf)\b", re.MULTILINE)
YAML_TOKEN_RE = re.compile(r"^\s+(\w[\w\-.]+\.ya?ml)\b", re.MULTILINE)
EXTRACTION_SOURCE_RE = re.compile(r"01_extraction/(\w[\w\-]*)/")


def extract_workflows_yaml_tokens(dir_block: str) -> set:
    """Return YAML filenames only from the infra/workflows/ subsection of the dir block."""
    tokens = set()
    in_workflows = False
    for line in dir_block.splitlines():
        # Enter the workflows/ subsection (exactly 2-space indent)
        if re.match(r"^  workflows/", line):
            in_workflows = True
            continue
        if in_workflows:
            # Children of workflows/ have 4+ spaces; anything shallower ends the section
            if re.match(r"^\s{4,}\S", line):
                m = YAML_TOKEN_RE.match(line)
                if m:
                    tokens.add(m.group(1))
            else:
                in_workflows = False
    return tokens


def find_repo_root() -> Path:
    for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (p / "CLAUDE.md").exists():
            return p
    raise FileNotFoundError("Could not find CLAUDE.md searching upward from script location")


def load_ignore_patterns(repo_root: Path) -> list:
    ignore_file = repo_root / "scripts" / ".claude_md_ignore"
    if not ignore_file.exists():
        return []
    return [
        line.strip()
        for line in ignore_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def is_ignored(name: str, patterns: list) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def extract_dir_block(claude_md_text: str) -> str:
    m = DIR_BLOCK_RE.search(claude_md_text)
    if not m:
        raise ValueError("Could not find '## Directory Structure' fenced block in CLAUDE.md")
    return m.group(1)


def main() -> int:
    repo_root = find_repo_root()
    claude_md = (repo_root / "CLAUDE.md").read_text(encoding="utf-8")
    dir_block = extract_dir_block(claude_md)
    ignore_patterns = load_ignore_patterns(repo_root)

    failures = 0

    # --- Check A: listed .tf files must exist on disk ---
    listed_tf = set(TF_TOKEN_RE.findall(dir_block))
    missing_tf = sorted(
        tf for tf in listed_tf
        if not (repo_root / "infra" / "terraform" / tf).exists()
    )
    if missing_tf:
        print("[FAIL] Listed .tf files missing from disk:")
        for f in missing_tf:
            print(f"       - infra/terraform/{f}  (listed in CLAUDE.md but not found on disk)")
        failures += 1
    else:
        print(f"[PASS] All {len(listed_tf)} .tf files listed in CLAUDE.md exist on disk")

    # --- Check B: .tf files on disk must be listed in CLAUDE.md ---
    tf_dir = repo_root / "infra" / "terraform"
    disk_tf = {
        p.name for p in tf_dir.glob("*.tf")
        if p.name not in RUNTIME_IGNORES and not is_ignored(p.name, ignore_patterns)
    }
    undocumented_tf = sorted(disk_tf - listed_tf)
    if undocumented_tf:
        print("[FAIL] Undocumented .tf files (on disk but not listed in CLAUDE.md):")
        for f in undocumented_tf:
            print(f"       + infra/terraform/{f}  (add to CLAUDE.md Directory Structure)")
        failures += 1
    else:
        print(f"[PASS] All {len(disk_tf)} .tf files in infra/terraform/ are documented in CLAUDE.md")

    # --- Check C: extraction sources must be mentioned in CLAUDE.md ---
    extraction_dir = repo_root / "01_extraction"
    real_sources = (
        [d.name for d in extraction_dir.iterdir() if d.is_dir() and (d / "main.py").exists()]
        if extraction_dir.exists()
        else []
    )
    documented_sources = set(EXTRACTION_SOURCE_RE.findall(claude_md))
    undocumented_sources = sorted(
        s for s in real_sources
        if s not in documented_sources and not is_ignored(s, ignore_patterns)
    )
    if undocumented_sources:
        print("[FAIL] Undocumented extraction sources:")
        for s in undocumented_sources:
            print(f"       + 01_extraction/{s}/  (add to CLAUDE.md Directory Structure)")
        failures += 1
    else:
        print(f"[PASS] Extraction sources: {len(real_sources)} source(s), all documented")

    # --- Check D: workflow YAMLs — bidirectional check ---
    listed_yaml = extract_workflows_yaml_tokens(dir_block)
    workflows_dir = repo_root / "infra" / "workflows"
    disk_yaml = {
        p.name
        for p in list(workflows_dir.glob("*.yaml")) + list(workflows_dir.glob("*.yml"))
        if not is_ignored(p.name, ignore_patterns)
    }
    missing_yaml = sorted(listed_yaml - disk_yaml)
    undocumented_yaml = sorted(disk_yaml - listed_yaml)

    if missing_yaml:
        print("[FAIL] Listed workflow YAMLs missing from disk:")
        for f in missing_yaml:
            print(f"       - infra/workflows/{f}  (listed in CLAUDE.md but not found on disk)")
        failures += 1
    else:
        print(f"[PASS] All workflow YAML files listed in CLAUDE.md exist on disk")

    if undocumented_yaml:
        print("[FAIL] Undocumented workflow YAMLs (on disk but not listed in CLAUDE.md):")
        for f in undocumented_yaml:
            print(f"       + infra/workflows/{f}  (add to CLAUDE.md Directory Structure)")
        failures += 1
    else:
        print(f"[PASS] All {len(disk_yaml)} workflow YAML(s) in infra/workflows/ are documented")

    print()
    if failures:
        print(f"CLAUDE.md is STALE — {failures} check(s) failed.")
        print("Update CLAUDE.md to reflect the above paths, then re-run this script.")
        return 1

    print("CLAUDE.md is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
