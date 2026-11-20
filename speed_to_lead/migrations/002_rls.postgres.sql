-- Supabase only: lock tables away from the public anon/authenticated API roles.
-- The service connects with the database connection string (postgres role), which bypasses RLS.
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE baseline_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE owner_pings ENABLE ROW LEVEL SECURITY;
