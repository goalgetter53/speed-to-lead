# ADR 0002: One portable SQL schema for SQLite (local) and Postgres (Supabase)

Status: accepted, 2026-11-20

## Context
Production runs on Supabase's free Postgres. Local development, tests and the demo must run offline.

## Decision
- Plain SQL migrations in `speed_to_lead/migrations/`, no ORM. Files named `NNN_name.sql` run on both
  engines; `NNN_name.postgres.sql` runs only on Postgres (row-level security for Supabase).
- Timestamps are ISO-8601 UTC strings (`2026-11-17T05:30:00.429Z`), so both engines sort and compare them
  the same way.
- Idempotency through `UNIQUE` keys plus `ON CONFLICT DO NOTHING`: `leads.phone` (dedupe by normalised
  phone) and `events.event_key` (`wa:<wamid>`, `leadgen:<id>`, `form:<id>`, `alert:<lead>:<level>`,
  `fu:<lead>:<n>`). Meta retries webhooks, so the same message processed twice is a no-op.
- `?` placeholders, translated to `%s` for psycopg.

## Consequences
- The whole test suite runs on both engines (CI has a Postgres 16 service job; it was also run locally on
  Postgres 16 while building).
- Date arithmetic happens in Python, not SQL. That is fine at a paint shop's volume (hundreds of leads/month).
