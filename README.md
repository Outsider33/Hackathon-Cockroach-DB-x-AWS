# A memory that records what it does not know

**CockroachDB × AWS Hackathon — "Build with Agentic Memory"**

An agent memory built on two ideas that most agent memories skip:

1. **Uncertainty is a first-class value.** `UNDECIDABLE` and `NOT_FOUND` are stored at the same
   rank as facts, enforced by a `CHECK` constraint. An empty cell is an invisible debt; a row that
   says `NOT_FOUND` is a documented decision.
2. **A belief has a lifetime, and a reason for ending.** Beliefs are append-only over closed
   intervals. Every revision carries the evidence that caused it, in a `NOT NULL` column — because
   a revision without evidence is an overwrite, not learning.

---

## What this project does not prove

*Read this first. It is here because the rest of the README is more convincing than the code.*

- **The dataset is small on purpose.** 14 revisions across 17 beliefs. They are real, dated and
  traceable to a source file, but they are not a benchmark and nothing here demonstrates scale.
- **Vector search here is a working integration, not a performance claim.** Everything was run on
  CockroachDB v26.2.1; no latency or recall was measured.
- **`AS OF SYSTEM TIME` is not the mechanism.** On the free Basic plan the MVCC window is
  `gc.ttlseconds = 4500` — 1 hour 15 minutes, not configurable. Measured, not assumed. That is the
  reason history is modelled explicitly rather than read off the storage layer.
- **The author did not write this code by hand.** It was specified, driven and verified by him,
  and generated with an AI agent. The engineering claims in the dataset are his; the SQL is a
  collaboration. Saying otherwise would be the first thing this memory would have to revise.

**Disclosure.** All code in this repository is new, written during the submission period. The
*data* is not: the 14 revisions are extracted from dated engineering logs in a private repository
that predates the hackathon. That is the point of them — they could not have been invented for a
demo, and they are unflattering enough that nobody would have.

---

## Why the MVCC layer is not enough

A distributed database already keeps history. So the honest question for a hackathon on agentic
memory is: why model it at all?

> **MVCC gives you 75 minutes of accidental history. An agent needs deliberate history.**

The difference matters exactly when the agent was wrong three weeks ago, which is the only case
anybody cares about. Accidental history expires, has no notion of *why*, and cannot distinguish a
fact that was corrected from a fact that was merely rewritten. Deliberate history keeps the
interval, the evidence, and the source — forever, and queryable.

`AS OF SYSTEM TIME` still earns its place as a secondary demonstration: recovering an accidental
overwrite inside the 75-minute window. It is a safety net, not a memory.

---

## The data is real, and it is unflattering

None of the seed data is synthetic. It comes from a two-week engineering log where an AI agent and
its author ran a generative-CAD → meshing → FEA → fatigue pipeline for a suspension upright. Every
row is a moment where the agent was wrong, found out, and recorded what changed its mind.

| the agent believed | it turned out | what changed its mind |
|---|---|---|
| `sigma_a = (VM(Σmax) − VM(Σmin))/2` | `sigma_a = VM(Σmax − Σmin)/2` | Von Mises carries no sign, so a full stress reversal read as **zero amplitude**. On an analytic case, an **18% underestimate**. |
| part mass `5.494 kg` | `6.007 kg` | a consequence of the above. A full day of weight optimisation was cancelled — **the 5.494 kg had never existed**. |
| the governing cycle is left/right wheel inversion | `8g bump ↔ 1.5g cornering`, two **orthogonal** cases | sweeping all 15 state pairs instead of the hard-coded one. The reasoning was right in principle and **wrong about the culprit**. |
| the lightening optimiser produces pockets | **0 pockets, for two full runs** | the run log had been printing `n_poches = 0` and nobody read it. |
| the submission repository is public | **404** | somebody finally clicked the link from a logged-out browser. |

And three things it still does not know, stored as such: `mesh_independence` is `UNDECIDABLE`
(two runs of the same commit return 14.00 mm and 13.28 mm, unexplained), `additive_fatigue_data`
is `NOT_FOUND`, `published_numbers_checked` is `UNDECIDABLE`.

**Query 1 is the one to look at.** Ask what the agent believed on 2026-07-30 and you get a *mixed*
state: it already knew the hub barrel was unmanufacturable and the optimiser was dead, while still
believing the wrong thickness, the wrong mass and the wrong governing cycle. No file snapshot can
reconstruct that, and no `git checkout` can tell you which of those beliefs were uncertain.

---

## Tools used

**CockroachDB (2 of the 4 eligible tools):**

| tool | how it is used |
|---|---|
| **CockroachDB Cloud managed MCP server** | the entire schema was created and seeded through it, from the agent session — no local client involved. Its limits are documented below and in `sql/queries.sql`. |
| **Distributed vector indexing** | semantic search over the corpus, declared inline on an empty table so it can never be built on a populated one. |

All three distance operators work on v26.2.1 — measured, not assumed:
`<-> = 1.4142135623730951`, `<=> = 1`, `<#> = -0` on orthogonal unit vectors. The index itself is
built for one operator class (here the default, L2); a query using a different operator is correct
but will not use it. Titan embeddings are normalised, so L2 ranks identically to cosine.

**AWS:** **Amazon Bedrock**, `amazon.titan-embed-text-v2:0`, 1024 dimensions, `us-east-1`.

### What we learned about the managed MCP server

Reported here because the organisers asked for feedback on the AI tooling, and because these cost
real time:

- **`create_table` accepts only `CREATE TABLE`**, and there is no generic DDL tool. Secondary
  indexes and vector indexes must therefore be **declared inline** in the table definition. This
  turned out to be a blessing: `CREATE VECTOR INDEX` blocks mutations until its backfill finishes,
  and an inline declaration makes it structurally impossible to create the index on a populated
  table.
- **`AS OF SYSTEM TIME` is rejected outright** by the SQL-over-HTTP path, at any offset, with
  `inconsistent AS OF SYSTEM TIME timestamp`. Time-travel queries need pgwire.
- **Hard limits worth knowing before you design around it:** 16,384 characters per statement,
  a 20-second query timeout, a 10 KiB response cap, and `SELECT` defaults to `LIMIT 25`. Ingestion
  has to be chunked for the statement cap as much as for the vector-batching advice.

---

## Running it

```bash
# 1. A CockroachDB Basic cluster (free, no card) at cockroachlabs.cloud
export CRDB_URL='postgresql://<user>:<password>@<host>:26257/agentmem?sslmode=verify-full'

# 2. Schema, then data. The order matters -- see the comments in schema.sql.
psql "$CRDB_URL" -f sql/schema.sql
psql "$CRDB_URL" -f sql/seed.sql

# 3. The demonstration
psql "$CRDB_URL" -f sql/queries.sql
```

Requires `psql` (any recent PostgreSQL client) for time-travel queries; everything else works
through the managed MCP server. Embedding generation requires AWS credentials with
`bedrock:InvokeModel` in `us-east-1`. Copy `.env.example` to `.env` and fill it in — `.env` is
git-ignored, and **no credential belongs in this repository or in a chat window**.

## Status

| | |
|---|---|
| Schema, seed data, queries 1–4 | ✅ verified by execution, 2026-08-04 |
| Corpus ingestion + Bedrock embeddings | 🚧 in progress |
| Vector search over the corpus | 🚧 in progress |
| Demo application URL | 🚧 in progress |
| `AS OF SYSTEM TIME` recovery demo | 🚧 pending, pgwire only |

## License

MIT — see [LICENSE](LICENSE).
