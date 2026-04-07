CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    transport_user_id TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS display_name TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_profile_id TEXT;

CREATE TABLE IF NOT EXISTS agent_profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_profiles_user_idx
    ON agent_profiles (user_id);

CREATE UNIQUE INDEX IF NOT EXISTS agent_profiles_user_slug_idx
    ON agent_profiles (user_id, lower(slug));

INSERT INTO agent_profiles (id, user_id, slug, name, status, meta, created_at, updated_at)
SELECT
    'profile-default:' || users.id,
    users.id,
    'default',
    'Default',
    'active',
    '{}'::jsonb,
    NOW(),
    NOW()
FROM users
WHERE NOT EXISTS (
    SELECT 1
    FROM agent_profiles
    WHERE agent_profiles.user_id = users.id
      AND lower(agent_profiles.slug) = 'default'
);

UPDATE users
SET default_profile_id = 'profile-default:' || users.id
WHERE (default_profile_id IS NULL OR default_profile_id = '')
  AND EXISTS (
    SELECT 1
    FROM agent_profiles
    WHERE agent_profiles.id = 'profile-default:' || users.id
  );

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT 'active',
    scope_type TEXT NOT NULL DEFAULT 'private',
    scope_id TEXT NOT NULL DEFAULT '',
    model TEXT
);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS model TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS origin TEXT;

UPDATE sessions
SET origin = 'discord'
WHERE origin IS NULL;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS scope_type TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS scope_id TEXT;

UPDATE sessions
SET scope_type = CASE
    WHEN status = 'heartbeat' THEN 'system'
    WHEN status = 'scheduled' THEN 'system'
    ELSE 'private'
END
WHERE scope_type IS NULL OR scope_type = '';

UPDATE sessions
SET agent_profile_id = COALESCE(agent_profile_id, users.default_profile_id)
FROM users
WHERE users.id = sessions.user_id
  AND (sessions.agent_profile_id IS NULL OR sessions.agent_profile_id = '');

UPDATE sessions
SET scope_id = CASE
    WHEN scope_type = 'private' THEN 'private:' || COALESCE(agent_profile_id, user_id)
    WHEN scope_type = 'system' THEN 'system:' || status || ':' || id
    ELSE 'legacy:' || id
END
WHERE scope_id IS NULL OR scope_id = '';

UPDATE sessions
SET scope_id = 'private:' || COALESCE(agent_profile_id, user_id)
WHERE scope_type = 'private'
  AND scope_id = 'private:' || user_id;

ALTER TABLE sessions
    ALTER COLUMN scope_type SET DEFAULT 'private';

ALTER TABLE sessions
    ALTER COLUMN scope_id SET DEFAULT '';

CREATE INDEX IF NOT EXISTS sessions_scope_status_created_idx
    ON sessions (scope_type, scope_id, status, created_at DESC);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS context_summary TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS context_summary_checkpoint TIMESTAMPTZ;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS context_summary_input_tokens INTEGER;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_status TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_checkpoint TIMESTAMPTZ;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_input_tokens INTEGER;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_message_id TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_last_error TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_path TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS session_memory_updated_at TIMESTAMPTZ;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_status TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_attempts INTEGER;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_next_retry_at TIMESTAMPTZ;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_last_error TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_path TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary_completed_at TIMESTAMPTZ;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS total_cost DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_input_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_output_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_total_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_cost DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_model TEXT;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_usage_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE llm_usage
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

CREATE TABLE IF NOT EXISTS tool_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    executor_id TEXT,
    run_id TEXT,
    message_id TEXT,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE tool_runs
    ADD COLUMN IF NOT EXISTS executor_id TEXT;

ALTER TABLE tool_runs
    ADD COLUMN IF NOT EXISTS run_id TEXT;

ALTER TABLE tool_runs
    ADD COLUMN IF NOT EXISTS message_id TEXT;

CREATE INDEX IF NOT EXISTS tool_runs_run_id_idx
    ON tool_runs (run_id);

CREATE INDEX IF NOT EXISTS tool_runs_executor_id_idx
    ON tool_runs (executor_id);

CREATE INDEX IF NOT EXISTS tool_runs_session_created_idx
    ON tool_runs (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_prompts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT,
    message_id TEXT,
    question TEXT NOT NULL,
    choices JSONB NOT NULL DEFAULT '[]'::jsonb,
    allow_free_text BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'pending',
    answer TEXT,
    answered_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS user_prompts_session_created_idx
    ON user_prompts (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS user_prompts_status_created_idx
    ON user_prompts (status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS user_prompts_session_pending_idx
    ON user_prompts (session_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS executors (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'docker',
    platform TEXT,
    hostname TEXT,
    status TEXT NOT NULL DEFAULT 'offline',
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS kind TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS platform TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS hostname TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE executors
    ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS executors_owner_created_idx
    ON executors (owner_user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS executors_owner_name_idx
    ON executors (owner_user_id, name);
CREATE INDEX IF NOT EXISTS executors_owner_kind_idx
    ON executors (owner_user_id, kind);

CREATE TABLE IF NOT EXISTS executor_tokens (
    id TEXT PRIMARY KEY,
    executor_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

ALTER TABLE executor_tokens
    ADD COLUMN IF NOT EXISTS executor_id TEXT;
ALTER TABLE executor_tokens
    ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE executor_tokens
    ADD COLUMN IF NOT EXISTS token_prefix TEXT;
ALTER TABLE executor_tokens
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE executor_tokens
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS executor_tokens_hash_idx
    ON executor_tokens (token_hash);
CREATE INDEX IF NOT EXISTS executor_tokens_executor_created_idx
    ON executor_tokens (executor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS run_traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    message_id TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'running',
    model TEXT,
    input_text TEXT NOT NULL DEFAULT '',
    output_text TEXT NOT NULL DEFAULT '',
    error TEXT,
    limit_reason TEXT,
    limit_detail TEXT,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_ms INTEGER
);

ALTER TABLE run_traces
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

CREATE INDEX IF NOT EXISTS run_traces_session_started_idx
    ON run_traces (session_id, started_at DESC);

CREATE INDEX IF NOT EXISTS run_traces_user_started_idx
    ON run_traces (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS run_traces_status_started_idx
    ON run_traces (status, started_at DESC);

CREATE TABLE IF NOT EXISTS run_trace_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS run_trace_events_run_created_idx
    ON run_trace_events (run_id, created_at ASC);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    embedding vector NOT NULL,
    summary TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE memory_entries
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

CREATE INDEX IF NOT EXISTS memory_entries_user_id_idx
    ON memory_entries (user_id);

DO $$
DECLARE
    embedding_typmod INTEGER;
BEGIN
    SELECT a.atttypmod
    INTO embedding_typmod
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = 'memory_entries'
      AND n.nspname = current_schema()
      AND a.attname = 'embedding'
      AND a.attnum > 0
      AND NOT a.attisdropped;

    -- pgvector ANN indexes require a fixed-dimension vector column.
    IF embedding_typmod IS NOT NULL AND embedding_typmod > 0 THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS memory_entries_embedding_cosine_idx
                 ON memory_entries USING ivfflat (embedding vector_cosine_ops)
                 WITH (lists = 100)';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS secrets (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    name TEXT NOT NULL,
    value_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

ALTER TABLE secrets
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'secrets_user_id_name_key'
    ) THEN
        ALTER TABLE secrets DROP CONSTRAINT secrets_user_id_name_key;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS secrets_user_profile_name_idx
    ON secrets (user_id, COALESCE(agent_profile_id, ''), name);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    device_name TEXT,
    device_type TEXT,
    created_via TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_tokens_token_hash_idx
    ON auth_tokens (token_hash);

CREATE UNIQUE INDEX IF NOT EXISTS auth_tokens_token_prefix_idx
    ON auth_tokens (token_prefix);

CREATE INDEX IF NOT EXISTS auth_tokens_user_id_idx
    ON auth_tokens (user_id);

CREATE TABLE IF NOT EXISTS pair_codes (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    user_id TEXT,
    flow_type TEXT NOT NULL DEFAULT 'pair',
    display_name TEXT,
    created_by_user_id TEXT,
    created_via TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS pair_codes_code_hash_idx
    ON pair_codes (code_hash);

CREATE INDEX IF NOT EXISTS pair_codes_flow_expires_idx
    ON pair_codes (flow_type, expires_at);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    transport_channel_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    guild_id TEXT,
    guild_name TEXT,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS surface_profile_overrides (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    surface_kind TEXT NOT NULL,
    surface_id TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS surface_profile_overrides_unique_idx
    ON surface_profile_overrides (user_id, origin, surface_kind, surface_id);

CREATE INDEX IF NOT EXISTS surface_profile_overrides_profile_idx
    ON surface_profile_overrides (agent_profile_id);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    channel_id TEXT NOT NULL,
    target_scope_type TEXT NOT NULL DEFAULT 'private',
    target_scope_id TEXT NOT NULL DEFAULT '',
    target_origin TEXT,
    target_destination_id TEXT,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '__main_chain__',
    schedule_type TEXT NOT NULL DEFAULT 'cron',
    schedule_expr TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ
);

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS target_scope_type TEXT;

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS target_scope_id TEXT;

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS target_origin TEXT;

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS target_destination_id TEXT;

ALTER TABLE scheduled_jobs
    ADD COLUMN IF NOT EXISTS model TEXT;

UPDATE scheduled_jobs
SET agent_profile_id = COALESCE(agent_profile_id, users.default_profile_id)
FROM users
WHERE users.id = scheduled_jobs.user_id
  AND (scheduled_jobs.agent_profile_id IS NULL OR scheduled_jobs.agent_profile_id = '');

UPDATE scheduled_jobs
SET target_scope_type = 'private'
WHERE target_scope_type IS NULL OR target_scope_type = '';

UPDATE scheduled_jobs
SET target_scope_id = 'private:' || COALESCE(agent_profile_id, user_id)
WHERE target_scope_id IS NULL OR target_scope_id = '';

UPDATE scheduled_jobs
SET target_scope_id = 'private:' || COALESCE(agent_profile_id, user_id)
WHERE target_scope_type = 'private'
  AND target_scope_id = 'private:' || user_id;

UPDATE scheduled_jobs
SET target_origin = COALESCE(target_origin, 'discord')
WHERE target_origin IS NULL;

UPDATE scheduled_jobs
SET target_destination_id = COALESCE(target_destination_id, channel_id)
WHERE target_destination_id IS NULL OR target_destination_id = '';

UPDATE scheduled_jobs
SET model = '__main_chain__'
WHERE model IS NULL OR model = '';

ALTER TABLE scheduled_jobs
    ALTER COLUMN target_scope_type SET DEFAULT 'private';

ALTER TABLE scheduled_jobs
    ALTER COLUMN target_scope_id SET DEFAULT '';

ALTER TABLE scheduled_jobs
    ALTER COLUMN model SET DEFAULT '__main_chain__';

CREATE INDEX IF NOT EXISTS scheduled_jobs_target_scope_idx
    ON scheduled_jobs (target_scope_type, target_scope_id);

CREATE TABLE IF NOT EXISTS scheduled_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error TEXT,
    output TEXT,
    attachments JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_profile_id TEXT,
    session_id TEXT,
    kind TEXT NOT NULL DEFAULT 'sub_agent',
    name TEXT NOT NULL DEFAULT 'Background job',
    status TEXT NOT NULL DEFAULT 'queued',
    model TEXT,
    target_scope_type TEXT NOT NULL DEFAULT 'private',
    target_scope_id TEXT NOT NULL DEFAULT '',
    target_origin TEXT,
    target_destination_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    tool_calls_used INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    delivery_error TEXT
);

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS agent_profile_id TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS session_id TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'sub_agent';

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT 'Background job';

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'queued';

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS model TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS target_scope_type TEXT NOT NULL DEFAULT 'private';

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS target_scope_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS target_origin TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS target_destination_id TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS limits JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS result JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS error TEXT;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS tool_calls_used INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS cost DOUBLE PRECISION NOT NULL DEFAULT 0;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;

ALTER TABLE agent_jobs
    ADD COLUMN IF NOT EXISTS delivery_error TEXT;

UPDATE agent_jobs
SET agent_profile_id = COALESCE(agent_profile_id, users.default_profile_id)
FROM users
WHERE users.id = agent_jobs.user_id
  AND (agent_jobs.agent_profile_id IS NULL OR agent_jobs.agent_profile_id = '');

UPDATE agent_jobs
SET target_scope_type = 'private'
WHERE target_scope_type IS NULL OR target_scope_type = '';

UPDATE agent_jobs
SET target_scope_id = 'private:' || COALESCE(agent_profile_id, user_id)
WHERE target_scope_id IS NULL OR target_scope_id = '';

UPDATE agent_jobs
SET target_scope_id = 'private:' || COALESCE(agent_profile_id, user_id)
WHERE target_scope_type = 'private'
  AND target_scope_id = 'private:' || user_id;

CREATE INDEX IF NOT EXISTS agent_jobs_user_created_idx
    ON agent_jobs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS agent_jobs_status_created_idx
    ON agent_jobs (status, created_at ASC);

CREATE INDEX IF NOT EXISTS sessions_agent_profile_idx
    ON sessions (agent_profile_id);

CREATE INDEX IF NOT EXISTS llm_usage_agent_profile_idx
    ON llm_usage (agent_profile_id);

CREATE INDEX IF NOT EXISTS run_traces_agent_profile_idx
    ON run_traces (agent_profile_id);

CREATE INDEX IF NOT EXISTS memory_entries_agent_profile_idx
    ON memory_entries (agent_profile_id);

CREATE INDEX IF NOT EXISTS secrets_agent_profile_idx
    ON secrets (agent_profile_id);

CREATE INDEX IF NOT EXISTS scheduled_jobs_agent_profile_idx
    ON scheduled_jobs (agent_profile_id);

CREATE INDEX IF NOT EXISTS agent_jobs_agent_profile_idx
    ON agent_jobs (agent_profile_id);

UPDATE llm_usage
SET agent_profile_id = COALESCE(llm_usage.agent_profile_id, sessions.agent_profile_id)
FROM sessions
WHERE sessions.id = llm_usage.session_id
  AND (llm_usage.agent_profile_id IS NULL OR llm_usage.agent_profile_id = '');

UPDATE run_traces
SET agent_profile_id = COALESCE(run_traces.agent_profile_id, sessions.agent_profile_id)
FROM sessions
WHERE sessions.id = run_traces.session_id
  AND (run_traces.agent_profile_id IS NULL OR run_traces.agent_profile_id = '');

UPDATE memory_entries
SET agent_profile_id = COALESCE(memory_entries.agent_profile_id, users.default_profile_id)
FROM users
WHERE users.id = memory_entries.user_id
  AND (memory_entries.agent_profile_id IS NULL OR memory_entries.agent_profile_id = '');

UPDATE secrets
SET agent_profile_id = NULL
WHERE agent_profile_id = '';
