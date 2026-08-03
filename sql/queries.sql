-- The queries that make the demonstration.
-- All verified by execution on 2026-08-04 against the seeded data.

-- ---------------------------------------------------------------------------
-- 1. What did the agent believe on a given day, and how sure was it?
--
-- Observed on 2026-07-30, and the MIXED state is the whole point: the agent
-- already knew the hub barrel was not manufacturable and that the optimiser
-- was dead, but it still believed 11.53 mm, 5.494 kg, the scalar fatigue
-- formula, the wrong governing cycle, and that its submission repo was public.
--
-- A file snapshot cannot answer this. A git checkout gives you the documents,
-- not the beliefs, and says nothing about which of them were still uncertain.
-- ---------------------------------------------------------------------------
SELECT key, value, status, source
FROM belief
WHERE valid_from <= '2026-07-30'
  AND (valid_to IS NULL OR valid_to > '2026-07-30')
ORDER BY status, key;

-- ---------------------------------------------------------------------------
-- 2. What changed the agent's mind, and what evidence triggered it?
-- ---------------------------------------------------------------------------
SELECT b_old.key,
       b_old.value AS believed,
       b_new.value AS revised_to,
       r.occurred_at,
       r.evidence,
       r.evidence_source
FROM revision r
JOIN belief b_old ON b_old.id = r.belief_old
JOIN belief b_new ON b_new.id = r.belief_new
ORDER BY r.occurred_at DESC, b_old.key;

-- ---------------------------------------------------------------------------
-- 3. What the memory does NOT know -- at the same rank as what it knows.
--
-- This is the query most agent memories cannot answer at all, because an
-- unknown is stored as an absent row and an absent row is indistinguishable
-- from a question never asked.
-- ---------------------------------------------------------------------------
SELECT key, status, value, source
FROM belief
WHERE status <> 'ESTABLISHED' AND valid_to IS NULL
ORDER BY status, key;

-- ---------------------------------------------------------------------------
-- 4. Which beliefs have been revised most often? Churn as a risk signal:
--    a key that keeps moving is a key you should not build on yet.
-- ---------------------------------------------------------------------------
SELECT b.key, count(*) AS revisions, max(r.occurred_at) AS last_revised
FROM revision r
JOIN belief b ON b.id = r.belief_new
GROUP BY b.key
ORDER BY revisions DESC, last_revised DESC;

-- ---------------------------------------------------------------------------
-- 5. Secondary demonstration: recovering an accidental overwrite with MVCC.
--
-- /!\ DOES NOT WORK THROUGH THE MANAGED MCP SERVER. The SQL-over-HTTP API
--     sets its own timestamp and rejects the clause with
--     "inconsistent AS OF SYSTEM TIME timestamp", at any offset. Measured on
--     2026-08-04 at both -10m and -3h. Run it over pgwire instead:
--         psql "$CRDB_URL" -f sql/queries.sql
--
-- On CockroachDB Basic, gc.ttlseconds = 4500 -- a 1h15 window, and it is not
-- configurable on that plan. That limit is the reason this project models
-- history explicitly instead of reading it off the MVCC layer.
-- ---------------------------------------------------------------------------
-- SELECT count(*) FROM belief AS OF SYSTEM TIME '-10m';
