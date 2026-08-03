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

-- ---------------------------------------------------------------------------
-- 6. THE ONE THAT SAVES TIME: can I run this, and if not, what is missing?
--
-- Verdict on the seeded data:
--   fea_run              BLOCKED   2 blocking gaps   about 2 hours
--   bolt_check           BLOCKED   1 blocking gap
--   rod_end_boss_sizing  BLOCKED   1 blocking gap
--   unsprung_mass_budget BLOCKED   1 blocking gap
--   fatigue_check_parent CAN RUN
--   fatigue_check_welded CAN RUN
--   scrub_recompute      CAN RUN
--
-- The two hour FEA run is blocked on a decision nobody had written down as a
-- blocker, and on a measurement problem that was known and filed as a note.
-- ---------------------------------------------------------------------------
SELECT c.name AS computation,
       count(*) FILTER (WHERE b.status IS DISTINCT FROM 'ESTABLISHED'
                          AND r.criticality = 'BLOCKING') AS blocking_gaps,
       CASE WHEN count(*) FILTER (WHERE b.status IS DISTINCT FROM 'ESTABLISHED'
                                    AND r.criticality = 'BLOCKING') = 0
            THEN 'CAN RUN' ELSE 'BLOCKED' END AS verdict,
       c.cost_note
FROM computation c
LEFT JOIN requirement r ON r.computation_id = c.id
LEFT JOIN belief b ON b.key = r.belief_key AND b.valid_to IS NULL
GROUP BY c.name, c.cost_note
ORDER BY blocking_gaps DESC, c.name;

-- ---------------------------------------------------------------------------
-- 7. And the detail: exactly which input, at what criticality, and why.
-- ---------------------------------------------------------------------------
SELECT c.name AS computation,
       r.criticality,
       r.belief_key,
       coalesce(b.status, 'ABSENT') AS status,
       r.why
FROM computation c
JOIN requirement r ON r.computation_id = c.id
LEFT JOIN belief b ON b.key = r.belief_key AND b.valid_to IS NULL
WHERE b.id IS NULL OR b.status <> 'ESTABLISHED'
ORDER BY r.criticality, c.name;
