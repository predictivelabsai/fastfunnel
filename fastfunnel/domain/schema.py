"""Versioned SQLite schema for the operational marketing backend."""

SCHEMA_VERSION = 2

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration_connections (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(company_id, provider)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    connection_id TEXT NOT NULL REFERENCES integration_connections(id),
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    rows_written INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    cursor_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_sync_runs_company_provider
    ON sync_runs(company_id, provider, started_at DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    daily_budget REAL,
    currency TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(company_id, provider, external_id)
);

CREATE TABLE IF NOT EXISTS marketing_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    account_id TEXT NOT NULL,
    campaign_external_id TEXT NOT NULL,
    fact_date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT '',
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    source_updated_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(
        company_id, provider, account_id, campaign_external_id,
        fact_date, metric, dimensions_json
    )
);
CREATE INDEX IF NOT EXISTS ix_marketing_facts_company_date
    ON marketing_facts(company_id, fact_date);
CREATE INDEX IF NOT EXISTS ix_marketing_facts_metric
    ON marketing_facts(company_id, metric);

CREATE TABLE IF NOT EXISTS journey_entities (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    occurred_on TEXT NOT NULL,
    source TEXT NOT NULL,
    campaign_external_id TEXT,
    reached_stage INTEGER NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_journey_entities_cohort
    ON journey_entities(company_id, occurred_on, source, reached_stage);

CREATE TABLE IF NOT EXISTS funnel_definitions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    observation_window_days INTEGER NOT NULL DEFAULT 30,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, slug)
);

CREATE TABLE IF NOT EXISTS funnel_stages (
    id TEXT PRIMARY KEY,
    funnel_id TEXT NOT NULL REFERENCES funnel_definitions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    dropoff_name TEXT NOT NULL,
    predicate_json TEXT NOT NULL,
    UNIQUE(funnel_id, position)
);

CREATE TABLE IF NOT EXISTS job_queue (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    job_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    available_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    locked_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(company_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_job_queue_due
    ON job_queue(status, available_at);
"""
