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
--
-- The width below is the Bedrock one. It is not what the loaded corpus uses:
-- Bedrock was throttled at the account level on 2026-08-04, so the 171 chunks
-- were embedded locally with paraphrase-multilingual-MiniLM-L12-v2, which is
-- 384 wide. ingest/embed_and_load.py drops and recreates this table at the
-- width of whichever backend it runs with, so the live table is VECTOR(384)
-- today and this file is the shape it takes once Bedrock is reachable again.
-- Read the width from the backend, not from here.
CREATE TABLE chunk (
  id        UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
  file      STRING NOT NULL,
  text      STRING NOT NULL,
  embedding VECTOR(1024),
  belief_id UUID REFERENCES belief(id),
  VECTOR INDEX chunk_emb (embedding)
);

-- A calculation the agent knows how to run, and what it costs to run it.
-- Cost matters: a two hour run that cannot conclude is the expensive mistake.
CREATE TABLE computation (
  id        UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
  name      STRING NOT NULL UNIQUE,
  purpose   STRING NOT NULL,
  standard  STRING,
  cost_note STRING
);

-- What a calculation needs before it can run, and how badly it needs it.
-- This is the join that turns "what do I know" into "what am I missing".
-- BLOCKING  : without it the calculation cannot run at all
-- DEGRADES  : it runs, but the result does not mean what you think
-- COSMETIC  : listed so nobody goes looking for it a second time
CREATE TABLE requirement (
  id             UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
  computation_id UUID   NOT NULL REFERENCES computation(id),
  belief_key     STRING NOT NULL,
  criticality    STRING NOT NULL,
  why            STRING NOT NULL,
  CONSTRAINT criticality_is_declared CHECK (criticality IN ('BLOCKING','DEGRADES','COSMETIC')),
  INDEX requirement_by_key (belief_key)
);
