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

**The demo runs both, on the same instant, rather than asserting the difference.**

```
                                                          answer          took
storage    AS OF SYSTEM TIME '-70m'                        39 beliefs      297 ms
modelled   belief interval, -70m                           25 beliefs
storage    AS OF SYSTEM TIME '-120m'                       refused        3718 ms
                 batch timestamp must be after replica GC threshold
modelled   2026-07-26                                      10 beliefs
```

Three things in that table are worth more than the paragraph above it.

**The refusal is the slow path, not the time travel.** A read inside the window costs what any
read costs. A read past it spends three and a half seconds retrying inside the server before
admitting the versions are gone, and past about three hours it stops answering at all — which is
why the offset is clamped before the database is asked and the connection carries a statement
timeout. A demo that hangs for twenty seconds is a demo a judge closes.

**The two counts differ, and that is not a bug.** Storage counts rows that existed 70 minutes ago,
including superseded ones and one a visitor wrote and let expire. The modelled history counts
beliefs that were *held* then. Storage answers "what was in the table", the model answers "what did
this agent think", and those were never the same question.

**The last line is the argument.** 2026-07-26 is the oldest revision in this memory. Storage cannot
be asked about it at any price on this plan, and the model answers it exactly the way it answers
about ten minutes ago.

*Measured over pgwire on 2026-08-09. The managed MCP server rejects `AS OF SYSTEM TIME` at every
offset, including ones well inside the window — its SQL-over-HTTP layer sets its own timestamp. A
note in this repository had recorded that as a possible 75 minute limit for a week; it was a client
limitation and the window was fine.*

## What do I need to know, and where do I read it

For a week this project had two halves that never spoke. One answers *what is missing* with a join
over computation, requirement and belief: exact, structural, and it names a gap without helping you
close it. The other answers an open question by searching the corpus: useful, and it has no idea
what you are blocked on.

Between them sits the question an engineer actually asks on a Monday, and it needs both:

```
what do I need to know to unblock the FEA run

fea_run   BLOCKED · costs about 2 hours · 6 passages to read
  hub_barrel_architecture   BLOCKING   UNDECIDABLE
      REPRISE.md              similarity 0.58   "6. Reste ouvert, par ordre de rendement
                                                 1. Fût de moyeu ..."
      RECHERCHE_27-30.md      similarity 0.54   "2.1 SKF Hub Bearing Unit ..."
  mesh_independence         BLOCKING   UNDECIDABLE
      REPRISE.md              similarity 0.53   "3.4 La boucle de dimensionnement
                                                 convergeait sur le MAUVAIS critère"
```

One query. The join finds the gaps, then a `LATERAL` vector search reads the corpus **from where
each belief sits** — which is why beliefs carry an embedding of their own, in the same 384
dimensional space as the chunks. Cross-lingual on the way: the questions are English and the notes
are French.

**And it says when the notes are silent.** `bolt_check` is blocked on a belief nothing in the
corpus discusses, so it reports that rather than showing three weak passages. The threshold is
measured, not chosen: a belief compared against all 171 chunks sits at a mean distance of 1.169
with a standard deviation of 0.090, so 0.99 is two standard deviations better than the corpus
average, and anything above it is noise wearing a rank.

*A note on the scale, because getting it wrong sent this feature to the bin for ten minutes. These
are L2 distances between unit vectors, so the range is 0 to 2 and orthogonal is 1.414, not 1. A
distance of 0.91 is a cosine of 0.58. Read 1.0 as "unrelated" and the best retrieval in the project
looks like noise.*

## Telling it something, and being refused

A memory nobody can correct is a log. So the demo takes a claim and the agent answers one of three
ways, and only one of them writes:

| answer | when |
|---|---|
| `REVISE` | the claim settles a belief that was open, or contradicts one that was held |
| `NO CHANGE` | the memory already holds this, for a stated reason |
| `INSUFFICIENT` | the claim reaches a belief but does not settle it, or reaches nothing at all |

The third one is the part worth building. A memory whose argument is that it stores what it does
not know does not get to accept every claim it is handed.

A claim declares its parts rather than having them inferred:

```
hub barrel architecture is B because the mass study closed the 1.7 kg gap
      subject                 value              evidence
```

That is not a shortcut around parsing. An earlier attempt in this codebase at reading intent out of
prose returned four false positives out of four, including on the value that happened to be right.
A claim that does not parse is reported as unparsed, with the shape it wanted.

Matching a subject to a belief is lexical, and the score is shown on screen. Free text cannot be
embedded on this deployment, and in exchange the rule is one a reader can recompute by hand instead
of a similarity they would have to take on faith.

Then the part that makes it worth watching. Beliefs are joined to the computations that need them,
so a sentence moves a two-hour job:

```
fea_run     BLOCKED (2 blocking)  ->  BLOCKED (1 blocking)      costs about 2 hours
```

### A public write endpoint that cannot damage the memory

The demo is open and unauthenticated, which is the only way a judge can actually try it. Three
things make that safe, and the second took a rewrite to get right.

**A visitor row expires.** It carries `expires_at` and row-level TTL removes it within the day. The
engineer's beliefs have no expiry and are never candidates.

That last sentence was an assumption until it was measured, and an unmeasured sweeper is a
decoration. A row was planted already expired at 06:33:45 UTC on 2026-08-09; the sweep runs on a
quarter hour, the job was created at 06:45:06 and finished at 06:45:32, and the row was gone.
Nothing else in the safety argument rests on a claim that has not been run.

**A visitor never mutates an engineer row.** The obvious implementation closes the old belief with
`UPDATE ... SET valid_to = now()` and inserts the new one. That is not recoverable: TTL deletes
rows, it does not restore a column it never wrote, so a stranger would have closed a real belief
for good. A visitor therefore only inserts, and *current* stops meaning `valid_to IS NULL` and
starts meaning *held most recently* — resolved once, in a view. When the visitor row expires, the
engineer's row is current again by arithmetic rather than by repair.

**The revision goes with the belief it created.** The foreign keys were created without
`ON DELETE CASCADE`, which would have made the first sweep against a cited belief fail quietly, in
the background, days later.

The belief and the revision that explains it are written in one transaction. Closing a belief and
opening its successor are one fact about the world, and a memory that can hold the first without
the second is worse than one that refuses both.

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

Two further CockroachDB features carry the write path. They are not on the list of four eligible
tools and are not counted as such here:

| feature | what it holds up |
|---|---|
| Row-level TTL | a public write endpoint that returns to its reference state on its own, with nobody on call |
| Serializable transactions, by default | the belief and the revision that explains it are written together or not at all, with no isolation level to argue about |

**AWS**: the demo is deployed on **S3 and Lambda**. **Amazon Bedrock** is implemented for
embeddings and is not what generated the vectors currently in the database, which is worth
explaining rather than hiding.

The account is one day old and sits at the default Bedrock quota. The documentation states that
default quotas depend on, among other things, payment history. Titan Text Embeddings V2 offers the
Standard tier only, so there is no throughput to buy, and it supports neither geo nor global
cross-region inference. `ThrottlingException` came back for the account root and for a scoped IAM
user alike, across four regions, for over an hour.

So the embedding backend is a flag. `--backend bedrock` is the code that was written first;
`--backend local` runs a multilingual sentence transformer on the CPU and is what the current
vectors come from. A demo that depends on a service which is throttling you is a demo that dies on
screen, and swapping the backend costs one argument.

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
psql "$CRDB_URL" -f sql/migration_002_visitor_writes.sql
psql "$CRDB_URL" -f sql/migration_003_belief_vectors.sql
psql "$CRDB_URL" -f sql/queries.sql
```

The order matters and the comments in `schema.sql` say why. Everything except the time travel query
also works through the managed MCP server.

The migration is not optional and was missing from this list until 2026-08-09. It adds the expiry
column, the row-level TTL, the delete cascade and the `current_belief` view, and the API reads that
view: a database built from `schema.sql` alone is one the deployed code cannot run against. Anyone
who followed these instructions before that date got exactly that, which is a good argument for
running your own install notes on an empty cluster at least once.

Then the corpus:

```bash
pip install --quiet pg8000            # pure Python, nothing to compile
python3 ingest/embed_and_load.py --reset
python3 ingest/embed_beliefs.py       # a vector per belief, and the stored questions
python3 ingest/embed_and_load.py --search "why did the part get thicker"
```

`ingest/chunker.py` produced `data/chunks.jsonl` and is kept here so the boundary is auditable, but
it cannot run for you. It reads a private engineering repository that is not distributed with this
one, and it takes the location as `SANDRAIL_NOTES` rather than assuming a path. Run it without that
variable and it explains itself and exits 2. The passages it produced are in the database, and the
demo shows them whenever a search retrieves one.

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
| Corpus ingestion, 171 chunks, 18 anchored to a belief | done, local backend |
| Vector search, including French corpus against English questions | done |
| Bedrock embeddings | written, blocked on account quota, remeasured across four regions on 2026-08-09 |
| Agent loop that proposes, refuses, or writes a revision | done, six decision paths verified against the live cluster |
| Where to read: structural gaps joined to the corpus | done, one query, threshold measured against the corpus average |
| Tests | `python3 tests/test_agent.py`, 45 checks against the live cluster |
| Public writes bounded by row-level TTL | done |
| Demo application, S3 and Lambda behind an HTTP API | live |

## License

MIT, see [LICENSE](LICENSE).
