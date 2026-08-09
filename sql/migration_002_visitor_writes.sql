-- Make the demo writable by strangers without letting them damage the memory.
--
-- The demo is public and unauthenticated. Letting an agent write into it is the
-- point of the project -- a memory nobody can correct is a log -- but a public
-- write endpoint on a real database is an open door, and the usual answer
-- (authenticate the demo) removes the only thing a judge can actually try.
--
-- Three properties, and the third is the one that took a rewrite to get right:
--
--   1. A visitor row carries an expiry and row-level TTL removes it. Twenty
--      four hours later the database is back to its reference state with
--      nobody touching it.
--
--   2. A visitor NEVER mutates an engineer row. The obvious implementation --
--      close the old belief with UPDATE ... SET valid_to = now(), insert the
--      new one -- is not reversible: TTL deletes rows, it does not restore the
--      column it did not write. A stranger would close a real belief for good.
--      So a visitor only INSERTs, and "current" stops meaning "valid_to IS
--      NULL" and starts meaning "the one held most recently". When the visitor
--      row expires, the engineer row is current again by arithmetic rather
--      than by repair.
--
--   3. The revision row points at the belief it created, so it has to go when
--      that belief goes. The foreign keys were created without ON DELETE
--      CASCADE, which would have made the TTL job fail on its first run
--      against a referenced row -- silently, in the background, days later.
--
-- Applied 2026-08-09. Reproducible: psql "$CRDB_URL" -f sql/migration_002_visitor_writes.sql

-- Schema changes need the lock off on this version; it is restored at the end.
ALTER TABLE belief   SET (schema_locked = false);
ALTER TABLE revision SET (schema_locked = false);

-- NULL means permanent. Only the demo endpoint ever sets it.
ALTER TABLE belief   ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE revision ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- A row whose expiry is NULL is never a candidate, which is what keeps the
-- engineer's fourteen revisions out of reach of the sweeper.
ALTER TABLE belief   SET (ttl_expiration_expression = 'expires_at', ttl_job_cron = '*/15 * * * *');
ALTER TABLE revision SET (ttl_expiration_expression = 'expires_at', ttl_job_cron = '*/15 * * * *');

-- Cascade, so the sweeper can delete a belief that a revision still cites.
ALTER TABLE revision DROP CONSTRAINT IF EXISTS revision_belief_old_fkey;
ALTER TABLE revision DROP CONSTRAINT IF EXISTS revision_belief_new_fkey;
ALTER TABLE revision ADD CONSTRAINT revision_belief_old_fkey
  FOREIGN KEY (belief_old) REFERENCES belief(id) ON DELETE CASCADE;
ALTER TABLE revision ADD CONSTRAINT revision_belief_new_fkey
  FOREIGN KEY (belief_new) REFERENCES belief(id) ON DELETE CASCADE;

-- "Current" in one place instead of eight. Greatest valid_from wins, and the
-- id breaks a tie so the answer is stable across runs rather than merely
-- usually the same.
CREATE OR REPLACE VIEW current_belief AS
  SELECT DISTINCT ON (key) id, key, value, status, source, valid_from, valid_to, expires_at
  FROM belief
  WHERE valid_to IS NULL
  ORDER BY key, valid_from DESC, id;

ALTER TABLE belief   SET (schema_locked = true);
ALTER TABLE revision SET (schema_locked = true);
