"""What the agent decides, what it writes, and what it refuses to do.

    python3 tests/test_agent.py

Runs against the real cluster, because the thing under test is the interaction
between a decision and a bitemporal schema, and a fake would only prove the
fake. It writes, checks, and removes what it wrote; the counts are asserted
back to their starting values at the end, so a run that dies half way is
visible rather than silent.

Every case here exists because something was wrong. Three of them were found by
hand on 2026-08-09, after the code reported success:

  - the agent proposed revising 14.00 mm to 14.00 mm, because value comparison
    borrowed a tokeniser built for keys and both sides came out empty
  - the revision row was never inserted, while the belief was and the commit
    reported success
  - a GET could write, which is a thing browsers and crawlers do on their own

A hand check that is not in a file is a hand check that happens once.
"""

import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    path = ROOT / ".env"
    if not path.exists():
        sys.exit(".env not found. CRDB_URL never goes in a tracked file.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env()
sys.path.insert(0, str(ROOT / "api"))
import handler  # noqa: E402  -- after the environment is populated


PASSED, FAILED = [], []


def check(name, got, expected):
    if got == expected:
        PASSED.append(name)
        print(f"  ok    {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}\n          expected {expected!r}\n          got      {got!r}")


def counts():
    row = handler.view_health()["database"]
    return {k: row[k] for k in ("beliefs", "current_beliefs", "revisions",
                                "visitor_beliefs")}


def verdict_of(name):
    for computation in handler.view_missing()["computations"]:
        if computation["computation"] == name:
            return computation["verdict"], computation["blocking_gaps"]
    return None, None


def purge():
    """Everything a visitor wrote. The cascade takes the revisions with it."""
    handler.query("DELETE FROM belief WHERE source = %s", (handler.VISITOR_SOURCE,))


# ---------------------------------------------------------------- decisions --

print("\ndecisions")

check("prose that declares nothing is refused",
      handler.view_propose("I think the hub barrel should probably be B")["decision"],
      "INSUFFICIENT")

check("a subject the memory never held is refused",
      handler.view_propose("the coffee machine is broken because nobody cleaned it")["decision"],
      "INSUFFICIENT")

check("thin evidence is refused",
      handler.view_propose("hub barrel architecture is B because yes")["decision"],
      "INSUFFICIENT")

# The one that caught the tokeniser. 14.00 mm is what the memory holds; every
# token in it is two characters or fewer, so a token-set comparison sees two
# empty sets and calls them different.
check("a value the memory already holds is NO CHANGE",
      handler.view_propose(
          "part thickness is 14.00 mm because the tensor fatigue run measured it"
      )["decision"],
      "NO CHANGE")

check("a different value on a held belief is REVISE",
      handler.view_propose(
          "part thickness is 15.20 mm because a thicker web was chosen"
      )["decision"],
      "REVISE")

check("an open belief with real evidence is REVISE",
      handler.view_propose(
          "hub barrel architecture is B because the mass study closed the 1.7 kg gap"
      )["decision"],
      "REVISE")

print("\nproposing writes nothing")
before = counts()
handler.view_propose("hub barrel architecture is B because the mass study closed the 1.7 kg gap")
check("counts unchanged after a proposal", counts(), before)

# ------------------------------------------------------------------- values --

print("\nvalue comparison")
check("14.00 mm equals 14.00 mm", handler.same_value("14.00 mm", "14.00 mm"), True)
check("14.00 mm is not 14 mm", handler.same_value("14.00 mm", "14 mm"), False)
check("punctuation and case are ignored",
      handler.same_value("B -- chosen", "b   chosen"), True)
check("tokens() is empty on a bare measurement",
      handler.tokens("14.00 mm"), set())

# ------------------------------------------------------------------ writing --

print("\nwriting")
purge()
start = counts()
was_verdict, was_gaps = verdict_of("fea_run")

result = handler.view_commit(
    "hub barrel architecture is B because the mass study closed the 1.7 kg gap")

check("the commit reports a write", result["written"], True)

after = counts()
check("one belief was added", after["beliefs"], start["beliefs"] + 1)
# The one that caught the silent INSERT ... SELECT: the belief was written and
# the revision was not, and the commit said it had succeeded.
check("one revision was added", after["revisions"], start["revisions"] + 1)
check("it is counted as a visitor row", after["visitor_beliefs"], 1)
# A visitor supersedes rather than adds: the engineer's row is untouched and
# still open, so the number of current beliefs cannot move.
check("current beliefs did not grow", after["current_beliefs"], start["current_beliefs"])

rows = handler.query(
    "SELECT count(*) AS n FROM belief WHERE key = %s AND valid_to IS NULL",
    ("hub_barrel_architecture",))
check("the engineer's row is still open", rows[0]["n"], 2)

newest = handler.view_revisions(1)["revisions"][0]
check("the revision names the belief it replaced",
      newest["key"], "hub_barrel_architecture")
check("the revision records who wrote it",
      newest["evidence_source"], handler.VISITOR_SOURCE)

now_verdict, now_gaps = verdict_of("fea_run")
check("a sentence moved a two hour computation", (was_gaps, now_gaps), (2, 1))

# ---------------------------------------------------------------- reversing --

print("\nexpiry restores the reference state")
purge()
check("counts are back where they started", counts(), start)
check("fea_run is blocked again", verdict_of("fea_run"), (was_verdict, was_gaps))

# ------------------------------------------------------------------ routing --

print("\nHTTP")


def call(method, parameters=None, body=None):
    event = {"queryStringParameters": parameters or {},
             "requestContext": {"http": {"method": method}}, "body": body}
    return handler.lambda_handler(event, type("C", (), {"aws_request_id": "test"}))


check("a GET cannot reach the write route",
      call("GET", {"view": "commit", "claim": "x is y because z"})["statusCode"],
      405)
check("an unknown view is a 400",
      call("GET", {"view": "nope"})["statusCode"], 400)
check("a preflight is answered", call("OPTIONS")["statusCode"], 204)
check("health answers", call("GET", {"view": "health"})["statusCode"], 200)
check("a POST with a body that is not JSON is a 400",
      call("POST", {}, "not json")["statusCode"], 400)

posted = call("POST", {}, '{"view": "propose", "claim": "I think it is B"}')
check("a POST carries its parameters in the body", posted["statusCode"], 200)

check("nothing was written by the HTTP checks", counts(), start)

# -------------------------------------------------------------------- report --

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    for name in FAILED:
        print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
