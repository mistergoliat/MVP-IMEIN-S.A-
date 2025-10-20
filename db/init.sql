CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator','supervisor','admin')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products(
  item_code TEXT PRIMARY KEY,
  item_name TEXT NOT NULL,
  ABC TEXT, XYZ TEXT,
  unit_cost NUMERIC,
  monthly_mean NUMERIC, monthly_std NUMERIC, annual_qty NUMERIC,
  ACV NUMERIC, z_level NUMERIC, lead_time_days INT,
  SS INT, ROP INT, EOQ INT, SMIN INT, SMAX INT,
  OnHand INT, BelowROP BOOLEAN,
  uom TEXT NOT NULL DEFAULT 'UN',
  requires_lot BOOLEAN NOT NULL DEFAULT FALSE,
  requires_serial BOOLEAN NOT NULL DEFAULT FALSE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  item_code TEXT NOT NULL REFERENCES products(item_code),
  lot TEXT NULL,
  serial TEXT NULL,
  expiry DATE NULL,
  location TEXT NOT NULL DEFAULT 'MAIN',
  qty INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS moves(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type TEXT NOT NULL CHECK (type IN ('inbound','outbound','transfer','return')),
  doc_type TEXT NOT NULL CHECK (doc_type IN ('PO','SO','TR','RT')),
  doc_number TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','approved','pending','cancelled')) DEFAULT 'pending',
  created_by UUID NOT NULL REFERENCES users(id),
  approved_by UUID NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS move_lines(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  move_id UUID NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
  item_code TEXT NOT NULL REFERENCES products(item_code),
  lot TEXT NULL,
  serial TEXT NULL,
  expiry DATE NULL,
  qty INT NOT NULL,
  qty_confirmed INT NOT NULL DEFAULT 0,
  location_from TEXT NOT NULL DEFAULT 'MAIN',
  location_to TEXT NOT NULL DEFAULT 'MAIN'
);

CREATE TABLE IF NOT EXISTS audit(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  user_id UUID NULL REFERENCES users(id),
  ts TIMESTAMP NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'audit'
      AND column_name = 'payload_json'
      AND udt_name = 'text'
  ) THEN
    ALTER TABLE audit
      ALTER COLUMN payload_json TYPE JSONB
      USING payload_json::jsonb;
  END IF;
END
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users') THEN
    ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'stock') THEN
    ALTER TABLE stock ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'moves') THEN
    ALTER TABLE moves ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'move_lines') THEN
    ALTER TABLE move_lines ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'audit') THEN
    ALTER TABLE audit ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'print_jobs') THEN
    ALTER TABLE print_jobs ALTER COLUMN id SET DEFAULT gen_random_uuid();
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS print_jobs(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  printer_name TEXT NOT NULL,
  payload_zpl TEXT NOT NULL,
  copies INT NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK (status IN ('queued','sent','error','retry')) DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Helpful index for queue polling
CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status, created_at);

-- ABC–XYZ analytics results (periodic, denormalized)
CREATE TABLE IF NOT EXISTS abcxyz_results (
  period TEXT NOT NULL,
  item_code TEXT NOT NULL,
  abc CHAR(1) NOT NULL,
  xyz CHAR(1) NOT NULL,
  class TEXT NOT NULL,
  policy TEXT NOT NULL,
  stock NUMERIC NULL,
  turnover NUMERIC NULL,
  revenue NUMERIC NULL,
  min_qty NUMERIC NULL,
  max_qty NUMERIC NULL,
  item_name VARCHAR(255) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT now(),
  PRIMARY KEY (period, item_code)
);

ALTER TABLE IF EXISTS abcxyz_results
  ADD COLUMN IF NOT EXISTS min_qty NUMERIC,
  ADD COLUMN IF NOT EXISTS max_qty NUMERIC,
  ADD COLUMN IF NOT EXISTS item_name VARCHAR(255);

INSERT INTO users(username, password_hash, role)
VALUES ('admin', '$2b$12$1nqmxCFIvossKXkg0vvicuKEGDYZUtm1gea3xMN2rf4hZ8alJFvum', 'admin')
ON CONFLICT DO NOTHING;

-- Goods Receipt (encabezado + líneas)
CREATE TABLE IF NOT EXISTS gr_header (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  warehouse_to VARCHAR(32) NOT NULL,
  reference VARCHAR(64),
  note TEXT,
  user_id VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gr_line (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  gr_id UUID NOT NULL REFERENCES gr_header(id) ON DELETE CASCADE,
  item_code VARCHAR(64) NOT NULL,
  item_name VARCHAR(255) NOT NULL,
  uom VARCHAR(16) NOT NULL DEFAULT 'EA',
  qty NUMERIC(18,3) NOT NULL,
  batch VARCHAR(64),
  serial VARCHAR(64)
);

-- ===== Block A (MVP): Core inventory entities =====
-- Warehouses master
CREATE TABLE IF NOT EXISTS warehouse (
  id SERIAL PRIMARY KEY,
  code VARCHAR(32) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL
);

-- Item master (lightweight, independent from analytics products)
CREATE TABLE IF NOT EXISTS item_master (
  id SERIAL PRIMARY KEY,
  item_code VARCHAR(64) UNIQUE NOT NULL,
  item_name VARCHAR(255) NOT NULL,
  uom VARCHAR(16) NOT NULL DEFAULT 'EA',
  tracking_mode VARCHAR(10) NOT NULL DEFAULT 'NONE', -- NONE|BATCH|SERIAL
  status VARCHAR(16) NOT NULL DEFAULT 'active'       -- active|temporary|inactive
);

-- Inventory balances by warehouse + optional batch/serial
CREATE TABLE IF NOT EXISTS inventory_balance (
  id BIGSERIAL PRIMARY KEY,
  item_code VARCHAR(64) NOT NULL REFERENCES item_master(item_code),
  warehouse_code VARCHAR(32) NOT NULL REFERENCES warehouse(code),
  batch VARCHAR(64),
  serial VARCHAR(64),
  qty NUMERIC(18,3) NOT NULL DEFAULT 0
);

-- Ensure uniqueness for the balance key (using an expression index)
CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_balance
  ON inventory_balance(item_code, warehouse_code, COALESCE(batch,''), COALESCE(serial,''));

-- Generic movements ledger
CREATE TABLE IF NOT EXISTS movement (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type VARCHAR(16) NOT NULL,               -- INBOUND|OUTBOUND|TRANSFER|RETURN|ADJUST
  item_code VARCHAR(64) NOT NULL REFERENCES item_master(item_code),
  item_name VARCHAR(255) NOT NULL,
  qty NUMERIC(18,3) NOT NULL,
  uom VARCHAR(16) NOT NULL,
  warehouse_from VARCHAR(32),
  warehouse_to VARCHAR(32),
  batch VARCHAR(64),
  serial VARCHAR(64),
  reference VARCHAR(64),
  note TEXT,
  user_id VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Cleanup: drop obsolete columns if present
ALTER TABLE IF EXISTS movement DROP COLUMN IF EXISTS document_number;

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_inv_item_wh ON inventory_balance(item_code, warehouse_code);
CREATE INDEX IF NOT EXISTS idx_mov_dt ON movement(created_at);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movement(item_code);

-- Minimal seeds for warehouses
INSERT INTO warehouse(code, name) VALUES
  ('BP','Bodega Principal'), ('M1','Mezzanina 1')
ON CONFLICT (code) DO NOTHING;

-- Convenience views
CREATE OR REPLACE VIEW vw_inventory_totals AS
  SELECT item_code, SUM(qty) AS qty
  FROM inventory_balance
  GROUP BY item_code;

CREATE OR REPLACE VIEW vw_inventory_by_warehouse AS
  SELECT warehouse_code, item_code, SUM(qty) AS qty
  FROM inventory_balance
  GROUP BY warehouse_code, item_code;

-- ===== Block D: HID scanning sessions (count and outbound) =====
-- Count sessions (cycle counting)
CREATE TABLE IF NOT EXISTS count_session (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  warehouse_code VARCHAR(32) NOT NULL REFERENCES warehouse(code),
  status VARCHAR(16) NOT NULL DEFAULT 'open',  -- open|closed
  note TEXT,
  user_id VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS count_entry (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES count_session(id) ON DELETE CASCADE,
  item_code VARCHAR(64) NOT NULL,
  batch VARCHAR(64),
  serial VARCHAR(64),
  qty NUMERIC(18,3) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_count_entry_sess ON count_entry(session_id);

-- Outbound/Transfer scanning sessions (virtual cart)
CREATE TABLE IF NOT EXISTS outbound_session (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type VARCHAR(16) NOT NULL,                 -- OUTBOUND|TRANSFER
  warehouse_from VARCHAR(32) NOT NULL REFERENCES warehouse(code),
  warehouse_to VARCHAR(32),
  status VARCHAR(16) NOT NULL DEFAULT 'open',-- open|confirmed|cancelled
  note TEXT,
  user_id VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outbound_entry (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES outbound_session(id) ON DELETE CASCADE,
  item_code VARCHAR(64) NOT NULL,
  qty NUMERIC(18,3) NOT NULL,
  batch VARCHAR(64),
  serial VARCHAR(64),
  created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_out_entry_sess ON outbound_entry(session_id);
