-- Portable SQL: runs on SQLite (local/demo) and Postgres (Supabase).
-- Timestamps are ISO-8601 UTC strings so both engines sort them identically.
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  phone TEXT NOT NULL UNIQUE,            -- E.164, dedupe key
  name TEXT,
  source TEXT NOT NULL,                  -- whatsapp_direct | ctwa_ad | meta_lead_ad | website | gbp | instagram | walk_in | phone_call | ...
  source_detail TEXT,                    -- ad id / form id / utm / ref token
  created_at TEXT NOT NULL,
  last_inbound_at TEXT,
  language TEXT,
  area TEXT,
  pincode TEXT,
  distance_km REAL,
  project_type TEXT,                     -- interior | exterior | waterproofing | wood_polish
  size_text TEXT,
  budget_text TEXT,
  timeline TEXT,                         -- now | soon | later
  customer_type TEXT,                    -- homeowner | contractor
  score INTEGER,
  score_bucket TEXT,
  score_explain TEXT,                    -- JSON list of lines
  owner TEXT,                            -- father | painter | hussain
  route_reason TEXT,
  status TEXT NOT NULL DEFAULT 'new',    -- new | contacted | quoted | won | lost
  consent_source TEXT,
  consent_at TEXT,
  opted_out INTEGER NOT NULL DEFAULT 0,
  opted_out_at TEXT,
  first_auto_reply_at TEXT,
  first_human_reply_at TEXT,
  quote_value INTEGER,                   -- rupees
  invoice_value INTEGER,                 -- rupees
  lost_reason TEXT,
  synthetic INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL REFERENCES leads(id),
  event_key TEXT NOT NULL UNIQUE,        -- idempotency: wa:<wamid>, leadgen:<id>, form:<uuid>, alert:<lead>:<n>
  kind TEXT NOT NULL,                    -- inbound | auto_reply | followup | human_reply | quote | won | lost | alert | opt_out | opt_in | note
  channel TEXT,
  actor TEXT,
  body TEXT,
  meta TEXT,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_kind_at ON events(kind, at);

-- Baseline: 2 weeks of the CURRENT manual process, logged by the shop before go-live.
CREATE TABLE IF NOT EXISTS baseline_log (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  lead_at TEXT NOT NULL,
  first_reply_at TEXT,
  outcome TEXT,                          -- open | quoted | won | lost
  quote_value INTEGER,
  invoice_value INTEGER,
  notes TEXT,
  logged_by TEXT,
  synthetic INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- Owners pinging the business number keep their own free 24h window open for alerts.
CREATE TABLE IF NOT EXISTS owner_pings (
  owner TEXT PRIMARY KEY,
  last_at TEXT NOT NULL
);
