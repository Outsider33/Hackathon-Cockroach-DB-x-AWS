-- Bitemporal agent memory -- schema.
-- CockroachDB Basic, v26.2.1. Created and verified by execution on 2026-08-04.
--
-- THE STATEMENT ORDER IS CONSTRAINED. Three documented reasons:
--
--   1. CREATE VECTOR INDEX blocks mutations on the indexed column until the
--      backfill completes. The vector index is therefore declared INLINE in
--      CREATE TABLE -- i.e. on an empty table, before any ingestion. Declaring
--      it inline makes the constraint impossible to violate later.
--   2. Only euclidean distance <-> is supported. Cosine <=> and inner product
--      <#> are on the roadmap and fail today. Titan embeddings are normalised,
--      so euclidean ranks identically to cosine.
--   3. Large insert batches degrade vector write performance. Ingest in
--      batches of 50 to 100 rows.
--
-- VECTOR and the C-SPANN index are in preview since 25.2. See the README,
-- section "What this project does not prove".

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
