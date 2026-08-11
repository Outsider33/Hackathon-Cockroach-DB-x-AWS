-- migration_004_fixed_instrument.sql
--
-- Brings a LIVE database up to the state seed.sql now describes, without
-- rebuilding it.
--
-- 🔴 Why a migration and not simply replaying seed.sql. seed.sql is a from-scratch
-- build: its INSERTs are unconditional and nothing truncates first, so replaying
-- it against a running cluster duplicates all forty beliefs. That is a good way to
-- destroy a demo three days before a deadline. The repository already had the
-- convention -- migration_002, migration_003 -- and this follows it.
--
-- What it applies: the three revisions of 2026-08-11, discovered when a fixed-size
-- mesh was measured against the one that had been slaved to thickness.
--
-- 🟢 IDEMPOTENT. Every statement is guarded, so running it twice changes nothing
-- the second time. Verified by the WHERE clauses, not by intention.

USE agentmem;

BEGIN;

-- 1. Close what the fixed instrument superseded. Guarded on valid_to IS NULL so a
--    second run finds nothing to close.
UPDATE belief SET valid_to = TIMESTAMPTZ '2026-08-11 00:00:00+00'
 WHERE key = 'mesh_independence' AND valid_to IS NULL AND status = 'UNDECIDABLE'
   AND source <> 'demo visitor';

UPDATE belief SET valid_to = TIMESTAMPTZ '2026-08-11 00:00:00+00'
 WHERE key IN ('part_thickness', 'part_mass') AND valid_to IS NULL
   AND valid_from = TIMESTAMPTZ '2026-07-31 00:00:00+00';

-- 2. Open what replaces it. NOT EXISTS keeps a second run inert.
INSERT INTO belief (key, value, status, source, valid_from, valid_to)
SELECT * FROM (VALUES
  ('mesh_independence',
   'INDEPENDENT -- with a constant clmax of 6.0 mm, two runs of the same commit on 2026-08-11 returned exactly 12.74 mm, 6.69 kg, SF 1.51',
   'ESTABLISHED',
   'FEA runs of 2026-08-11, morning and evening, fixed-instrument mesh',
   TIMESTAMPTZ '2026-08-11 00:00:00+00', NULL::TIMESTAMPTZ),
  ('part_thickness', '12.74 mm', 'ESTABLISHED',
   'FEA runs of 2026-08-11, fixed-instrument mesh, two runs agreeing',
   TIMESTAMPTZ '2026-08-11 00:00:00+00', NULL::TIMESTAMPTZ),
  ('part_mass', '6.69 kg', 'ESTABLISHED',
   'FEA runs of 2026-08-11, fixed-instrument mesh, two runs agreeing',
   TIMESTAMPTZ '2026-08-11 00:00:00+00', NULL::TIMESTAMPTZ)
) AS v(key, value, status, source, valid_from, valid_to)
WHERE NOT EXISTS (
  SELECT 1 FROM belief b
   WHERE b.key = v.key AND b.valid_from = v.valid_from AND b.source = v.source);

-- 3. And what changed the agent's mind. `evidence` is NOT NULL by design: a
--    revision without proof is an overwrite, not a lesson.
INSERT INTO revision (belief_old, belief_new, occurred_at, evidence, evidence_source)
SELECT o.id, n.id, TIMESTAMPTZ '2026-08-11 00:00:00+00',
  CASE o.key
    WHEN 'mesh_independence' THEN 'The instrument was the defect, not the mesher. Element size had been slaved to thickness, so it changed with every iteration and no two were comparable -- which is why the same commit returned 14.00 mm and 13.28 mm, and why the safety factor once JUMPED from 1.44 to 2.24 for 0.21 mm of ADDED thickness, a physical impossibility. Fixing the size at 6.0 mm made the loop converge monotonically in two iterations instead of five plus a fallback, and two independent runs the same day returned identical results to the second decimal. The fix costs 35.9 s of meshing, eight times under the budget that had been blamed for it.'
    WHEN 'part_thickness' THEN 'Measured again once the instrument stopped moving. The 14.00 mm had been converged on a mesh whose element size followed the thickness, so each iteration was measured with a different ruler. At a fixed 6.0 mm the loop settles at 12.74 mm, and two independent runs on 2026-08-11 agree to the second decimal. The part is 1.26 mm thinner than believed, and the safety factor is unchanged at 1.51 -- the margin was never the issue, the repeatability was.'
    WHEN 'part_mass' THEN 'Same fix, and an honest anomaly recorded rather than smoothed over: the part gets THINNER while it gets HEAVIER, 12.74 mm for 6.69 kg, with the same 42 pockets. That combination is not explained yet. Worse, the 6.007 kg it replaces matches no archived run on disk -- the two runs of 2026-07-31 recorded 6.972 kg and 6.849 kg. So this revision corrects a number whose own provenance was already broken, and says so instead of pretending the chain was clean.'
  END,
  'CAD_Pipeline/REPRISE.md'
FROM belief o
JOIN belief n ON o.key = n.key
             AND n.valid_from = TIMESTAMPTZ '2026-08-11 00:00:00+00'
             AND n.valid_to IS NULL
             AND n.source LIKE 'FEA runs of 2026-08-11%'
WHERE o.key IN ('mesh_independence', 'part_thickness', 'part_mass')
  AND o.valid_to = TIMESTAMPTZ '2026-08-11 00:00:00+00'
  AND NOT EXISTS (SELECT 1 FROM revision r WHERE r.belief_old = o.id AND r.belief_new = n.id);

COMMIT;

-- ---------------------------------------------------------------------------
-- Check afterwards. Expected: three rows, and exactly one open belief per key.
-- ---------------------------------------------------------------------------
-- SELECT key, value, status FROM belief
--  WHERE valid_to IS NULL AND key IN ('mesh_independence','part_thickness','part_mass')
--  ORDER BY key;
--
-- SELECT key, count(*) FROM belief WHERE valid_to IS NULL AND source <> 'demo visitor'
--  GROUP BY key HAVING count(*) > 1;     -- must return zero rows
