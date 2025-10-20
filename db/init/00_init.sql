-- Base bootstrap for PostgreSQL on first init
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Minimal audit table (optional use by triggers)
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  table_name VARCHAR(64),
  operation VARCHAR(16),
  record_id UUID,
  user_id VARCHAR(64),
  created_at TIMESTAMPTZ DEFAULT now(),
  detail JSONB
);

