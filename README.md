# A memory that knows what it is missing

**CockroachDB × AWS Hackathon, Build with Agentic Memory**

I spend my evenings designing a suspension upright with an AI agent. Generative CAD, meshing,
finite elements, a fatigue criterion, a loop that resizes the part until it passes. One full run
costs about two hours on my machine.

The expensive mistake is not a wrong result. It is a two hour run that could never have concluded,
because something it needed was not known yet. That happened often enough that I started keeping a
file called "data needs", by hand, listing what was missing and whether it blocked anything.

This project is that file, turned into a memory the agent can query.

It answers three questions:

1. **What do I believe today, and how sure am I?**
2. **What changed my mind, and what evidence did it?**
3. **Can I run this calculation, and if not, what exactly is missing?**

The third one is the one that saves the two hours.

## The idea in one table

Most agent memories store what is known. This one gives equal weight to what is not.
`UNDECIDABLE` and `NOT_FOUND` are statuses, written into a `CHECK` constraint, so an empty cell is
impossible to leave by accident. An empty cell is an invisible debt. A row that says `NOT_FOUND` is
a decision somebody made and can be asked about.

Then each calculation declares what it needs, and how badly:

| | |
|---|---|
| `BLOCKING` | without it the calculation cannot run |
| `DEGRADES` | it runs, but the number does not mean what you think |
| `COSMETIC` | listed so nobody goes looking for it a second time |

"What is missing" stops being a document somebody maintains, and becomes a join.

```
computation            blocking gaps   verdict   cost
fea_run                      2         BLOCKED   about 2 hours
bolt_check                   1         BLOCKED   seconds
rod_end_boss_sizing          1         BLOCKED   minutes
unsprung_mass_budget         1         BLOCKED   minutes
fatigue_check_parent         0         CAN RUN
fatigue_check_welded         0         CAN RUN
scrub_recompute              0         CAN RUN
```

The two hour run is blocked on two things. One is an architecture decision nobody had written down
as a blocker. The other is a measurement problem that was known, filed as a note, and left in
place: mesh size was slaved to part thickness, so the instrument changed with the measurement, and
two runs of the same commit returned 14.00 mm and 13.28 mm.

The vehicle behind this is ambitious and touches a lot of disciplines at once. Nobody holds all of
its variables in their head. That is the real job of this memory.

## Why not just read the database history

CockroachDB already keeps history, so it is a fair question.

On the free plan, `AS OF SYSTEM TIME` reaches back 75 minutes, and that limit is not configurable.
I measured it rather than assuming it. But even with a longer window it would not do the job.
Storage history tells you what a row used to say. It does not tell you why it changed, what
evidence made it change, or which of those values you were unsure about at the time.

So the history is modelled. Beliefs are append only over closed intervals, and every revision
carries its evidence in a `NOT NULL` column, because a revision without evidence is an overwrite
and not learning. Time travel stays as a safety net for the last 75 minutes, which is what it is
good at.

## The data is real, and it is unflattering

None of the seed data is invented. Fourteen revisions, all from dated logs, all moments where the
agent or I got something wrong and found out.

| I believed | it turned out | what changed my mind |
|---|---|---|
| `sigma_a = (VM(Σmax) − VM(Σmin))/2` | `sigma_a = VM(Σmax − Σmin)/2` | Von Mises has no sign, so a full stress reversal read as zero amplitude. On an analytic case, 18 percent optimistic. |
| part mass 5.494 kg | 6.007 kg | a consequence of the line above. A whole day of weight saving cancelled. The 5.494 kg had never existed. |
| the governing cycle is left to right wheel inversion | 8g bump against 1.5g cornering, two orthogonal cases | sweeping all 15 pairs of load states instead of the one I had hard coded. The reasoning was right and the culprit was wrong. |
| the lightening optimiser produces pockets | zero pockets, for two full runs | the log had been printing `n_poches = 0` the whole time and nobody read it. |
| my contest repository is public | 404 | somebody finally clicked the link from a logged out browser. |

Three things it still does not know are stored as such, including a brake disc mass that is an
interpolation and not a measurement, sitting inside a mass budget that reads 27.25 kg known out of
40 declared.

Ask what I believed on 2026-07-30 and you get a mixed answer. I already knew the hub barrel was
not manufacturable and that the optimiser was dead, and I still believed the wrong thickness, the
wrong mass and the wrong governing cycle. No file snapshot reconstructs that, and no `git checkout`
tells you which of those I was unsure about.

## What this does not prove

- The dataset is small on purpose. Fourteen revisions over seventeen beliefs, one subsystem of one
  vehicle. It is real and traceable, it is not a benchmark, and nothing here demonstrates scale.
- Vector search is a working integration, not a performance claim. Nothing was measured on latency
  or recall.
- The requirement graph is only as good as the requirements somebody declares. It catches a gap
  that was written down. It does not discover an input nobody thought of.
- The code here is new, written during the submission window. The data is older. It comes from a
  private engineering repository, and that is the point of it. Nobody would invent failures this
  unflattering for a demo.
- I use AI assistants to build, which the rules allow. I specify, drive and check the work.

## Tools used

**CockroachDB**, two of the four eligible tools:

| tool | how |
|---|---|
| Cloud managed MCP server | the whole schema and dataset were created through it, from the agent session, with no local client |
| Distributed vector indexing | semantic search over the corpus, declared inline on an empty table |

**AWS**: Amazon Bedrock, `amazon.titan-embed-text-v2:0`, 1024 dimensions, `us-east-1`.

### Feedback on the managed MCP server

The organisers asked, and these cost real time:

- `create_table` accepts only `CREATE TABLE`, and there is no generic DDL tool, so every index has
  to be declared inline. That turned out well. `CREATE VECTOR INDEX` blocks writes until its
  backfill finishes, and an inline declaration makes it impossible to build on a populated table.
- There is no `UPDATE`, `DELETE` or `DROP`. A scratch database created by mistake cannot be cleaned
  up through the same channel that created it.
- `AS OF SYSTEM TIME` is rejected at any offset with `inconsistent AS OF SYSTEM TIME timestamp`.
  Time travel needs pgwire.
- Worth knowing before designing around it: 16384 characters per statement, 20 second timeout,
  10 KiB response cap, and `SELECT` defaults to 25 rows.
- All three distance operators work on v26.2.1. I measured them rather than trusting the older
  docs: `<->` gives 1.4142135623730951, `<=>` gives 1, `<#>` gives -0 on orthogonal unit vectors.
  The index itself is built for one operator class, here the default L2, so a query with a
  different operator is correct but will not use the index. Titan embeddings are normalised, so L2
  ranks the same as cosine.

## Running it

```bash
# A CockroachDB Basic cluster, free and no card, at cockroachlabs.cloud
export CRDB_URL='postgresql://<user>:<password>@<host>:26257/agentmem?sslmode=verify-full'

psql "$CRDB_URL" -f sql/schema.sql
psql "$CRDB_URL" -f sql/seed.sql
psql "$CRDB_URL" -f sql/queries.sql
```

The order matters and the comments in `schema.sql` say why. Everything except the time travel query
also works through the managed MCP server.

Then the corpus, which needs Bedrock. This runs as is in AWS CloudShell, where the credentials
already exist:

```bash
pip install --quiet pg8000            # pure Python, nothing to compile
python3 ingest/chunker.py             # notes -> data/chunks.jsonl, offline
python3 ingest/embed_and_load.py --reset
python3 ingest/embed_and_load.py --search "why did the part get thicker"
```

`pg8000` rather than `psycopg2` on purpose, so the same file runs in CloudShell, in a Lambda zip
and on a Windows laptop. Vectors go in one row at a time with a commit every 25, because the
documentation says to avoid large batches of vector inserts.

No credential belongs in this repository, in a commit, or in a chat window. `CRDB_URL` lives in the
environment, `.env` is git ignored, and there is no step in this project where the password has to
be handed to anyone.

## Status

| | |
|---|---|
| Schema, seed data, queries | done, verified by running them on 2026-08-04 |
| Corpus ingestion and Bedrock embeddings | in progress |
| Agent loop that proposes a revision | in progress |
| Demo application | in progress |

## License

MIT, see [LICENSE](LICENSE).
