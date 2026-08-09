"""Place every belief in the corpus's vector space, and widen the question set.

    python3 ingest/embed_beliefs.py

Two jobs, one model load, because loading the model costs more than either
computation.

1. A vector per belief. That is what lets "what is blocking the FEA run" become
   "and here are the three passages in your own notes that discuss it": the
   structural join finds the belief, and the belief's position finds the
   reading. Without it the two halves of this project never touch.

2. More stored questions. Free text cannot be embedded at request time on this
   deployment -- Bedrock is throttled to zero on the account and a sentence
   transformer does not fit in a Lambda -- so a question only searches if its
   vector is already in the database. Ten of them made the semantic half look
   like a demo of ten buttons. These cover the belief space instead.

Same model as the corpus, and the check is not decorative: a vector is only
comparable to vectors from the same model, and a mismatch here would not fail
loudly, it would return confident nonsense.
"""

import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

import pg8000.dbapi

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "paraphrase-multilingual-MiniLM-L12-v2"
MODEL = f"sentence-transformers/{BACKEND}"
DIMENSIONS = 384

# Questions an engineer would actually type, spread over the belief space
# rather than over the five that demo well. The ones that land on UNDECIDABLE
# and NOT_FOUND matter most: they are the reason this memory exists.
QUESTIONS = [
    # the open ones
    "what is undecided about the hub barrel",
    "what is unknown about the brake disc",
    "why can two runs of the same commit disagree",
    "what is not settled about the rod ends",
    "what is missing before the FEA run can start",
    "which numbers have never been checked",
    "is there fatigue data for this alloy",
    "what is the bore radius of the hub",
    # what changed, and why
    "why did the part get thicker",
    "what changed my mind about the safety factor",
    "why was the pocket optimiser wrong",
    "what was wrong with the lightening pockets",
    "what caused the flicker in the video",
    "why was the repository private",
    "what was retyped instead of being read",
    "which belief was corrected most recently",
    # method and criteria
    "what does the sizing loop converge on",
    "what is the fatigue amplitude computed on",
    "which load case governs the design",
    "how is the stopping tolerance defined",
    "why is the mesh not independent",
    "what is the convergence criterion",
    "how is lateral acceleration justified",
    "what happens when the optimiser finds nothing",
    # parts and numbers
    "what is the front wheel",
    "how was the caliper radius finally found",
    "what is the mass of the part",
    "how thick is the upright",
    "what is the safety factor in fatigue",
    "is the hub barrel manufacturable",
    "what surface treatment is applied",
    "what is the disc radius used for",
    "how heavy is the brake disc",
    "what is the rod end spacing on screen",
    # the work itself
    "what does the grading actually reward",
    "what did I get wrong about the contest",
    "what is dead code in this pipeline",
    "which input goes nowhere",
    "what was measured rather than assumed",
    "where does the bearing spacing go wrong",
]


def connect():
    url = os.environ.get("CRDB_URL")
    if not url:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("CRDB_URL"):
                url = line.split("=", 1)[1].strip().strip("'\"")
    if not url:
        sys.exit("CRDB_URL is not set. It never goes in a file that git tracks.")
    parsed = urlparse(url)
    connection = pg8000.dbapi.connect(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=(parsed.path or "/agentmem").lstrip("/").split("?")[0],
        ssl_context=ssl.create_default_context(),
        application_name="agentmem-embed-beliefs",
    )
    connection.autocommit = True
    return connection


def literal(vector):
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


def main():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)

    probe = model.encode("dimension probe", normalize_embeddings=True)
    if len(probe) != DIMENSIONS:
        sys.exit(f"model returns {len(probe)} dimensions, the corpus is {DIMENSIONS}")

    connection = connect()
    cursor = connection.cursor()

    cursor.execute("SELECT id, key, value FROM belief")
    beliefs = cursor.fetchall()
    for identifier, key, value in beliefs:
        # The key carries the intent and the value carries the wording. Both go
        # in: searching from the key alone finds documents about the topic,
        # searching from the value alone finds documents about the number.
        text = f"{key.replace('_', ' ')}. {value}"
        cursor.execute(
            "UPDATE belief SET embedding = %s::VECTOR WHERE id = %s",
            (literal(model.encode(text, normalize_embeddings=True).tolist()), identifier),
        )
    print(f"beliefs embedded : {len(beliefs)}")

    cursor.execute("SELECT text FROM demo_query")
    known = {row[0] for row in cursor.fetchall()}
    added = 0
    for question in QUESTIONS:
        if question in known:
            continue
        # backend is NOT NULL on this table and that is the schema being wiser
        # than the first draft of this script, which omitted it and was
        # refused. A vector without the name of the model that made it is a
        # vector nobody can safely compare to anything later.
        cursor.execute(
            "INSERT INTO demo_query (text, embedding, backend) VALUES (%s, %s::VECTOR, %s)",
            (question,
             literal(model.encode(question, normalize_embeddings=True).tolist()),
             BACKEND),
        )
        added += 1
    cursor.execute("SELECT count(*) FROM demo_query")
    print(f"questions added  : {added}")
    print(f"questions total  : {cursor.fetchone()[0]}")

    cursor.execute("SELECT count(*) FROM belief WHERE embedding IS NULL")
    unplaced = cursor.fetchone()[0]
    print(f"beliefs with no vector : {unplaced}")
    return 1 if unplaced else 0


if __name__ == "__main__":
    sys.exit(main())
