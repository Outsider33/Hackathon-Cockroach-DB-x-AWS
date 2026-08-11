#!/usr/bin/env python3
"""stress_agent_loop.py - can this thing embarrass us in front of a jury?

    python3 stress_agent_loop.py

The only failure that really costs anything during a live demo is a traceback,
because it turns a claim about rigour into a screenshot of a crash. A hang is the
second worst: dead air on a three-minute video is unrecoverable. Everything else
is cosmetic.

So the bar here is deliberately not "does it produce the right answer". It is:
  - never raise an unhandled exception, whatever it is fed
  - never hang past a few seconds
  - return the SAME answer for the same question, so a rehearsal predicts the take
  - degrade in a way that can be read aloud
"""
import json
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ICI = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(ICI, os.pardir, "agent_loop.py")   # tests/ -> racine du depot
PY = sys.executable
LIMITE_S = 40.0          # au-dela, c'est un plan mort a l'ecran

resultats = []


def lancer(titre, args, attendu=None, limite=LIMITE_S):
    t0 = time.time()
    try:
        r = subprocess.run([PY, AGENT, *args], capture_output=True, text=True,
                           errors="replace", timeout=limite)
        d = time.time() - t0
        sortie = (r.stdout or "") + (r.stderr or "")
        crash = "Traceback (most recent call last)" in sortie
        if crash:
            verdict, detail = "CRASH", [l for l in sortie.splitlines() if l.strip()][-1][:70]
        elif attendu is not None and r.returncode != attendu:
            verdict, detail = "CODE", f"attendu {attendu}, obtenu {r.returncode}"
        else:
            verdict, detail = "OK", f"code {r.returncode}"
    except subprocess.TimeoutExpired:
        d, verdict, detail = time.time() - t0, "HANG", f"> {limite:.0f} s"
        sortie = ""
    resultats.append((verdict, titre, d, detail))
    marque = {"OK": "  ok  ", "CODE": " CODE ", "CRASH": "CRASH!", "HANG": "HANG! "}[verdict]
    print(f"  [{marque}] {titre:<44} {d:>5.1f}s  {detail}")
    return sortie


print("\n=== 1. Ce qu'un jure peut taper ===")
lancer("aucun argument (objectif par defaut)", [], attendu=1)
lancer("--help", ["--help"], attendu=0)
lancer("--list", ["--list"], attendu=0)
lancer("objectif inconnu", ["--goal", "does_not_exist"], attendu=2)
lancer("objectif vide", ["--goal", ""], attendu=2)
lancer("objectif avec espaces", ["--goal", "fea run"], attendu=2)
lancer("objectif avec accents", ["--goal", "épaisseur"], attendu=2)
lancer("objectif tres long (2 ko)", ["--goal", "x" * 2000], attendu=2)
lancer("caracteres d'echappement", ["--goal", "fea_run%00&view=health"], attendu=2)
lancer("apostrophe SQL", ["--goal", "' OR 1=1 --"], attendu=2)

print("\n=== 2. Quand le reseau lache (le cas qui fait peur) ===")
lancer("hote inexistant", ["--api", "https://nowhere.invalid/"], attendu=3, limite=45)
lancer("hote joignable, pas notre API", ["--api", "https://example.com/"], limite=45)
lancer("port ferme", ["--api", "https://localhost:9/"], attendu=3, limite=45)

print("\n=== 3. Reproductibilite : une repetition predit-elle la prise ? ===")
sorties = []
for i in range(3):
    s = lancer(f"fea_run, passe {i + 1}/3", ["--goal", "fea_run"], attendu=1)
    sorties.append(re.sub(r"\d+\.\d+s|\d{2}:\d{2}:\d{2}", "", s))
identiques = len(set(sorties)) == 1
resultats.append(("OK" if identiques else "CODE", "sorties identiques sur 3 passes", 0.0,
                  "identiques" if identiques else f"{len(set(sorties))} variantes"))
print(f"  [{'  ok  ' if identiques else ' CODE '}] "
      f"{'sorties identiques sur 3 passes':<44}        "
      f"{'identiques' if identiques else str(len(set(sorties))) + ' variantes'}")

print("\n=== 4. Les trois issues sont-elles encore distinctes ? ===")
codes = {}
for lbl, g, att in [("REFUS", "fea_run", 1), ("ACCEPTE", "fatigue_check_parent", 0),
                    ("INCONNU", "nexiste_pas", 2)]:
    s = lancer(f"{lbl} -> code {att}", ["--goal", g], attendu=att)
    codes[lbl] = s

print("\n" + "=" * 74)
crash = [r for r in resultats if r[0] == "CRASH"]
hang = [r for r in resultats if r[0] == "HANG"]
code = [r for r in resultats if r[0] == "CODE"]
lent = [r for r in resultats if r[2] > 20]
print(f"  {len(resultats)} essais  |  {len(crash)} crash  |  {len(hang)} blocage  |"
      f"  {len(code)} code inattendu  |  {len(lent)} au-dela de 20 s")
for l, t, d, det in crash + hang + code:
    print(f"    {l:<6} {t:<46} {det}")
if not crash and not hang:
    print("\n  🟢 AUCUN CRASH, AUCUN BLOCAGE. Filmable.")
else:
    print("\n  🔴 A CORRIGER AVANT DE FILMER.")
sys.exit(1 if (crash or hang) else 0)
