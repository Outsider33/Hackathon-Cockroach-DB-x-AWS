# Applying `migration_004_fixed_instrument.sql`

*Written 2026-08-12. Read this once, then run three commands.*

---

## What it is for

On 2026-08-11 the sizing loop was measured with a mesh whose element size no longer
followed the thickness of the part. Three beliefs changed as a result, and the
repository was updated the same day. **The live database was not**, so the
deployment and the repository stopped agreeing — which is the exact defect this
project exists to make visible.

| belief | live database says | should say |
|---|---|---|
| `mesh_independence` | `UNDECIDABLE` | **`ESTABLISHED`** |
| `part_thickness` | `14.00 mm` | **`12.74 mm`** |
| `part_mass` | `6.007 kg` | **`6.69 kg`** |
| `fatigue_safety_factor` | `1.51` | 🟢 **unchanged, and not touched** |

---

## 🔴 Why this is a migration and not a replay of `seed.sql`

**`seed.sql` is a from-scratch build.** Its `INSERT`s are unconditional and nothing
truncates first, so replaying it against a running cluster **duplicates all forty
beliefs**. Every view would then return each fact twice, and the memory would
contradict itself while looking busy.

This file only moves what changed.

🟢 **It is idempotent, and by construction rather than by intention.** The `UPDATE`s
require `valid_to IS NULL`, the `INSERT`s sit under `NOT EXISTS`. Running it a
second time finds nothing to do. If you are unsure whether it already ran, run it.

---

## Run it

```bash
# 1. Point at the cluster. The sslrootcert=system is what makes a fresh shell work.
export CRDB_URL='postgresql://<user>:<password>@<host>:26257/agentmem?sslmode=verify-full&sslrootcert=system'

# 2. Apply. One transaction: it either all lands or none of it does.
psql "$CRDB_URL" -f sql/migration_004_fixed_instrument.sql
```

**Expected output** — three statements reporting rows, then `COMMIT`:

```
UPDATE 1
UPDATE 2
INSERT 0 3
INSERT 0 3
COMMIT
```

⚠️ **If the second `INSERT` reports `0 0`**, the revisions did not attach. That means
the closing `UPDATE`s found nothing, which means the migration had already run.
Harmless — check with the queries below.

---

## Check it, three ways

**1. From `psql`, the invariant that matters most:**

```sql
-- Exactly one open belief per key, ignoring visitor overlays.
-- This must return ZERO rows. CockroachDB has no EXCLUDE constraint, so
-- nothing enforces it but us.
SELECT key, count(*) FROM belief
 WHERE valid_to IS NULL AND source <> 'demo visitor'
 GROUP BY key HAVING count(*) > 1;
```

**2. From `psql`, that the values actually moved:**

```sql
SELECT key, value, status FROM belief
 WHERE valid_to IS NULL
   AND key IN ('mesh_independence','part_thickness','part_mass')
 ORDER BY key;
```

**3. 🎯 From anywhere, against the live API — the real check:**

```bash
python3 tests/stress_invariants.py
```

**`BT6` is the one to watch.** It asks whether the live database says what the
repository says, and it is currently the only red line of the bench:

```
[ FAUX ] BT6 la base vive dit ce que le depot dit    part_thickness = '14.00 mm'
```

After the migration it turns green, and the bench reads **20 / 20**.

---

## If it goes wrong

The whole file is one transaction, so a failure leaves the database exactly as it
was. Nothing partial can land.

| symptom | what it is |
|---|---|
| `root certificate file ... does not exist` | the `sslrootcert=system` is missing from the URL |
| `relation "belief" does not exist` | wrong database in the URL — it must end `/agentmem` |
| `UPDATE 0` on every statement | already applied. Confirm with the queries above |
| anything else | nothing was written. Copy the error, change nothing, ask |

⛔ **Do not "fix" a TLS error by switching to `sslmode=require`.** It removes server
verification. The error is asking for a trust store, not for less security.

---

## What it does NOT do

- it does not touch `fatigue_safety_factor`, which measured 1.51 before and after
- it does not touch visitor overlays, which expire on their own
- it does not delete anything at all: closed beliefs stay readable, which is the
  entire point of keeping validity intervals rather than overwriting rows
