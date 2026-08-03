"""Embed the chunks with Amazon Bedrock and load them into CockroachDB.

Runs where AWS credentials live. In AWS CloudShell that is out of the box:

    git clone https://github.com/Outsider33/Hackathon-Cockroach-DB-x-AWS.git
    cd Hackathon-Cockroach-DB-x-AWS
    pip install --quiet pg8000
    export CRDB_URL='postgresql://...'
    python3 ingest/embed_and_load.py --reset
    python3 ingest/embed_and_load.py --search "why did the part get thicker"

pg8000 and not psycopg2 on purpose: pure Python, nothing to compile, so the same
script runs in CloudShell, in a Lambda zip, and on a Windows laptop.

Vectors are inserted one row at a time. The documentation says explicitly to
avoid large batches of VECTOR inserts, so this commits every 25 rows instead of
building one big statement.
"""

import argparse
import io
import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

# The console on the development machine is GBK. The corpus contains emoji, so
# without this the script dies on the first result it tries to print, after the
# work is already done.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pg8000.dbapi


def load_dotenv():
    """Read .env if it is there. Without this the file sits next to the script
    being quietly ignored, which is worse than not having it."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()

MODEL = os.environ.get("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
# us-east-1 was throttled solid on 2026-08-04. us-west-2, eu-west-3 and
# ap-northeast-1 answered once and then throttled too, for the account root as
# well as for a scoped IAM user. Bedrock capacity is per region and per model.
REGION = os.environ.get("AWS_REGION", "us-west-2")
COMMIT_EVERY = 25

# Two backends, same interface, because the first one was not available when it
# was needed. Dimensions differ, so the chunk table is created to match.
BACKENDS = {
    "bedrock": {"dimensions": 1024, "label": MODEL},
    "local": {"dimensions": 384, "label": "paraphrase-multilingual-MiniLM-L12-v2"},
}

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks.jsonl"


def connect():
    url = os.environ.get("CRDB_URL")
    if not url:
        sys.exit("CRDB_URL is not set. It never goes in a file that git tracks.")
    parsed = urlparse(url)
    return pg8000.dbapi.connect(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=(parsed.path or "/agentmem").lstrip("/").split("?")[0] or "agentmem",
        ssl_context=ssl.create_default_context(),
    )


class Bedrock:
    """Amazon Bedrock, Titan Text Embeddings V2.

    Left in place and unused as of 2026-08-04. The account is on the default
    quota, which the documentation says depends on payment history, and a one
    day old account sits at the floor. Both the account root and a scoped IAM
    user got ThrottlingException, in four regions, over more than an hour.
    The model offers the Standard tier only, so there is no throughput to buy,
    and it supports neither geo nor global cross-region inference.
    """

    def __init__(self):
        import boto3  # imported here so the local backend needs no AWS at all
        self.client = boto3.client("bedrock-runtime", region_name=REGION)
        self.dimensions = BACKENDS["bedrock"]["dimensions"]

    def __call__(self, text, attempt=0):
        try:
            response = self.client.invoke_model(
                modelId=MODEL,
                body=json.dumps({
                    "inputText": text,
                    "dimensions": self.dimensions,
                    "normalize": True,
                }),
            )
            vector = json.loads(response["body"].read())["embedding"]
            if len(vector) != self.dimensions:
                sys.exit(f"expected {self.dimensions} dimensions, got {len(vector)}")
            return vector
        except Exception as error:
            name = type(error).__name__
            if attempt < 5 and ("Throttl" in name or "TooManyRequests" in name):
                wait = 2 ** attempt
                print(f"  throttled, waiting {wait}s")
                time.sleep(wait)
                return self(text, attempt + 1)
            raise


class Local:
    """A multilingual sentence transformer, on the CPU.

    Chosen because the corpus is in French and because it needs no network at
    all: the model is already in the local cache, which matters on a connection
    that goes through a VPN.
    """

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.dimensions = BACKENDS["local"]["dimensions"]
        self.model = SentenceTransformer(
            f"sentence-transformers/{BACKENDS['local']['label']}"
        )

    def __call__(self, text):
        vector = self.model.encode(text, normalize_embeddings=True)
        if len(vector) != self.dimensions:
            sys.exit(f"expected {self.dimensions} dimensions, got {len(vector)}")
        return vector.tolist()


def make_embedder(backend):
    return {"bedrock": Bedrock, "local": Local}[backend]()


def recreate_chunk_table(cursor, dimensions):
    """The vector index has to exist before the rows do, so the table is dropped
    and rebuilt rather than emptied. Declaring the index inline is what makes it
    impossible to build on a populated table."""
    cursor.execute("DROP TABLE IF EXISTS chunk")
    cursor.execute(f"""
        CREATE TABLE chunk (
          id        UUID   DEFAULT gen_random_uuid() PRIMARY KEY,
          file      STRING NOT NULL,
          text      STRING NOT NULL,
          embedding VECTOR({dimensions}),
          belief_id UUID REFERENCES belief(id),
          VECTOR INDEX chunk_emb (embedding)
        )
    """)


def as_literal(vector):
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


def load(backend):
    if not CHUNKS.exists():
        sys.exit(f"{CHUNKS} not found. Run ingest/chunker.py first.")
    rows = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    embedder = make_embedder(backend)
    print(f"{len(rows)} chunks, {backend} backend, "
          f"{BACKENDS[backend]['label']}, {embedder.dimensions} dimensions")

    connection = connect()
    cursor = connection.cursor()
    recreate_chunk_table(cursor, embedder.dimensions)
    connection.commit()

    done = 0
    for row in rows:
        text = f"{row['heading']}\n\n{row['text']}"
        vector = as_literal(embedder(text))
        cursor.execute(
            f"""
            INSERT INTO chunk (file, text, embedding, belief_id)
            VALUES (%s, %s, %s::VECTOR({embedder.dimensions}),
                    (SELECT id FROM belief
                      WHERE key = %s AND valid_to IS NULL LIMIT 1))
            """,
            (row["file"], text, vector, row["belief_key"]),
        )
        done += 1
        if done % COMMIT_EVERY == 0:
            connection.commit()
            print(f"  {done}/{len(rows)}")
    connection.commit()

    cursor.execute("SELECT count(*), count(belief_id) FROM chunk")
    total, anchored = cursor.fetchone()
    print(f"loaded {total} chunks, {anchored} of them anchored to a belief")
    connection.close()


def search(question, limit, backend):
    embedder = make_embedder(backend)
    vector = as_literal(embedder(question))
    connection = connect()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT c.file,
               left(c.text, 130),
               b.key,
               b.status,
               c.embedding <-> %s::VECTOR({embedder.dimensions}) AS distance
        FROM chunk c
        LEFT JOIN belief b ON b.id = c.belief_id
        ORDER BY c.embedding <-> %s::VECTOR({embedder.dimensions})
        LIMIT %s
        """,
        (vector, vector, limit),
    )
    print(f"\n{question}\n")
    for file, snippet, key, status, distance in cursor.fetchall():
        flag = f"  [{key} = {status}]" if key else ""
        print(f"{distance:.4f}  {file}{flag}")
        print(f"        {snippet.strip()[:130]}...".replace("\n", " "))
    connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=list(BACKENDS), default="local",
                        help="local needs no network, bedrock needs quota")
    parser.add_argument("--search", metavar="QUESTION")
    parser.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args()

    if arguments.search:
        search(arguments.search, arguments.limit, arguments.backend)
    else:
        load(arguments.backend)
