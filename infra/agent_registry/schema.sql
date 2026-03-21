-- ── agent_snapshots ───────────────────────────────────────────────────────────
-- Append-only history of every content change to agents.
-- Source of truth is .claude/agents/<name>.md — edit there, not here.
-- Never UPDATE or DELETE rows — only INSERT.
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.agent_snapshots` (
    name            STRING    NOT NULL,  -- filename stem, e.g. "data-extractor"
    description     STRING,             -- from frontmatter: what this agent does
    tools           ARRAY<STRING>,      -- from frontmatter: allowed tools
    skills          ARRAY<STRING>,      -- from frontmatter: composed skills
    sections        ARRAY<STRUCT<      -- parsed markdown sections
                        heading STRING, -- e.g. "## Instructions"
                        body    STRING  -- section body text
                    >>,
    content         STRING    NOT NULL, -- full raw file content (used for diffing)
    version         INT64     NOT NULL,
    snapshotted_at  TIMESTAMP NOT NULL,
    notes           STRING,             -- optional: "improved pagination logic"
    performance_tag STRING              -- optional: tag for A/B comparison
)
OPTIONS (description = "Append-only history of agent content changes. Source of truth is .claude/agents/<name>.md.");


-- ── skill_snapshots ───────────────────────────────────────────────────────────
-- Append-only history of every content change to skills.
-- Source of truth is .claude/skills/<name>/SKILL.md — edit there, not here.
-- Never UPDATE or DELETE rows — only INSERT.
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.skill_snapshots` (
    name            STRING    NOT NULL,  -- directory name, e.g. "python-data-extraction"
    description     STRING,             -- from frontmatter: when to invoke this skill
    sections        ARRAY<STRUCT<      -- parsed markdown sections
                        heading STRING,
                        body    STRING
                    >>,
    content         STRING    NOT NULL, -- full raw file content (used for diffing)
    version         INT64     NOT NULL,
    snapshotted_at  TIMESTAMP NOT NULL,
    notes           STRING,
    performance_tag STRING
)
OPTIONS (description = "Append-only history of skill content changes. Source of truth is .claude/skills/<name>/SKILL.md.");
