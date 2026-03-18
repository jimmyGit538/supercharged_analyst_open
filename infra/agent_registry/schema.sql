-- ── agents ────────────────────────────────────────────────────────────────────
-- Live definitions for Claude agents.
-- Edit the `content` field here to update an agent immediately.
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.agents` (
    name        STRING  NOT NULL,   -- unique identifier, e.g. "extraction-agent"
    heading     STRING  NOT NULL,   -- human-readable title shown in docs
    content     STRING  NOT NULL,   -- full system prompt / instructions
    version     INT64   NOT NULL DEFAULT 1,
    is_active   BOOL    NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_by  STRING                                          -- optional: who changed it
)
OPTIONS (description = "Live Claude agent definitions. Single source of truth.");


-- ── skills ────────────────────────────────────────────────────────────────────
-- Live definitions for Claude skills (reusable sub-instructions).
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.skills` (
    name        STRING  NOT NULL,
    heading     STRING  NOT NULL,
    content     STRING  NOT NULL,
    version     INT64   NOT NULL DEFAULT 1,
    is_active   BOOL    NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_by  STRING
)
OPTIONS (description = "Live Claude skill definitions. Single source of truth.");


-- ── agent_snapshots ───────────────────────────────────────────────────────────
-- Append-only history of every content change to agents.
-- Never UPDATE or DELETE rows here — only INSERT.
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.agent_snapshots` (
    name            STRING    NOT NULL,
    heading         STRING    NOT NULL,
    content         STRING    NOT NULL,
    version         INT64     NOT NULL,
    snapshotted_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    notes           STRING,             -- optional: "improved pagination instructions"
    performance_tag STRING              -- optional: tag for A/B comparison
)
OPTIONS (description = "Append-only history of agent content changes for versioning and A/B analysis.");


-- ── skill_snapshots ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.skill_snapshots` (
    name            STRING    NOT NULL,
    heading         STRING    NOT NULL,
    content         STRING    NOT NULL,
    version         INT64     NOT NULL,
    snapshotted_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    notes           STRING,
    performance_tag STRING
)
OPTIONS (description = "Append-only history of skill content changes.");
