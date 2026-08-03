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
import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import boto3
import pg8000.dbapi

MODEL = os.environ.get("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
DIMENSIONS = 1024
COMMIT_EVERY = 25

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


def embed(client, text, attempt=0):
    """One embedding. Retries on throttling, because a 171 row ingest will hit
    it eventually and losing the run at row 140 is annoying."""
    try:
        response = client.invoke_model(
            modelId=MODEL,
            body=json.dumps({
                "inputText": text,
                "dimensions": DIMENSIONS,
                "normalize": True,
            }),
        )
        vector = json.loads(response["body"].read())["embedding"]
        if len(vector) != DIMENSIONS:
            sys.exit(f"expected {DIMENSIONS} dimensions, got {len(vector)}")
        return vector
    except Exception as error:
        name = type(error).__name__
        if attempt < 5 and ("Throttl" in name or "TooManyRequests" in name):
            wait = 2 ** attempt
            print(f"  throttled, waiting {wait}s")
            time.sleep(wait)
            return embed(client, text, attempt + 1)
        raise


def as_literal(vector):
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


def load(reset):
    if not CHUNKS.exists():
        sys.exit(f"{CHUNKS} not found. Run ingest/chunker.py first.")
    rows = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    print(f"{len(rows)} chunks to embed with {MODEL} in {REGION}")

    client = boto3.client("bedrock-runtime", region_name=REGION)
    connection = connect()
    cursor = connection.cursor()

    if reset:
        cursor.execute("DELETE FROM chunk")
        connection.commit()
        print("chunk emptied")

    done = 0
    for row in rows:
        text = f"{row['heading']}\n\n{row['text']}"
        vector = as_literal(embed(client, text))
        cursor.execute(
            """
            INSERT INTO chunk (file, text, embedding, belief_id)
            VALUES (%s, %s, %s::VECTOR(1024),
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


def search(question, limit):
    client = boto3.client("bedrock-runtime", region_name=REGION)
    vector = as_literal(embed(client, question))
    connection = connect()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT c.file,
               left(c.text, 130),
               b.key,
               b.status,
               c.embedding <-> %s::VECTOR(1024) AS distance
        FROM chunk c
        LEFT JOIN belief b ON b.id = c.belief_id
        ORDER BY c.embedding <-> %s::VECTOR(1024)
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
    parser.add_argument("--reset", action="store_true", help="empty chunk first")
    parser.add_argument("--search", metavar="QUESTION")
    parser.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args()

    if arguments.search:
        search(arguments.search, arguments.limit)
    else:
        load(arguments.reset)
