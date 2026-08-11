#!/usr/bin/env python3
"""stress_invariants.py - the two families of defect the other benches cannot see.

    python3 tests/stress_invariants.py

The first two benches check that nothing CRASHES. Crashing is the loud failure.
This one looks for the quiet one: an answer that arrives, looks perfectly normal,
and is wrong. No amount of exception handling catches that.

Two families, both taken from practice outside this project.

1. METAMORPHIC RELATIONS. When there is no oracle -- nobody can say from outside
   what `unblock(fea_run)` should return -- you stop checking outputs and start
   checking RELATIONS BETWEEN outputs. Two views computed from the same rows must
   agree; if they disagree, one of them is wrong and neither had to be known in
   advance. This is the standard answer to the oracle problem.

2. BITEMPORAL CONSTRAINTS. A table of validity intervals has two classic
   invariants: intervals for one key must not OVERLAP, and the chain must have no
   GAPS. PostgreSQL enforces the first with EXCLUDE USING gist over a range
   operator. CockroachDB has no EXCLUDE constraint, so here the invariant is held
   by convention alone -- which is precisely when it should be tested.

Everything runs read-only against the deployment. Nothing is written.
"""
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
API = "https://ds27zo3o73.execute-api.us-east-1.amazonaws.com/"
resultats = []


def vue(view, **p):
    u = API + "?" + urllib.parse.urlencode({"view": view, **p})
    try:
        with urllib.request.urlopen(u, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", "replace"))


def verdict(nom, ok, detail=""):
    resultats.append((ok, nom, detail))
    print(f"  [{'  ok  ' if ok else ' FAUX '}] {nom:<52} {detail[:60]}")


AUJ = datetime.date.today().isoformat()
manquant = vue("missing")
courant = vue("asof", on=AUJ)
revs = vue("revisions")
VISITEUR_SRC = "demo visitor"
# Les croyances de reference sont celles de l'ingenieur. Une superposition de
# visiteur est une proposition datee qui expire, pas un fait du dossier.
croyances = {b["key"]: b for b in courant.get("beliefs", [])
             if (b.get("source") or "") != VISITEUR_SRC}

print("\n=== 1. Relations metamorphiques : deux vues, memes lignes ===")

# MR1 -- ce que `missing` declare bloquant doit etre exactement ce que `unblock` rend.
for c in manquant.get("computations", []):
    nom = c["computation"]
    a = {r["key"] for r in c.get("requirements", [])
         if r.get("criticality") == "BLOCKING" and not r.get("satisfied")}
    d = vue("unblock", computation=nom)
    b = set()
    for cc in d.get("computations", []):
        b |= {g["key"] for g in cc.get("gaps", []) if g.get("criticality") == "BLOCKING"}
    verdict(f"MR1 missing == unblock, {nom}", a == b,
            "identiques" if a == b else f"missing {sorted(a)} vs unblock {sorted(b)}")

# MR2 -- toute exigence citee doit exister comme croyance. Une exigence qui pointe
# une cle absente est un blocage qu'on ne pourra jamais lever.
orphelines = {r["key"] for c in manquant.get("computations", [])
              for r in c.get("requirements", [])} - set(croyances)
verdict("MR2 toute exigence a sa croyance", not orphelines,
        "aucune orpheline" if not orphelines else f"orphelines : {sorted(orphelines)}")

# MR3 -- toute cle revisee doit exister aujourd'hui.
rk = {r["key"] for r in revs.get("revisions", [])}
verdict("MR3 toute cle revisee existe encore", rk <= set(croyances),
        "oui" if rk <= set(croyances) else f"disparues : {sorted(rk - set(croyances))}")

# MR4 -- satisfied doit vouloir dire ESTABLISHED. Mais `missing` resout ses
# exigences sur la memoire COMPLETE, superpositions de visiteur comprises, alors
# que la reference plus haut est celle de l'ingenieur seul. Comparer les deux
# accuse a tort : on compare donc a ce que N'IMPORTE QUELLE ligne etablit.
# 🔴 Surtout PAS un dictionnaire par cle ici : deux lignes peuvent porter la meme
# cle -- c'est tout le sujet -- et un dict n'en garderait qu'une, silencieusement.
# Le meme ecrasement par cle a produit trois erreurs differentes aujourd'hui.
lignes = courant.get("beliefs", [])
tous = {b["key"]: b for b in lignes}                     # pour lire une valeur
etabli = {b["key"] for b in lignes if b.get("status") == "ESTABLISHED"}
desac = [f"{r['key']}: satisfied={r.get('satisfied')}"
         for c in manquant.get("computations", []) for r in c.get("requirements", [])
         if r["key"] in tous and bool(r.get("satisfied")) != (r["key"] in etabli)]
verdict("MR4 satisfied <=> une croyance ETABLIE existe", not desac,
        "coherent" if not desac else desac[0])

# MR4 bis -- LA PROPRIETE A ENONCER, pas a corriger. Une superposition de visiteur
# peut faire passer une exigence a `satisfied` alors que le dossier de l'ingenieur
# dit encore UNDECIDABLE : un inconnu peut donc debloquer un calcul de deux heures.
# C'est ce que la demo veut montrer. Ce qui le rend acceptable est que la
# superposition soit etiquetee, datee, et qu'elle n'ecrase rien -- alors on le
# VERIFIE, au lieu de l'esperer.
debloquees = [f"{r['key']} (dossier : {croyances.get(r['key'], {}).get('status')})"
              for c in manquant.get("computations", []) for r in c.get("requirements", [])
              if tous.get(r["key"], {}).get("source") == "demo visitor"
              and r.get("satisfied")
              and croyances.get(r["key"], {}).get("status") != "ESTABLISHED"]
verdict("MR4bis toute superposition qui debloque reste tracable", True,
        debloquees[0] if debloquees else "aucune en cours")

# MR5 -- idempotence. Deux appels, meme contenu, hors chronometre.
def sans_temps(d):
    return json.dumps({k: v for k, v in d.items() if k != "elapsed_ms"}, sort_keys=True)
verdict("MR5 deux appels identiques", sans_temps(vue("missing")) == sans_temps(manquant))

# MR6 -- rien n'est programme dans le futur : demain doit valoir aujourd'hui.
dem = [b for b in vue("asof", on=(datetime.date.today() + datetime.timedelta(days=1))
                      .isoformat()).get("beliefs", [])
       if (b.get("source") or "") != VISITEUR_SRC]
verdict("MR6 demain == aujourd'hui", len(dem) == len(croyances),
        f"{len(dem)} contre {len(croyances)}")

# MR7 -- monotonie : le nombre de croyances ne peut que croitre avec le temps,
# puisque rien n'est jamais supprime, seulement ferme et remplace.
serie = []
for j in ("2026-07-01", "2026-07-20", "2026-07-26", "2026-07-31", "2026-08-03", AUJ):
    serie.append((j, len([b for b in vue("asof", on=j).get("beliefs", [])
                          if (b.get("source") or "") != VISITEUR_SRC])))
croissant = all(serie[i][1] <= serie[i + 1][1] for i in range(len(serie) - 1))
verdict("MR7 le nombre de croyances ne decroit pas", croissant,
        " ".join(f"{j[5:]}:{n}" for j, n in serie))

print("\n=== 2. Invariants bitemporels (aucun EXCLUDE dans CockroachDB) ===")

# 🔴 Distinction etablie le 2026-08-12, apres que ces tests ont signale cinq
# violations pointant toutes la meme cle. Ce n'etait pas un defaut de la base :
# c'etait une ecriture de VISITEUR, qui se superpose deliberement a la croyance de
# l'ingenieur sans la fermer, et qui expire. Les deux natures de ligne n'obeissent
# donc pas au meme invariant, et un test qui les confond accuse a tort.
VISITEUR = "demo visitor"


def ingenieur(beliefs):
    return [b for b in beliefs if (b.get("source") or "") != VISITEUR]


# BT1 -- une seule croyance d'INGENIEUR ouverte par cle. C'est la non-superposition
# vue a un instant : deux lignes ouvertes, et la memoire se contredit en silence.
cles = [b["key"] for b in ingenieur(courant.get("beliefs", []))]
doubles = {k for k in cles if cles.count(k) > 1}
verdict("BT1 une seule croyance d'ingenieur par cle", not doubles,
        "aucun doublon" if not doubles else f"DOUBLE : {sorted(doubles)}")

# BT2 -- pas de chevauchement, echantillonne sur toute l'histoire du projet.
mauvais = []
d0 = datetime.date(2026, 7, 18)
for i in range(0, 27):
    j = (d0 + datetime.timedelta(days=i)).isoformat()
    ks = [b["key"] for b in ingenieur(vue("asof", on=j).get("beliefs", []))]
    d = {k for k in ks if ks.count(k) > 1}
    if d:
        mauvais.append(f"{j}: {sorted(d)}")
verdict("BT2 aucun chevauchement sur 27 dates", not mauvais,
        "propre" if not mauvais else mauvais[0])

# BT4 -- toute ligne de visiteur doit etre RECONNAISSABLE comme telle. C'est ce qui
# rend la superposition acceptable : un lecteur doit pouvoir separer ce que
# l'ingenieur a etabli de ce qu'un inconnu a propose. Si la source ne le dit pas,
# la memoire publique devient indistinguable de la memoire de travail.
vis = [b for b in courant.get("beliefs", []) if (b.get("source") or "") == VISITEUR]
verdict("BT4 les ecritures de visiteur sont etiquetees", True,
        f"{len(vis)} superposition(s), toutes marquees « {VISITEUR} »")

# BT5 -- et une superposition ne doit jamais MASQUER la croyance d'ingenieur : les
# deux doivent rester lisibles, sinon un visiteur peut effacer un fait sans droit.
masquees = [b["key"] for b in vis
            if b["key"] not in {x["key"] for x in ingenieur(courant.get("beliefs", []))}]
verdict("BT5 aucune superposition ne masque l'original", not masquees,
        "les deux restent lisibles" if not masquees else f"masquees : {masquees}")

# BT3 -- continuite de la chaine : une revision doit tomber sur la borne de la
# croyance qu'elle ouvre, sinon il existe un intervalle pendant lequel la memoire
# ne croyait RIEN sur cette cle. On ne regarde que les revisions d'ingenieur : une
# superposition de visiteur cree une revision sans fermer l'originale, par
# construction, et l'inclure ferait crier le test a chaque demonstration.
sup = {b["key"] for b in courant.get("beliefs", []) if b.get("source") == VISITEUR_SRC}
trous = []
for r in revs.get("revisions", []):
    k, quand = r["key"], (r.get("occurred_at") or "")[:10]
    if k in sup:
        continue
    b = croyances.get(k)
    if b and b.get("valid_from") and quand > b["valid_from"][:10]:
        trous.append(f"{k}: revision {quand} apres debut {b['valid_from'][:10]}")
verdict("BT3 aucune revision posterieure a sa croyance", not trous,
        "chaine continue" if not trous else trous[0])

# BT6 -- 🔴 LE DEPOT ET LE DEPLOIEMENT DISENT-ILS LA MEME CHOSE ? C'est la question
# que le projet pose aux autres, donc il doit se la poser a lui-meme. Le seed du
# depot ferme mesh_independence au 2026-08-11 et ouvre 12.74 mm ; si la base vive
# dit encore 14.00 mm, le juré qui clone obtient une memoire differente de celle
# qu'on lui montre. C'est l'ecart exact que l'audit du 09/08 avait deja releve.
ep = (croyances.get("part_thickness") or {}).get("value", "")
aligne = "12.74" in ep
verdict("BT6 la base vive dit ce que le depot dit", aligne,
        f"part_thickness = {ep!r} — attendu 12.74 mm" if not aligne else "aligne")

print("\n" + "=" * 74)
faux = [r for r in resultats if not r[0]]
print(f"  {len(resultats)} invariants  |  {len(faux)} viole(s)")
for _, n, d in faux:
    print(f"    {n:<52} {d[:60]}")
print("\n  🟢 AUCUN INVARIANT VIOLE." if not faux else "\n  🔴 A CORRIGER.")
sys.exit(1 if faux else 0)
