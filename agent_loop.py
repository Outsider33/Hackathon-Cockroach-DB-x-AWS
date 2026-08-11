#!/usr/bin/env python3
"""agent_loop.py - an agent that reads its own memory and refuses when it must.

    python3 agent_loop.py                     # default goal: fea_run
    python3 agent_loop.py --goal render_video
    python3 agent_loop.py --list              # what goals exist

No installation, no credentials, no API key. It talks to the public read-only
endpoint over HTTPS with nothing but the standard library, so a judge can run it
on their own machine against the live deployment and get the same answer.

WHY THIS FILE EXISTS
--------------------
The repository holds a memory schema. A schema is not an agent. Without this
loop a judge sees a human asking questions to an API; with it, they see a
program decline to spend two hours of compute because one of its own beliefs is
UNDECIDABLE, name which one, say since when and on whose authority, and then
accept the same command once that belief has been settled.

The interesting outcome is not the action. It is the argued refusal.

WHAT IT DOES NOT DO
-------------------
It never writes. Writing is a third party's act, it would put a public demo at
risk, and it would blur the demonstration: the only thing allowed to change
between a refusal and an acceptance is the memory itself.

It calls no language model. The agent does not need to be intelligent, it needs
to be CONSEQUENT - the decision follows from stored beliefs, not from inference.
That is also why it stays deterministic, and why two runs a minute apart differ
only if somebody changed the memory in between.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import unicodedata
import urllib.request
from datetime import date

API = "https://ds27zo3o73.execute-api.us-east-1.amazonaws.com/"
TIMEOUT_S = 20

# The excerpts printed below are raw passages from an engineer's own notes, which
# contain emoji and accented French. A judge may run this in any terminal, and a
# Windows console on a GBK codepage raises UnicodeEncodeError on the first emoji
# and kills the demo mid-sentence. Caught exactly that way on 2026-08-11.
# errors="replace" degrades a character instead of the whole run.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, OSError):      # older Python, or a stream that cannot
    pass                               # be reconfigured: not worth failing over

# Exit codes, so the loop can be used in a script and not only read by a human.
EXIT_ACTED = 0
EXIT_REFUSED = 1
EXIT_UNKNOWN = 2
EXIT_UNREACHABLE = 3


def fetch(view, **params):
    """One GET against the public endpoint.

    Decoded with errors="replace" on purpose: one stored evidence string in the
    live data contains a lone surrogate, and a judge's demo must not die on a
    mojibake. A broken character is a cosmetic defect; a traceback in front of a
    jury is not.
    """
    url = API + "?" + urllib.parse.urlencode({"view": view, **params})
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
            brut = r.read()
    except urllib.error.HTTPError as e:
        brut = e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"\n  the memory is unreachable: {e}\n  endpoint: {API}", file=sys.stderr)
        sys.exit(EXIT_UNREACHABLE)
    try:
        objet = json.loads(brut.decode("utf-8", "replace"))
        if not isinstance(objet, dict):
            # Valid JSON, wrong shape. Found by the pathological-API bench on
            # 2026-08-12: a body of `[1,2,3]` parses cleanly, and then every
            # .get() below raises AttributeError. Well formed and wrong is a
            # nastier failure than malformed, because it clears the first gate.
            raise json.JSONDecodeError("expected a JSON object", "", 0)
        return objet
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A host answered, but not with our memory. Found by stress test on
        # 2026-08-12: pointing --api at any ordinary web server returns HTML and
        # raised JSONDecodeError in front of whoever was watching. It is the most
        # likely network failure of all -- a captive portal, a proxy error page, a
        # CDN interstitial -- and behind a VPN it is likelier still.
        apercu = " ".join(brut[:120].decode("utf-8", "replace").split())
        print(f"\n  something answered at {API}, but it is not this memory.\n"
              f"  expected JSON, got: {apercu}\n"
              f"  a captive portal or a proxy page will do this.", file=sys.stderr)
        sys.exit(EXIT_UNREACHABLE)


def provenance():
    """key -> (source, first day it held).

    Beliefs carry their provenance in `asof`, not in `missing`. Citing it is the
    whole point: without a source and a date, an agent that changes its mind
    looks like a program with a bug rather than one with a memory.
    """
    data = fetch("asof", on=date.today().isoformat())
    out = {}
    for b in data.get("beliefs", []):
        jour = (b.get("valid_from") or "")[:10]
        out[b["key"]] = (b.get("source") or "unrecorded", jour or "undated")
    return out


def affichable(texte):
    """Fold an untrusted passage down to ASCII, unconditionally.

    These excerpts are raw text from an engineer's notes: emoji, arrows, accents,
    and at least one lone surrogate. Two failure modes were observed on
    2026-08-11, in this order:

      1. a codepage that CANNOT encode the character -> UnicodeEncodeError, and
         the demo dies mid-sentence in front of whoever is watching;
      2. a codepage that CAN encode it -- GBK carries U+2192 -- but renders it as
         garbage anyway, which survives but looks broken on a screen recording.

    Testing the output encoding only fixes the first. Since the excerpt is a
    POINTER ("the answer is probably in this file"), not the content itself,
    losing accents in 88 characters costs nothing, while an unreadable line
    costs the shot. So: always ASCII, on every terminal, predictably.
    """
    return (unicodedata.normalize("NFKD", texte or "")
            .encode("ascii", "ignore").decode("ascii"))


def wrap(text, width, pad):
    """Fold long prose so the trace stays readable in a terminal recording."""
    mots, ligne, lignes = (text or "").split(), "", []
    for m in mots:
        if len(ligne) + len(m) + 1 > width:
            lignes.append(ligne)
            ligne = m
        else:
            ligne = f"{ligne} {m}".strip()
    lignes.append(ligne)
    return f"\n{' ' * pad}".join(l for l in lignes if l)


def main():
    global API
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--goal", default="fea_run")
    ap.add_argument("--list", action="store_true", help="list known goals and exit")
    ap.add_argument("--api", default=API, help="override the endpoint")
    a = ap.parse_args()
    API = a.api

    memoire = fetch("missing")
    calculs = memoire.get("computations", [])

    if a.list:
        print("\n  goals held in memory\n")
        for c in calculs:
            print(f"    {c['computation']:<22} {c.get('blocking_gaps', 0)} blocking")
        print()
        return EXIT_ACTED

    cible = next((c for c in calculs if c["computation"] == a.goal), None)

    print(f"\nGOAL        run {a.goal}")
    if cible:
        print(f"            \"{cible.get('cost_note', 'cost unrecorded')}\"")
    print()
    # ASCII only from here down. This is filmed for a jury and read in terminals
    # whose codepage is not always UTF-8: a middle dot renders as garbage on a
    # Windows GBK console, which is exactly where it was caught.
    print(f"PERCEIVE    reading my own memory ........ view=missing")
    print(f"            {len(calculs)} computations, "
          f"{sum(len(c.get('requirements', [])) for c in calculs)} requirements")
    print()

    # ---- Outcome 3: the goal is not in memory at all -----------------------
    # This is not an error and it is not a refusal. An agent asked for something
    # it has never heard of must say so plainly, otherwise "I don't know" and
    # "no" collapse into the same answer - which is the exact failure this whole
    # project argues against.
    if cible is None:
        print(f"DECIDE      {a.goal}  ->  UNKNOWN")
        print()
        print("VERDICT     I HAVE NO MEMORY OF THIS GOAL.")
        print("            Not a refusal. I cannot judge what I have never stored.")
        print()
        print("KNOWN GOALS " + ", ".join(c["computation"] for c in calculs))
        print()
        return EXIT_UNKNOWN

    sources = provenance()
    exigences = cible.get("requirements", [])
    bloquantes = [r for r in exigences
                  if r.get("criticality") == "BLOCKING" and not r.get("satisfied")]
    degradantes = [r for r in exigences
                   if r.get("criticality") == "DEGRADES" and not r.get("satisfied")]

    etat = "BLOCKED" if bloquantes else "CLEAR"
    print(f"DECIDE      {a.goal}  ->  {etat}  "
          f"({len(bloquantes)} of {len(exigences)} requirements)")
    print()

    for r in bloquantes:
        src, jour = sources.get(r["key"], ("unrecorded", "undated"))
        print(f"  {r['key']:<26} {r.get('status', '?')}")
        print(f"    known since   {jour}")
        print(f"    source        {src}")
        print(f"    blocks because  {wrap(r.get('why', ''), 54, 20)}")
        if r.get("value"):
            print(f"    what I hold     {wrap(r['value'], 54, 20)}")
        print()

    # ---- Outcome 1: refuse, and argue ------------------------------------
    if bloquantes:
        print("VERDICT     I AM NOT RUNNING THIS.")
        print(f"            The cost is {cible.get('cost_note', 'unrecorded')},")
        print("            and the result would be a number nobody could defend.")
        print()

        # A refusal that only says "no" wastes the memory. `unblock` returns, for
        # every gap, the passages of the engineer's OWN notes that sit closest to
        # it, with a similarity score. So the agent does not merely decline: it
        # routes. That is the difference between a guard and an assistant, and it
        # is the beat worth filming.
        deblocage = fetch("unblock", computation=a.goal)
        print(f"TO UNBLOCK  view=unblock&computation={a.goal}")
        print()
        for c in deblocage.get("computations", []):
            for g in c.get("gaps", []):
                if g.get("criticality") != "BLOCKING":
                    continue
                print(f"  establish {g['key']}")
                lus = g.get("read") or []
                if not lus:
                    print("    nothing in the corpus comes close. This one is not")
                    print("    hiding in the notes, it has to be decided.")
                for p in lus[:2]:
                    extrait = affichable(" ".join((p.get("text") or "").split())[:88])
                    print(f"    look in {affichable(p.get('file', '?'))}   "
                          f"(similarity {p.get('similarity', '?')})")
                    print(f"      \"{extrait}...\"")
                print()
        return EXIT_REFUSED

    # ---- Outcome 2: act, and say what the decision rests on ---------------
    print("VERDICT     I AM RUNNING IT.")
    print("            Every blocking requirement is ESTABLISHED. Standing on:")
    print()
    for r in exigences:
        if r.get("criticality") == "BLOCKING":
            src, jour = sources.get(r["key"], ("unrecorded", "undated"))
            print(f"  {r['key']:<26} ESTABLISHED   {jour}   {src}")
    if degradantes:
        print()
        print("  proceeding with known degradations:")
        for r in degradantes:
            print(f"    {r['key']} ({r.get('status', '?')})")
    print()
    return EXIT_ACTED


if __name__ == "__main__":
    sys.exit(main())
