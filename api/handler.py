"""The API behind the demo. One AWS Lambda behind one HTTP API.

It was a Lambda function URL until 2026-08-09, when that URL answered 403 to
every caller on a correct AuthType NONE configuration and CloudWatch showed the
function was never reached. Nothing in this file changed: function URLs and
HTTP APIs deliver the same event, payload format 2.0. See deploy/deploy.sh.

The whole point of the router below: a question like "what is blocking the FEA
run" is STRUCTURAL. It has an exact answer, and that answer is a join. Asking a
similarity engine for it returns FIA regulations -- measured on 2026-08-04.
So structural questions go to SQL and open questions go to the vector index,
and the answer says which road it took.

pg8000 and not psycopg2, on purpose: pure Python, nothing to compile, so the
same file runs in a Lambda zip built on Windows and on the laptop.
"""

import base64
import json
import os
import re
import ssl
import time
import traceback
from urllib.parse import urlparse, unquote

import pg8000.dbapi

# Set on the Lambda, never in the repository. The password does not transit
# through a file that git can see.
CRDB_URL = os.environ.get("CRDB_URL")

# "precomputed" is the default and it is a deliberate limit, not a fallback.
# The 171 chunks were embedded locally in 384 dimensions because Bedrock was
# throttled solid on 2026-08-04. A query vector must live in the same space, so
# free text cannot be embedded here until the corpus is re-embedded with the
# same model as the query. Flipping this to "bedrock" is a one-line change and
# is only correct once the corpus is 1024-dimensional too.
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "precomputed")
BEDROCK_MODEL = os.environ.get("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

CORS = {
    "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
    "Access-Control-Allow-Headers": "content-type",
    # POST is here because the write route only answers to POST. Leave it out
    # and the browser refuses the request at preflight, before the function is
    # ever reached, which looks like a server fault and is not one.
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json; charset=utf-8",
}

_connection = None


def connect():
    """One connection per warm container, reopened when the far end has gone.

    A serverless cluster closes idle connections, and a Lambda that has been
    warm for an hour will meet a dead socket sooner or later. Retrying once on
    a fresh connection is the difference between a demo that works after lunch
    and one that does not.
    """
    global _connection
    if _connection is not None:
        return _connection
    if not CRDB_URL:
        raise RuntimeError("CRDB_URL is not set on the function")
    parsed = urlparse(CRDB_URL)
    _connection = pg8000.dbapi.connect(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=(parsed.path or "/agentmem").lstrip("/").split("?")[0] or "agentmem",
        ssl_context=ssl.create_default_context(),
        application_name="agentmem-demo",
        timeout=10,
    )
    _connection.autocommit = True
    # Once per connection rather than around each risky statement. The function
    # has twenty seconds and a time travel read past the retention window does
    # not fail fast: it retries inside the server for over three seconds before
    # giving up, and a bad offset should not be able to spend the whole budget.
    _connection.cursor().execute("SET statement_timeout = '8s'")
    return _connection


def query(sql, parameters=()):
    global _connection
    for attempt in (1, 2):
        try:
            cursor = connect().cursor()
            cursor.execute(sql, parameters)
            if cursor.description is None:
                return []          # a statement that returns no rows, not a bug
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception:
            if attempt == 2:
                raise
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None


class transaction:
    """Every statement inside, or none of them.

    Closing a belief and opening its successor are one fact about the world,
    not two, and a memory that can hold the first without the second is worse
    than one that refuses both. CockroachDB is serializable by default, so
    there is no isolation level to argue about here -- only the need to take
    autocommit off, which the connection turns on for the read path.
    """

    def __enter__(self):
        self.connection = connect()
        self.connection.autocommit = False
        return self.connection.cursor()

    def __exit__(self, kind, value, trace):
        global _connection
        try:
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            try:
                self.connection.autocommit = True
            except Exception:
                _connection = None
        return False


def serialise(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def clean(rows):
    return [{key: serialise(value) for key, value in row.items()} for row in rows]


# --------------------------------------------------------------------------
# The three structural views. Each one is a join, and each one has an exact
# answer that a similarity search cannot produce.
# --------------------------------------------------------------------------

def view_missing():
    """What can the agent actually run right now, and what stops the rest.

    A requirement counts as satisfied only when a CURRENT belief carries the key
    AND its status is ESTABLISHED. UNDECIDABLE and NOT_FOUND are stored facts,
    not blanks -- which is exactly why they can block a two hour run instead of
    silently passing through it.
    """
    rows = query(
        """
        SELECT c.name        AS computation,
               c.purpose,
               c.cost_note,
               r.belief_key,
               r.criticality,
               r.why,
               b.value       AS known_value,
               b.status      AS known_status
        FROM computation c
        JOIN requirement r ON r.computation_id = c.id
        LEFT JOIN current_belief b ON b.key = r.belief_key
        ORDER BY c.name, r.criticality, r.belief_key
        """
    )
    computations = {}
    for row in rows:
        entry = computations.setdefault(
            row["computation"],
            {
                "computation": row["computation"],
                "purpose": row["purpose"],
                "cost_note": row["cost_note"],
                "blocking_gaps": 0,
                "degrading_gaps": 0,
                "requirements": [],
            },
        )
        satisfied = row["known_status"] == "ESTABLISHED"
        if not satisfied:
            if row["criticality"] == "BLOCKING":
                entry["blocking_gaps"] += 1
            elif row["criticality"] == "DEGRADES":
                entry["degrading_gaps"] += 1
        entry["requirements"].append(
            {
                "key": row["belief_key"],
                "criticality": row["criticality"],
                "why": row["why"],
                "status": row["known_status"] or "ABSENT",
                "value": row["known_value"],
                "satisfied": satisfied,
            }
        )
    result = []
    for entry in computations.values():
        entry["verdict"] = "BLOCKED" if entry["blocking_gaps"] else "CAN RUN"
        result.append(entry)
    # Blocked first, most blocked first: the answer to "what do I fix next".
    result.sort(key=lambda e: (-e["blocking_gaps"], e["computation"]))
    return {"view": "missing", "computations": result}


def view_revisions(limit=25):
    """What changed the agent's mind, and on what evidence."""
    rows = query(
        """
        SELECT n.key,
               o.value           AS believed_before,
               n.value           AS believed_after,
               n.status          AS status_after,
               r.evidence,
               r.evidence_source,
               r.occurred_at
        FROM revision r
        JOIN belief n ON n.id = r.belief_new
        LEFT JOIN belief o ON o.id = r.belief_old
        ORDER BY r.occurred_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return {"view": "revisions", "revisions": clean(rows)}


def view_asof(on):
    """What the memory held on a given day -- including what it held wrongly.

    This is the one an MVCC snapshot cannot answer: the garbage collection
    window is 75 minutes on this cluster, and these revisions are days apart.
    Belief time is data, not storage.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", on or ""):
        return {"error": "on= must be a date, YYYY-MM-DD", "view": "asof"}
    rows = query(
        """
        SELECT key, value, status, source, valid_from, valid_to
        FROM belief
        WHERE valid_from <= %s::TIMESTAMPTZ
          AND (valid_to IS NULL OR valid_to > %s::TIMESTAMPTZ)
        ORDER BY key
        """,
        (on, on),
    )
    revised_since = query(
        """
        SELECT count(*) AS n FROM revision WHERE occurred_at > %s::TIMESTAMPTZ
        """,
        (on,),
    )
    return {
        "view": "asof",
        "on": on,
        "beliefs": clean(rows),
        "revised_since": revised_since[0]["n"],
    }


# The garbage collection window on this cluster, read from the zone config
# rather than assumed: gc.ttlseconds = 4500. It is not configurable on the free
# plan, which is the whole reason this project models history instead of
# reading it back out of storage.
GC_WINDOW_MINUTES = 75

# Past the window a time travel read does not fail quickly. Measured on
# 2026-08-09: -80m returns the GC threshold error at once, but -3h and -24h
# time out instead, and a request that hangs for twenty seconds is a demo a
# judge closes. So the offset is bounded here, before the database is asked.
MAX_TRAVEL_MINUTES = 150


def view_timetravel(minutes=70):
    """Both kinds of history, side by side, on the same instant.

    This is the argument the project is built on, run rather than asserted.
    Storage keeps every version for seventy five minutes and then forgets them
    permanently. The modelled history keeps intervals and evidence for as long
    as the rows exist. Ask both the same question and the difference stops
    being a paragraph in a README.
    """
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return {"view": "timetravel", "error": "minutes must be a whole number"}
    minutes = max(1, min(minutes, MAX_TRAVEL_MINUTES))
    instant = f"-{minutes}m"

    started = time.time()
    storage = {"offset": instant, "within_window": minutes <= GC_WINDOW_MINUTES}
    try:
        rows = query(
            # No placeholder: AS OF SYSTEM TIME takes a constant, and the value
            # is built from an integer this function has already bounded.
            f"SELECT count(*) AS n FROM belief AS OF SYSTEM TIME '{instant}'"
        )
        storage["answered"] = True
        storage["beliefs"] = rows[0]["n"]
    except Exception as error:
        detail = str(error)
        storage["answered"] = False
        storage["refused_with"] = (
            "the read timed out" if "timed out" in detail.lower()
            else "batch timestamp must be after replica GC threshold")
        storage["why"] = (
            f"Storage keeps {GC_WINDOW_MINUTES} minutes of versions on this "
            "plan and gc.ttlseconds is not configurable here. Older versions "
            "are not slow to reach, they are gone.")
    # Reported because it is part of the answer: a read inside the window costs
    # the same as any other read, and a read past it spends three seconds
    # retrying before admitting the versions are gone. The refusal is the slow
    # path, not the time travel.
    storage["took_ms"] = int((time.time() - started) * 1000)

    # The same instant, asked of the modelled history. Belief time is data, so
    # there is no window and no configuration involved.
    modelled = query(
        """
        SELECT count(*) AS n FROM belief
        WHERE valid_from <= now() - %s::INTERVAL
          AND (valid_to IS NULL OR valid_to > now() - %s::INTERVAL)
        """,
        (instant.lstrip("-"), instant.lstrip("-")),
    )[0]["n"]

    # And a date storage cannot reach at all, which is the point. The oldest
    # revision in this memory is weeks old; the storage layer's memory begins
    # seventy five minutes ago.
    oldest = query("SELECT min(occurred_at) AS first FROM revision")[0]["first"]
    far = query(
        """
        SELECT count(*) AS n FROM belief
        WHERE valid_from <= %s::TIMESTAMPTZ
          AND (valid_to IS NULL OR valid_to > %s::TIMESTAMPTZ)
        """,
        (oldest, oldest),
    )[0]["n"]

    return {
        "view": "timetravel",
        "gc_window_minutes": GC_WINDOW_MINUTES,
        "storage": storage,
        "modelled": {"offset": instant, "beliefs": modelled},
        "beyond_storage": {
            "on": serialise(oldest),
            "beliefs": far,
            "note": ("The oldest revision in this memory. Storage cannot be "
                     "asked about this instant at any price on this plan, and "
                     "the modelled history answers it the same way it answers "
                     "about ten minutes ago."),
        },
    }


def view_unblock(name=None):
    """What has to be known before a computation can run, and where to read it.

    This is the join the project existed to make and did not make for a week.
    One half of it answers "what is missing" structurally, over computation,
    requirement and belief. The other half answers an open question by vector
    search. Between them sits the question an engineer actually asks -- what do
    I need to know, and where do I read it -- and answering it means crossing
    from the structural side to the semantic one in a single query: take the
    requirements that are not satisfied, take the belief behind each, and
    search the corpus from where that belief sits.

    The LATERAL is what makes it one query rather than one per gap. There are
    171 chunks, so the scan is free and the vector index is not needed here;
    the index earns its place on the open-question path, where the corpus is
    searched from an arbitrary point.
    """
    rows = query(
        """
        SELECT c.name        AS computation,
               c.purpose,
               c.cost_note,
               r.belief_key,
               r.criticality,
               r.why,
               b.value        AS known_value,
               b.status       AS known_status,
               near.file,
               near.text,
               near.distance
        FROM computation c
        JOIN requirement r ON r.computation_id = c.id
        LEFT JOIN current_belief b ON b.key = r.belief_key
        LEFT JOIN LATERAL (
            -- Truncated here rather than in Python. Profiled on 2026-08-09:
            -- the same join without the text came back in 593 ms and with it
            -- in 1750 ms, so a thousand milliseconds were whole chunks
            -- crossing the wire to be cut on arrival. That measurement was
            -- taken from China, where the round trip alone is 273 ms; the
            -- function runs in the cluster's own region and sees far less.
            -- Shipping less is free either way.
            SELECT ch.file, left(ch.text, 340) AS text,
                   ch.embedding <-> b.embedding AS distance
            FROM chunk ch
            WHERE b.embedding IS NOT NULL
            ORDER BY ch.embedding <-> b.embedding
            LIMIT 3
        ) near ON true
        WHERE b.status IS DISTINCT FROM 'ESTABLISHED'
          -- Cast, because a bare placeholder in IS NULL has no type to infer
          -- from and the planner says so rather than guessing.
          AND (%s::STRING IS NULL OR c.name = %s::STRING)
        ORDER BY c.name, r.criticality, r.belief_key, near.distance
        """,
        (name, name),
    )

    computations = {}
    for row in rows:
        entry = computations.setdefault(row["computation"], {
            "computation": row["computation"],
            "purpose": row["purpose"],
            "cost_note": row["cost_note"],
            "gaps": {},
        })
        gap = entry["gaps"].setdefault(row["belief_key"], {
            "key": row["belief_key"],
            "criticality": row["criticality"],
            "why": row["why"],
            "status": row["known_status"] or "ABSENT",
            "value": row["known_value"],
            "read": [],
        })
        if row["distance"] is None:
            continue
        distance = float(row["distance"])
        if distance <= NEAR_ENOUGH:
            gap["read"].append({
                "file": row["file"],
                "text": row["text"],
                "distance": round(distance, 3),
                # Cosine, because a reader can put a number on it. For unit
                # vectors d^2 = 2 - 2cos, and orthogonal is 1.414, not 1.
                "similarity": round(1 - distance * distance / 2, 2),
            })

    result = []
    for entry in computations.values():
        gaps = list(entry["gaps"].values())
        for gap in gaps:
            if not gap["read"]:
                # Saying the notes are silent is the answer, not the absence of
                # one. Showing three weak passages instead would be the thing
                # this whole project is against.
                gap["note"] = ("Nothing in the indexed notes comes closer than "
                               f"{NEAR_ENOUGH} to this belief, which is barely "
                               "better than the corpus average. This is a gap "
                               "with no reading behind it.")
        entry["gaps"] = sorted(gaps, key=lambda g: (g["criticality"] != "BLOCKING",
                                                    g["key"]))
        entry["blocking_gaps"] = sum(1 for g in gaps if g["criticality"] == "BLOCKING")
        entry["verdict"] = "BLOCKED" if entry["blocking_gaps"] else "DEGRADED"
        entry["passages"] = sum(len(g["read"]) for g in gaps)
        result.append(entry)

    result.sort(key=lambda e: (-e["blocking_gaps"], e["computation"]))
    return {"view": "unblock", "computations": result, "threshold": NEAR_ENOUGH}


# --------------------------------------------------------------------------
# The semantic road.
# --------------------------------------------------------------------------

def embed(text):
    """Return a query vector, or None with a reason the caller must show.

    No silent fallback. If the configured backend cannot answer, the API says
    so and the page says so -- a memory whose whole argument is that it names
    what it does not know does not get to hide a missing embedder.
    """
    if EMBED_BACKEND == "bedrock":
        import boto3

        client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        response = client.invoke_model(
            modelId=BEDROCK_MODEL,
            body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
        )
        return json.loads(response["body"].read())["embedding"], None

    rows = query(
        "SELECT embedding::STRING AS embedding FROM demo_query WHERE text = %s",
        (text.strip(),),
    )
    if rows:
        return json.loads(rows[0]["embedding"]), None
    return None, (
        "This deployment cannot embed new text. The corpus was embedded with a "
        "local multilingual model because Bedrock was throttled to zero on a "
        "one day old account; a query vector has to live in the same space as "
        "the corpus. The questions listed below are embedded and stored, and "
        "they search the vector index for real."
    )


def view_search(question, limit=5):
    vector, reason = embed(question)
    if vector is None:
        suggestions = query("SELECT text FROM demo_query ORDER BY text")
        return {
            "view": "search",
            "question": question,
            "status": "NO_EMBEDDER",
            "reason": reason,
            "embedded_questions": [row["text"] for row in suggestions],
        }
    literal = "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
    rows = query(
        """
        SELECT c.file,
               c.text,
               b.key    AS belief_key,
               b.status AS belief_status,
               b.value  AS belief_value,
               c.embedding <-> %s::VECTOR AS distance
        FROM chunk c
        LEFT JOIN belief b ON b.id = c.belief_id
        ORDER BY c.embedding <-> %s::VECTOR
        LIMIT %s
        """,
        (literal, literal, limit),
    )
    for row in rows:
        row["distance"] = round(float(row["distance"]), 4)
        row["text"] = row["text"][:400]
    return {"view": "search", "question": question, "status": "OK", "hits": clean(rows)}


# --------------------------------------------------------------------------
# The write path. An agent that can only read is a search box.
#
# What makes this one worth building is not that it writes -- anything can
# write -- but that it has three answers and only one of them is a write. A
# memory whose whole argument is that it stores what it does not know does not
# get to accept every claim it is handed.
#
#   REVISE        the claim settles a belief that was open, or contradicts one
#                 that was held. Closing and opening happen in one transaction.
#   NO CHANGE     the claim agrees with what is already held. Nothing is
#                 written, and saying so is the useful answer.
#   INSUFFICIENT  the claim reaches a belief but does not settle it, or reaches
#                 nothing at all. The agent says what it would need.
# --------------------------------------------------------------------------

# The grammar is declared, not inferred, and that is a rule this project
# learned the expensive way: a first attempt at reading intent out of prose
# produced four false positives out of four, including on the value that was
# correct. So a claim announces its own parts.
#
#     <subject> is <value> because <evidence>
#
# Anything that does not parse is reported as unparsed, with the shape it
# wanted. Guessing would be worse than refusing.
CLAIM = re.compile(r"^(?P<subject>.+?)\s+is\s+(?P<value>.+?)\s+because\s+(?P<evidence>.+)$",
                   re.I | re.S)

# A visitor row lives a day. Long enough that a judge can come back to it,
# short enough that the demo repairs itself without anyone on call.
VISITOR_TTL = "24h"
VISITOR_SOURCE = "demo visitor"

# One stranger with a loop should not be able to grow the table without bound.
VISITOR_CEILING = 200

STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "of", "for", "to",
             "in", "on", "at", "and", "or", "it", "its", "this", "that", "be"}

# How close a passage has to be to a belief before it is worth reading.
#
# Measured rather than chosen. A belief compared to all 171 chunks sits at a
# mean distance of 1.169 with a standard deviation of 0.090, so 0.99 is two
# standard deviations better than the corpus average. For unit vectors the
# scale runs 0 to 2 and orthogonal is 1.414, not 1 -- which is worth stating,
# because reading 1.0 as "unrelated" made a first look at these numbers
# conclude there was no signal when the retrieval was in fact the strongest in
# the project.
NEAR_ENOUGH = 0.99


def tokens(text):
    """Words worth matching a KEY on. Not usable to compare two values.

    The short-word filter is what makes key matching work and what makes value
    comparison fail: tokens("14.00 mm") is the empty set, because 14, 00 and mm
    are all two characters or fewer. Both sides of a comparison then came out
    empty and equal-looking, and the agent proposed revising 14.00 mm to
    14.00 mm. Measured on 2026-08-09, on the first run. Values go through
    same_value below.
    """
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOPWORDS}


def same_value(one, other):
    """Whether two stated values say the same thing.

    Deliberately literal: punctuation and spacing are ignored, 14.00 and 14 are
    not the same string and are not treated as one. A memory that quietly
    decides two numbers are close enough is a memory that stops being citable.
    """
    def flatten(value):
        return re.sub(r"[^a-z0-9.]+", " ", (value or "").lower()).strip()
    return flatten(one) == flatten(other)


def match_belief(subject):
    """Pick the belief a claim is about, and show the arithmetic that picked it.

    Lexical rather than semantic, on purpose. Free text cannot be embedded on
    this deployment -- see embed() -- and a scoring rule a judge can recompute
    by hand is worth more here than a similarity a judge has to trust. The
    score is returned with the answer for exactly that reason.
    """
    wanted = tokens(subject)
    if not wanted:
        return None, []
    ranked = []
    for row in query("SELECT id, key, value, status, source FROM current_belief"):
        # The key carries the intent (hub_barrel_architecture), the value
        # carries the wording someone might quote back. Both count, the key
        # more, because a value can be long enough to match by accident.
        key_hits = len(wanted & tokens(row["key"].replace("_", " ")))
        value_hits = len(wanted & tokens(row["value"]))
        score = key_hits * 3 + value_hits
        if score:
            ranked.append(dict(row, score=score, key_hits=key_hits))
    ranked.sort(key=lambda r: (-r["score"], r["key"]))
    if not ranked:
        return None, []
    best = ranked[0]
    # A claim that touches nothing but a couple of common words is not about
    # this belief, it is about the vocabulary. Require the key itself to land.
    if best["key_hits"] == 0:
        return None, ranked[:3]
    return best, ranked[:3]


def view_propose(claim):
    """Decide, and write nothing. Same code path the commit runs first."""
    claim = (claim or "").strip()
    if not claim:
        return {"view": "propose", "decision": "INSUFFICIENT",
                "reason": "No claim given.",
                "wanted_shape": "<subject> is <value> because <evidence>"}

    parsed = CLAIM.match(claim)
    if not parsed:
        return {
            "view": "propose", "decision": "INSUFFICIENT", "claim": claim,
            "reason": ("That claim does not declare its parts, and this agent "
                       "does not infer them. Reading intent out of prose is "
                       "how the memory got four facts wrong in one pass."),
            "wanted_shape": "<subject> is <value> because <evidence>",
            "example": ("hub barrel architecture is B because the mass study "
                        "closed the 1.7 kg gap"),
        }

    subject = parsed.group("subject").strip()
    value = parsed.group("value").strip()
    evidence = parsed.group("evidence").strip()
    target, considered = match_belief(subject)

    shortlist = [{"key": r["key"], "score": r["score"], "status": r["status"]}
                 for r in considered]

    if target is None:
        return {
            "view": "propose", "decision": "INSUFFICIENT", "claim": claim,
            "parsed": {"subject": subject, "value": value, "evidence": evidence},
            "reason": ("No belief in this memory is about that. The agent will "
                       "not open a new key on a stranger's say-so: an unasked "
                       "belief is how a memory fills up with things nobody "
                       "checked."),
            "considered": shortlist,
        }

    decision = "REVISE"
    why = None
    if same_value(value, target["value"]):
        decision = "NO CHANGE"
        why = "The memory already holds this, and holds it for a stated reason."
    elif len(tokens(evidence)) < 3:
        decision = "INSUFFICIENT"
        why = ("The evidence is too thin to close a belief. Name what was "
               "measured, read or decided, not that it changed.")

    return {
        "view": "propose",
        "decision": decision,
        "claim": claim,
        "parsed": {"subject": subject, "value": value, "evidence": evidence},
        "reason": why,
        "target": {"id": str(target["id"]), "key": target["key"],
                   "value": target["value"], "status": target["status"],
                   "source": target["source"], "match_score": target["score"]},
        "considered": shortlist,
        "would_write": None if decision != "REVISE" else {
            "close": target["key"],
            "open": {"key": target["key"], "value": value,
                     "status": "ESTABLISHED", "source": VISITOR_SOURCE},
            "revision_evidence": evidence,
            "expires_in": VISITOR_TTL,
        },
    }


def view_commit(claim):
    """Write it, or explain why not. The decision is recomputed here.

    Never trusts a decision handed in by the caller: propose is advisory and
    the client can say anything. The only decision that governs a write is the
    one this function makes on the claim it was given.
    """
    proposal = view_propose(claim)
    proposal["view"] = "commit"
    if proposal["decision"] != "REVISE":
        proposal["written"] = False
        return proposal

    ceiling = query("SELECT count(*) AS n FROM belief WHERE expires_at IS NOT NULL")
    if ceiling[0]["n"] >= VISITOR_CEILING:
        proposal["decision"] = "REFUSED"
        proposal["written"] = False
        proposal["reason"] = (
            f"{VISITOR_CEILING} visitor beliefs are already live. The sweeper "
            "clears them within the hour; the memory would rather refuse a "
            "write than grow without a bound.")
        return proposal

    before = {c["computation"]: c for c in view_missing()["computations"]}
    target = proposal["target"]
    parsed = proposal["parsed"]

    # The old belief is NOT closed. Closing it would be a mutation of somebody
    # else's row that no expiry can undo -- see sql/migration_002. The new row
    # simply becomes the most recent one, and stops being that when it expires.
    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO belief (key, value, status, source, valid_from, expires_at)
            VALUES (%s, %s, 'ESTABLISHED', %s, now(), now() + %s::INTERVAL)
            RETURNING id
            """,
            (target["key"], parsed["value"], VISITOR_SOURCE, VISITOR_TTL),
        )
        new_id = cursor.fetchone()[0]
        # The superseded belief is named by the id the proposal matched, not
        # looked up again here. Re-reading current_belief at this point returns
        # the row just inserted -- the view is DISTINCT ON (key) and the new
        # row is now the most recent -- so a lookup found nothing, the INSERT
        # ... SELECT matched zero rows, and the revision was silently not
        # written while the belief was. Measured on 2026-08-09: revisions
        # stayed at 14 through a commit that reported success.
        cursor.execute(
            """
            INSERT INTO revision (belief_old, belief_new, occurred_at,
                                  evidence, evidence_source, expires_at)
            VALUES (%s, %s, now(), %s, %s, now() + %s::INTERVAL)
            """,
            (target["id"], new_id, parsed["evidence"], VISITOR_SOURCE,
             VISITOR_TTL),
        )

    after = {c["computation"]: c for c in view_missing()["computations"]}
    # The point of the whole exercise: one sentence, and a two hour computation
    # changes state. Only the computations that actually moved are reported.
    moved = []
    for name, now_state in after.items():
        was = before.get(name)
        if was and (was["verdict"] != now_state["verdict"]
                    or was["blocking_gaps"] != now_state["blocking_gaps"]):
            moved.append({
                "computation": name,
                "from": f"{was['verdict']} ({was['blocking_gaps']} blocking)",
                "to": f"{now_state['verdict']} ({now_state['blocking_gaps']} blocking)",
                "cost_note": now_state["cost_note"],
            })

    proposal["written"] = True
    proposal["belief_id"] = str(new_id)
    proposal["expires_in"] = VISITOR_TTL
    proposal["unblocked"] = moved
    return proposal


# --------------------------------------------------------------------------
# The router. Structural first, semantic as the default.
# --------------------------------------------------------------------------

STRUCTURAL = [
    # First because it is the most specific, and because "remember" would
    # otherwise be read as a question about beliefs rather than about storage.
    ("timetravel", re.compile(
        r"\b(storage (still )?remember|time travel|how far back|"
        r"as of system time|mvcc|garbage collect\w*|retention)\b", re.I)),
    # Ordered, and the order is the point. "what do I need to know to unblock
    # the FEA run" and "what is blocking the FEA run" are different questions:
    # the first asks for the reading, the second for the state. Tested first so
    # the more specific one wins, because "unblock" appears in both.
    ("unblock", re.compile(
        r"\b(need to know|what should i read|where do i read|where is it "
        r"written|how do i unblock|unblock|what would settle|"
        r"what do i read)\b", re.I)),
    ("missing", re.compile(
        r"\b(missing|blocking|blocked|can .*run|what stops|gap|gaps|"
        r"ready to run|gate)\b", re.I)),
    ("revisions", re.compile(
        r"\b(chang\w* (my|its|his|her|their) mind|revision|revised|"
        r"what did i learn|correct\w*|got it wrong|used to think)\b", re.I)),
]
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
BELIEF_ON = re.compile(r"\b(believ\w*|know\w*|think\w*|hold\w*)\b", re.I)


def route(question):
    """Classify, and report the classification. The demo shows this line: a
    router the judge cannot see is a router the judge cannot trust."""
    date = DATE.search(question)
    if date and BELIEF_ON.search(question):
        return "asof", {"on": date.group(1)}
    for view, pattern in STRUCTURAL:
        if pattern.search(question):
            return view, {}
    return "search", {}


def view_ask(question):
    view, arguments = route(question)
    if view == "missing":
        payload = view_missing()
    elif view == "timetravel":
        # A number in the question is the offset to travel to, so "what did
        # storage remember 90 minutes ago" asks past the window on purpose.
        asked = re.search(r"\b(\d{1,3})\s*(?:m|min|minutes?)\b", question, re.I)
        payload = view_timetravel(int(asked.group(1)) if asked else 70)
    elif view == "unblock":
        # A computation named in the question narrows it; otherwise every
        # blocked one is answered, which is the useful default on a Monday.
        named = re.search(r"\b(fea_run|bolt_check|scrub_recompute|"
                          r"rod_end_boss_sizing|unsprung_mass_budget|"
                          r"fatigue_check_parent|fatigue_check_welded)\b",
                          question, re.I)
        if not named and re.search(r"\bfea\b|finite element", question, re.I):
            payload = view_unblock("fea_run")
        else:
            payload = view_unblock(named.group(1).lower() if named else None)
    elif view == "revisions":
        payload = view_revisions()
    elif view == "asof":
        payload = view_asof(arguments["on"])
    else:
        payload = view_search(question)
    payload["route"] = "semantic" if view == "search" else "structural"
    payload["question"] = question
    return payload


def view_health():
    """Enough to tell a broken deployment from an empty one, in one call."""
    counts = query(
        """
        SELECT (SELECT count(*) FROM belief)      AS beliefs,
               (SELECT count(*) FROM current_belief) AS current_beliefs,
               (SELECT count(*) FROM revision)    AS revisions,
               (SELECT count(*) FROM chunk)       AS chunks,
               (SELECT count(*) FROM computation) AS computations,
               (SELECT count(*) FROM requirement) AS requirements,
               (SELECT count(*) FROM belief WHERE expires_at IS NOT NULL) AS visitor_beliefs,
               version()                          AS server
        """
    )[0]
    counts["embed_backend"] = EMBED_BACKEND
    return {"view": "health", "status": "OK", "database": clean([counts])[0]}


ROUTES = {
    "health": lambda p: view_health(),
    "missing": lambda p: view_missing(),
    "unblock": lambda p: view_unblock(p.get("computation")),
    "revisions": lambda p: view_revisions(),
    "asof": lambda p: view_asof(p.get("on")),
    "timetravel": lambda p: view_timetravel(p.get("minutes", 70)),
    "search": lambda p: view_search(p.get("q", "")),
    "ask": lambda p: view_ask(p.get("q", "")),
    "propose": lambda p: view_propose(p.get("claim", "")),
    "commit": lambda p: view_commit(p.get("claim", "")),
}

# The one route that changes the database. Kept in a set rather than sniffed
# from the name, so that adding a writer later is a deliberate edit here.
WRITES = {"commit"}


def respond(status, body, started):
    body["elapsed_ms"] = int((time.time() - started) * 1000)
    return {
        "statusCode": status,
        "headers": CORS,
        "body": json.dumps(body, ensure_ascii=False, default=serialise),
    }


def lambda_handler(event, context):
    started = time.time()
    parameters = event.get("queryStringParameters") or {}
    method = (event.get("requestContext", {})
                   .get("http", {})
                   .get("method", "GET"))
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS, "body": ""}

    # A POST carries its parameters in the body. Merged under the query string
    # so a caller cannot smuggle a different view past the check below by
    # putting one in each place.
    if method == "POST" and event.get("body"):
        body = event["body"]
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "replace")
        try:
            posted = json.loads(body)
            if isinstance(posted, dict):
                parameters = {**{k: str(v) for k, v in posted.items()},
                              **parameters}
        except ValueError:
            return respond(400, {"error": "body is not JSON"}, started)

    view = parameters.get("view", "health")
    handler = ROUTES.get(view)
    if handler is None:
        return respond(400, {"error": f"unknown view '{view}'",
                             "views": sorted(ROUTES)}, started)

    # The route that writes refuses to be a GET, and this is not ceremony.
    # A GET is fetched by things that were never asked to: browser prefetch,
    # link preview in a chat client, any crawler that finds the URL. A demo
    # that writes on GET has a database written to by software, at a rate
    # nobody chose, from a link somebody pasted once.
    if view in WRITES and method != "POST":
        return respond(405, {
            "error": "method not allowed",
            "view": view,
            "detail": ("This route writes, so it is POST only. A GET would be "
                       "followed by prefetchers, link previews and crawlers, "
                       "none of which meant to change anything."),
            "how": 'POST {"view": "commit", "claim": "<subject> is <value> because <evidence>"}',
        }, started)
    try:
        payload = handler(parameters)
        # One structured line per request. CloudWatch turns it into a table,
        # and it is the only observability this thing needs.
        print(json.dumps({
            "view": view,
            "ms": int((time.time() - started) * 1000),
            "request_id": getattr(context, "aws_request_id", None),
        }))
        # A view that reports a bad argument was answering, not failing, and
        # the status code should say which. It used to return 200 with an
        # error field, and the page then told the visitor the API had not
        # answered -- blaming the server for a mistyped date.
        return respond(400 if "error" in payload else 200, payload, started)
    except Exception as error:
        print(json.dumps({
            "view": view,
            "error": type(error).__name__,
            "detail": str(error)[:400],
            "trace": traceback.format_exc()[-1200:],
            "request_id": getattr(context, "aws_request_id", None),
        }))
        # The client is told what failed, never how the database is addressed.
        return respond(500, {"error": type(error).__name__, "view": view}, started)
