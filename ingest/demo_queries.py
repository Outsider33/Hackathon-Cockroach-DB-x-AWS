"""Embed the demo questions once, store the vectors in the database.

Why this file exists, stated plainly because it is a limit and not a feature:
the 171 corpus chunks were embedded with a local 384-dimension multilingual
model, because Bedrock returned ThrottlingException on every region tried, for
both the account root and a scoped IAM user, on a one day old account. A query
vector must live in the same space as the corpus it searches. The Lambda cannot
carry a sentence transformer, so the questions the demo offers are embedded
here, on the laptop, and stored next to the corpus they search.

The vector index is then doing real work at query time in the deployed demo --
what is precomputed is the question, not the answer.

    py -3.12 ingest/demo_queries.py           # embed and load
    py -3.12 ingest/demo_queries.py --list    # show what is stored

When Bedrock quota opens (retest around 2026-08-12), re-embed the corpus in
1024 dimensions, set EMBED_BACKEND=bedrock on the Lambda, and free text works
with no other change.
"""

import argparse
import sys
from pathlib import Path

# embed_and_load forces UTF-8 on stdout at import time -- the console here is
# GBK. Doing it a second time closes the buffer, so it is not done here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from embed_and_load import connect, make_embedder, as_literal, BACKENDS  # noqa: E402

# English, because the contest is judged in English, while the corpus is in
# French. That is not an accident either: it is the cross-language retrieval
# the multilingual model buys, and the demo says so.
QUESTIONS = [
    "why did the part get thicker",
    "what is the fatigue amplitude computed on",
    "what is unknown about the brake disc",
    "why do two runs of the same commit disagree",
    "how was the caliper radius finally found",
    "what is the front wheel",
    "what caused the flicker in the video",
    "what is undecided about the hub barrel",
    "what does the sizing loop converge on",
    "what was wrong with the lightening pockets",
]


def create_table(cursor, dimensions):
    cursor.execute("DROP TABLE IF EXISTS demo_query")
    cursor.execute(
        f"""
        CREATE TABLE demo_query (
          id        UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
          text      STRING NOT NULL UNIQUE,
          embedding VECTOR({dimensions}) NOT NULL,
          backend   STRING NOT NULL
        )
        """
    )


def load(backend):
    embedder = make_embedder(backend)
    connection = connect()
    cursor = connection.cursor()
    create_table(cursor, embedder.dimensions)
    connection.commit()
    for question in QUESTIONS:
        cursor.execute(
            f"INSERT INTO demo_query (text, embedding, backend) "
            f"VALUES (%s, %s::VECTOR({embedder.dimensions}), %s)",
            (question, as_literal(embedder(question)), BACKENDS[backend]["label"]),
        )
        print(f"  {question}")
    connection.commit()
    cursor.execute("SELECT count(*) FROM demo_query")
    print(f"{cursor.fetchone()[0]} demo questions embedded, "
          f"{embedder.dimensions} dimensions, {backend} backend")
    connection.close()


def show():
    connection = connect()
    cursor = connection.cursor()
    cursor.execute("SELECT text, backend FROM demo_query ORDER BY text")
    for text, backend in cursor.fetchall():
        print(f"{backend:52s}  {text}")
    connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=list(BACKENDS), default="local")
    parser.add_argument("--list", action="store_true")
    arguments = parser.parse_args()
    show() if arguments.list else load(arguments.backend)
