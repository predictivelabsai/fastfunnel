"""Versioned SQLite schema for the operational marketing backend."""

SCHEMA_VERSION = 7

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_imports (
    import_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows_written INTEGER NOT NULL
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

CREATE TABLE IF NOT EXISTS workspace_settings (
    company_id TEXT PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    model_provider TEXT NOT NULL DEFAULT 'xai',
    model_name TEXT NOT NULL DEFAULT 'grok-4-1-fast-reasoning',
    model_temperature REAL NOT NULL DEFAULT 0.2,
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration_secrets (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    secret_name TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'validated',
    last_validated_at TEXT,
    validation_error TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, provider, secret_name)
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_api_tokens_company
    ON api_tokens(company_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS platform_accounts (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, provider, external_id)
);

CREATE TABLE IF NOT EXISTS data_sources (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    platform_account_id TEXT REFERENCES platform_accounts(id),
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    schedule_minutes INTEGER NOT NULL DEFAULT 1440,
    lookback_days INTEGER NOT NULL DEFAULT 30,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_data_sources_company
    ON data_sources(company_id, provider);

CREATE TABLE IF NOT EXISTS sync_cursors (
    data_source_id TEXT PRIMARY KEY REFERENCES data_sources(id) ON DELETE CASCADE,
    cursor_json TEXT NOT NULL DEFAULT '{}',
    watermark_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_extracts (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    data_source_id TEXT NOT NULL REFERENCES data_sources(id),
    sync_run_id TEXT REFERENCES sync_runs(id),
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    source_updated_at TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE(data_source_id, object_type, partition_key, payload_hash)
);
CREATE INDEX IF NOT EXISTS ix_raw_extracts_replay
    ON raw_extracts(company_id, provider, object_type, partition_key);

CREATE TABLE IF NOT EXISTS crm_entities (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL DEFAULT '',
    occurred_at TEXT,
    revenue_value REAL,
    currency TEXT NOT NULL DEFAULT '',
    properties_json TEXT NOT NULL DEFAULT '{}',
    source_updated_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(company_id, provider, entity_type, external_id)
);
CREATE INDEX IF NOT EXISTS ix_crm_entities_company_stage
    ON crm_entities(company_id, lifecycle_stage, occurred_at);

CREATE TABLE IF NOT EXISTS field_definitions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    slug TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL,
    aggregation TEXT NOT NULL,
    expression TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, slug, version)
);

CREATE TABLE IF NOT EXISTS transformation_rules (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    target_field TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    condition_json TEXT NOT NULL,
    value_expression TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    rate_date TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate REAL NOT NULL,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY(rate_date, base_currency, quote_currency)
);

CREATE TABLE IF NOT EXISTS saved_queries (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    name TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS destination_connections (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_runs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    destination_id TEXT NOT NULL REFERENCES destination_connections(id),
    saved_query_id TEXT REFERENCES saved_queries(id),
    status TEXT NOT NULL,
    rows_written INTEGER NOT NULL DEFAULT 0,
    receipt_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS skill_overlays (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    skill_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    instructions TEXT NOT NULL DEFAULT '',
    context_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, skill_id)
);

CREATE TABLE IF NOT EXISTS provider_identities (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    connected_account_id TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, user_id, provider)
);

CREATE TABLE IF NOT EXISTS action_requests (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    action_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    risk TEXT NOT NULL,
    status TEXT NOT NULL,
    approval_id TEXT REFERENCES approvals(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS action_executions (
    id TEXT PRIMARY KEY,
    action_request_id TEXT NOT NULL REFERENCES action_requests(id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    provider_receipt_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS kpi_definitions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    numerator_metric TEXT NOT NULL,
    denominator_metric TEXT,
    format TEXT NOT NULL DEFAULT 'number',
    target_value REAL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, slug)
);

CREATE TABLE IF NOT EXISTS agency_messages (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agency_messages_conversation
    ON agency_messages(company_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agency_runs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES users(id),
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agency_runs_company
    ON agency_runs(company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workspace_memberships (
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(company_id, user_id)
);

CREATE TABLE IF NOT EXISTS data_connections_v2 (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_checked_at TEXT,
    last_error TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, name)
);
CREATE INDEX IF NOT EXISTS ix_data_connections_v2_company_provider
    ON data_connections_v2(company_id, provider);

CREATE TABLE IF NOT EXISTS connection_secrets (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES data_connections_v2(id) ON DELETE CASCADE,
    secret_name TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    fingerprint TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    updated_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(connection_id, secret_name)
);

CREATE TABLE IF NOT EXISTS semantic_models (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    definition_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, model_key, version)
);

CREATE TABLE IF NOT EXISTS source_mappings (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    connection_id TEXT NOT NULL REFERENCES data_connections_v2(id) ON DELETE CASCADE,
    semantic_model_id TEXT NOT NULL REFERENCES semantic_models(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    definition_json TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(connection_id, name, version)
);

CREATE TABLE IF NOT EXISTS event_facts (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    semantic_model_id TEXT REFERENCES semantic_models(id),
    connection_id TEXT REFERENCES data_connections_v2(id),
    source TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    event_name TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    session_key TEXT,
    campaign_external_id TEXT,
    channel TEXT NOT NULL DEFAULT '',
    value REAL,
    currency TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    postal_area TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    ingested_at TEXT NOT NULL,
    UNIQUE(company_id, source, external_event_id)
);
CREATE INDEX IF NOT EXISTS ix_event_facts_funnel
    ON event_facts(company_id, event_name, occurred_at, subject_key);
CREATE INDEX IF NOT EXISTS ix_event_facts_geo
    ON event_facts(company_id, country_code, region, city, occurred_at);

CREATE TABLE IF NOT EXISTS metric_facts_v2 (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    semantic_model_id TEXT REFERENCES semantic_models(id),
    connection_id TEXT REFERENCES data_connections_v2(id),
    source TEXT NOT NULL,
    metric_date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT '',
    campaign_external_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    country_code TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    ingested_at TEXT NOT NULL,
    UNIQUE(
        company_id, source, metric_date, metric_name,
        campaign_external_id, channel, country_code, region, city, dimensions_json
    )
);
CREATE INDEX IF NOT EXISTS ix_metric_facts_v2_query
    ON metric_facts_v2(company_id, metric_name, metric_date);

CREATE TABLE IF NOT EXISTS dashboard_definitions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    semantic_model_id TEXT NOT NULL REFERENCES semantic_models(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(company_id, slug)
);
"""
