-- Give a belief a position in the same space as the corpus.
--
-- Until now the project had two halves that never spoke. The structural half
-- answers "what is missing" with a join over computation, requirement and
-- belief. The semantic half answers an open question with a vector search over
-- the corpus. Both work, and between them sits the question an engineer
-- actually asks, which neither could answer:
--
--     what do I need to KNOW to unblock this, and WHERE do I read it
--
-- The answer is a join that crosses from one half to the other: take the
-- requirements a computation is blocked on, take the belief behind each one,
-- and search the corpus from where that belief sits. Which needs the belief to
-- sit somewhere, hence this column.
--
-- 384 dimensions, matching the chunk table, because a vector only means
-- something against vectors from the same model -- here
-- paraphrase-multilingual-MiniLM-L12-v2, the backend that produced the corpus
-- when Bedrock was throttled to zero. A 1024-dimensional belief and a
-- 384-dimensional corpus would not have failed loudly; the operator would have
-- rejected them and the demo would have shown an error nobody could read.
--
-- No index on this column on purpose: there are 39 beliefs and the search runs
-- the other way, over chunk, where the C-SPANN index already is.
--
-- Applied 2026-08-09. Vectors are written by ingest/embed_beliefs.py.

ALTER TABLE belief SET (schema_locked = false);
ALTER TABLE belief ADD COLUMN IF NOT EXISTS embedding VECTOR(384);
ALTER TABLE belief SET (schema_locked = true);

-- The view is recreated because a view does not see a column added after it.
CREATE OR REPLACE VIEW current_belief AS
  SELECT DISTINCT ON (key) id, key, value, status, source, valid_from, valid_to,
                           expires_at, embedding
  FROM belief
  WHERE valid_to IS NULL
  ORDER BY key, valid_from DESC, id;
