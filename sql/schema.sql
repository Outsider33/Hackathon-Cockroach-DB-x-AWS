-- Bitemporal agent memory -- schema.
-- CockroachDB Basic, v26.2.1. Created and verified by execution on 2026-08-04.
--
-- THE STATEMENT ORDER IS CONSTRAINED. Three documented reasons:
--
--   1. CREATE VECTOR INDEX blocks mutations on the indexed column until the
--      backfill completes. The vector index is therefore declared INLINE in
--      CREATE TABLE -- i.e. on an empty table, before any ingestion. Declaring
--      it inline makes the constraint impossible to violate later.
--   2. All three distance operators work on v26.2.1 (measured: <-> , <=> , <#>).
--      But an index is built for ONE operator class -- the default here is L2
--      (vector_l2_ops). A query using <=> against an L2 index is correct and
--      does not use the index. Titan embeddings are normalised, so L2 ranks
--      identically to cosine and the default is the right one here.
--   3. Large insert batches degrade vector write performance -- the docs say
--      explicitly to avoid batching. Ingest in batches of 50 to 100 rows.
--
-- Also, from the managed MCP server: 16,384 characters per statement, a
-- 20-second timeout and a 10 KiB response cap. Ingestion must be chunked.

CREATE DATABASE IF NOT EXISTS agentmem;
USE agentmem;

-- What was believed, and over which interval it was believed.
-- Append-only: a belief is never corrected in place. Its interval is closed
-- and a new row opens. `status` is the point of the whole schema -- what the
-- memory does NOT know is stored at the same rank as what it knows, and the
-- CHECK constraint makes an empty cell impossible to write by accident.
CREATE TABLE belief (
  id         UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  key        STRING      NOT NULL,
  value      STRING      NOT NULL,
  status     STRING      NOT NULL,
  source     STRING,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to   TIMESTAMPTZ,
  CONSTRAINT status_is_declared CHECK (status IN ('ESTABLISHED','UNDECIDABLE','NOT_FOUND')),
  INDEX belief_key_from (key, valid_from DESC)
);

-- What changed the agent's mind. `evidence` is NOT NULL on purpose:
-- a revision without evidence is an overwrite, not learning.
CREATE TABLE revision (
  id              UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  belief_old      UUID        REFERENCES belief(id),
  belief_new      UUID        NOT NULL REFERENCES belief(id),
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence        STRING      NOT NULL,
  evidence_source STRING
);

-- The corpus, anchored to the beliefs it supports. Embeddings and facts live
-- in the same database and are written in the same transaction: no ETL, no
-- second system to keep in sync.
CREATE TABLE chunk (
  id        UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
  file      STRING NOT NULL,
  text      STRING NOT NULL,
  embedding VECTOR(1024),
  belief_id UUID REFERENCES belief(id),
  VECTOR INDEX chunk_emb (embedding)
);
