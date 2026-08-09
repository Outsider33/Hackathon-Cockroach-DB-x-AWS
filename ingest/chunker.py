"""Turn the engineering notes into chunks, ready to embed.

Runs offline, needs nothing but the standard library. Reads a declared list of
source documents, splits them on markdown headings, and writes one JSON object
per chunk to data/chunks.jsonl.

Two things are DECLARED here rather than guessed, because guessing intent from
prose is how you get four false positives out of four:

  SOURCES        which documents go in. Not a directory walk.
  BELIEF_OF      which heading anchors which belief. Not keyword matching.

REDACTIONS replaces the names of third parties who never agreed to appear in a
public dataset. The engineering content is the author's own.

    SANDRAIL_NOTES=/path/to/notes python3 ingest/chunker.py

The notes are a private engineering repository and are not distributed with
this one, so this script cannot run for anybody else and says so instead of
failing on a path from somebody's laptop. The chunks it would produce are the
corpus already loaded in the database, which the demo reads and displays; the
point of keeping the script here is that the boundary is auditable, not that a
reader can rerun it.
"""

import io
import json
import os
import re
import sys
from pathlib import Path

# The console on this machine is GBK. Without this, writing a degree sign to
# stdout kills the script.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# An absolute path to somebody's laptop was hard-coded here until 2026-08-09,
# in a public repository whose README told the reader to run this file. It
# failed for everyone but its author and published the layout of a private
# repository on the way. The location is an input now, and its absence is an
# explained exit rather than a traceback.
SANDRAIL = Path(os.environ.get("SANDRAIL_NOTES", "")).expanduser()
OUT = Path(__file__).resolve().parent.parent / "data" / "chunks.jsonl"

# Bounded on purpose: one subsystem, the documents that carry its state.
SOURCES = [
    ("BESOINS_DONNEES.md", "data registry: what is missing and whether it blocks"),
    ("GLOSSAIRE.md", "glossary: the vocabulary of the project"),
    ("CAD_Pipeline/REPRISE.md", "pipeline state: defects found and fixed"),
    ("SESSION_2026-07-30_31.md", "session log: the mesh independence problem"),
    ("RECHERCHE_27-30_JUILLET.md", "research log: sourcing and standards"),
    ("CAD_Pipeline/VERIFICATION.md", "verification: what is checked and how"),
]

# heading fragment (lowercase) -> belief key it anchors
BELIEF_OF = {
    "aveugle a l'inversion": "fatigue_amplitude_basis",
    "aveugle à l'inversion": "fatigue_amplitude_basis",
    "mauvais critere": "convergence_criterion",
    "mauvais critère": "convergence_criterion",
    "optimiseur d'allegement": "pocket_count",
    "optimiseur d'allègement": "pocket_count",
    "fut de moyeu": "hub_barrel_architecture",
    "fût de moyeu": "hub_barrel_architecture",
    "tolerance d'arret": "stop_tolerance",
    "tolérance d'arrêt": "stop_tolerance",
    "masse du disque": "brake_disc_mass_kg",
    "rod ends": "rod_end_type",
    "jante avant": "front_wheel",
    "moyeu / roulement": "hub_bore_radius_mm",
    "faux trous": "lateral_g",
    "entraxe": "displayed_rod_spacing",
}

REDACTIONS = {
    r"\bBryan\b": "the application engineer",
    r"\bLee\b": "a contact",
    r"\bLucas\b": "the author",
}

MAX_CHARS = 1200
MIN_CHARS = 80


def redact(text):
    for pattern, replacement in REDACTIONS.items():
        text = re.sub(pattern, replacement, text)
    return text


def split_on_headings(raw):
    """Yield (heading, body). The heading is the last one seen, so a chunk
    always knows what it is about even after the body is cut."""
    current, buffer = "(preamble)", []
    for line in raw.splitlines():
        if re.match(r"^#{1,4}\s+\S", line):
            if buffer:
                yield current, "\n".join(buffer)
            current = re.sub(r"^#+\s+", "", line).strip()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        yield current, "\n".join(buffer)


def cut(body):
    """Split a long body on blank lines, never mid-sentence."""
    if len(body) <= MAX_CHARS:
        return [body]
    pieces, run = [], []
    size = 0
    for para in body.split("\n\n"):
        if size + len(para) > MAX_CHARS and run:
            pieces.append("\n\n".join(run))
            run, size = [], 0
        run.append(para)
        size += len(para) + 2
    if run:
        pieces.append("\n\n".join(run))
    return pieces


def belief_for(heading):
    low = heading.lower()
    for fragment, key in BELIEF_OF.items():
        if fragment in low:
            return key
    return None


def main():
    if not SANDRAIL.name or not SANDRAIL.is_dir():
        print("SANDRAIL_NOTES is not set to a directory that exists.")
        print()
        print("This script reads a private engineering repository that is not")
        print("distributed with this one, so it cannot run outside the machine")
        print("that holds those notes. The corpus it produces is already loaded")
        print("in the database and the demo displays the passages it retrieves.")
        print()
        print("  SANDRAIL_NOTES=/path/to/notes python3 ingest/chunker.py")
        print()
        print(f"expected these files under it: {[name for name, _ in SOURCES]}")
        return 2

    OUT.parent.mkdir(parents=True, exist_ok=True)
    written, skipped, missing = 0, 0, []

    with OUT.open("w", encoding="utf-8") as out:
        for name, label in SOURCES:
            path = SANDRAIL / name
            if not path.exists():
                missing.append(name)
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            for heading, body in split_on_headings(raw):
                for piece in cut(body):
                    text = redact(piece.strip())
                    if len(text) < MIN_CHARS:
                        skipped += 1
                        continue
                    out.write(json.dumps({
                        "file": name,
                        "label": label,
                        "heading": redact(heading),
                        "text": text,
                        "belief_key": belief_for(heading),
                    }, ensure_ascii=False) + "\n")
                    written += 1

    print(f"chunks written : {written}")
    print(f"too short, dropped : {skipped}")
    if missing:
        print(f"NOT FOUND, and that is a result, not a warning : {missing}")
    print(f"out : {OUT}")


if __name__ == "__main__":
    # main returns a status and it has to reach the shell. Without this the
    # script printed a refusal and exited 0, which is the shape of a step that
    # a pipeline happily builds on.
    sys.exit(main() or 0)
