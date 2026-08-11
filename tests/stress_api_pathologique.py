#!/usr/bin/env python3
"""stress_api_pathologique.py - what if the memory answers badly?

    python3 tests/stress_api_pathologique.py

The first bench asked what a judge might TYPE. This one asks what the API might
ANSWER. It is the harder half, because the failures are not hypothetical: a
Lambda cold start returns 502, a throttled account returns 429, a redeploy can
change a field name, and a connection dropped mid-body returns JSON that starts
valid and stops in the middle.

Everything is served by a local server on 127.0.0.1, so the cases are
deterministic and the real deployment is not hammered. Each pathology is served
under its own path, and the agent is pointed at it with --api.

The bar is unchanged: never a traceback, never a hang, always an exit code a
script can read.
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ICI = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(ICI, os.pardir, "agent_loop.py")
PY = sys.executable

BON = {"view": "missing", "computations": [
    {"computation": "fea_run", "purpose": "p", "cost_note": "about 2 hours",
     "blocking_gaps": 1, "requirements": [
         {"key": "k", "criticality": "BLOCKING", "why": "w",
          "status": "UNDECIDABLE", "value": "v", "satisfied": False}]}]}

CAS = {}                       # chemin -> (code, entetes, corps bytes, delai_s)


def enregistre(nom, corps, code=200, ctype="application/json", delai=0.0, entetes=None):
    if isinstance(corps, (dict, list)):
        corps = json.dumps(corps).encode()
    elif isinstance(corps, str):
        corps = corps.encode()
    CAS[nom] = (code, ctype, corps, delai, entetes or {})


# --- ce qu'une API peut reellement renvoyer de travers ---------------------
enregistre("tronque", json.dumps(BON)[:120])                  # coupe en plein vol
enregistre("vide", b"")                                        # 200, zero octet
enregistre("pas_de_computations", {"view": "missing"})         # cle absente
enregistre("computations_vides", {"view": "missing", "computations": []})
enregistre("sans_requirements", {"view": "missing", "computations": [
    {"computation": "fea_run", "cost_note": "2 h"}]})          # pas de requirements
enregistre("champs_nuls", {"view": "missing", "computations": [
    {"computation": "fea_run", "cost_note": None, "requirements": [
        {"key": "k", "criticality": None, "why": None,
         "status": None, "value": None, "satisfied": None}]}]})
enregistre("liste_au_lieu_dobjet", [1, 2, 3])
enregistre("nombre_au_lieu_dobjet", 42)
enregistre("octets_invalides", b'{"view":"missing","computations":[{"computation":"\xff\xfe"}]}')
enregistre("enorme", {"view": "missing", "computations": [
    {"computation": "fea_run", "cost_note": "x" * 2_000_000, "requirements": []}]})
enregistre("erreur_500", {"error": "internal"}, code=500)
enregistre("erreur_502", "<html>502 Bad Gateway</html>", code=502, ctype="text/html")
enregistre("erreur_429", {"error": "Too Many Requests"}, code=429)
enregistre("erreur_403", {"error": "Forbidden"}, code=403)
enregistre("redirection", b"", code=302, entetes={"Location": "http://127.0.0.1:%PORT%/bon"})
enregistre("lent_25s", BON, delai=25.0)                        # au-dela du timeout de 20 s
enregistre("bon", BON)


class Poignee(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        nom = self.path.lstrip("/").split("?")[0] or "bon"
        if nom not in CAS:
            nom = "bon"
        code, ctype, corps, delai, entetes = CAS[nom]
        if delai:
            time.sleep(delai)
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(corps)))
            for k, v in entetes.items():
                self.send_header(k, v.replace("%PORT%", str(self.server.server_port)))
            self.end_headers()
            self.wfile.write(corps)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *a):
        pass


def port_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = port_libre()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Poignee)
threading.Thread(target=srv.serve_forever, daemon=True).start()

resultats = []


def essai(nom, chemin=None, limite=45.0, env=None):
    url = f"http://127.0.0.1:{PORT}/{chemin if chemin is not None else nom}"
    t0 = time.time()
    try:
        r = subprocess.run([PY, AGENT, "--api", url], capture_output=True, text=True,
                           errors="replace", timeout=limite,
                           env={**os.environ, **(env or {})})
        d = time.time() - t0
        sortie = (r.stdout or "") + (r.stderr or "")
        if "Traceback (most recent call last)" in sortie:
            v = "CRASH"
            det = [l for l in sortie.splitlines() if l.strip()][-1][:64]
        else:
            v, det = "OK", f"code {r.returncode}"
    except subprocess.TimeoutExpired:
        d, v, det = time.time() - t0, "HANG", f"> {limite:.0f}s"
    resultats.append((v, nom, d, det))
    print(f"  [{'  ok  ' if v == 'OK' else v + '!'}] {nom:<26} {d:>5.1f}s  {det}")


print(f"\n  faux serveur sur 127.0.0.1:{PORT}\n")
print("=== Ce que l'API peut renvoyer de travers ===")
for nom in ["tronque", "vide", "pas_de_computations", "computations_vides",
            "sans_requirements", "champs_nuls", "liste_au_lieu_dobjet",
            "nombre_au_lieu_dobjet", "octets_invalides", "enorme"]:
    essai(nom)

print("\n=== Codes HTTP d'un Lambda qui va mal ===")
for nom in ["erreur_500", "erreur_502", "erreur_429", "erreur_403", "redirection"]:
    essai(nom)

print("\n=== Lenteur : le timeout de 20 s tient-il ? ===")
essai("lent_25s", limite=60)

print("\n=== Sortie redirigee : c'est ainsi qu'on enregistre un plan ===")
essai("bon (stdout non tty)", "bon")
essai("bon (locale C)", "bon", env={"PYTHONIOENCODING": "ascii"})

print("\n=== Deux instances en parallele ===")
t0 = time.time()
ps = [subprocess.Popen([PY, AGENT, "--api", f"http://127.0.0.1:{PORT}/bon"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
codes = [p.wait(timeout=60) for p in ps]
d = time.time() - t0
meme = len(set(codes)) == 1
resultats.append(("OK" if meme else "CRASH", "3 en parallele", d, f"codes {codes}"))
print(f"  [{'  ok  ' if meme else 'CRASH!'}] {'3 en parallele':<26} {d:>5.1f}s  codes {codes}")

srv.shutdown()
print("\n" + "=" * 66)
mauvais = [r for r in resultats if r[0] != "OK"]
print(f"  {len(resultats)} essais  |  {len(mauvais)} probleme(s)")
for v, n, d, det in mauvais:
    print(f"    {v:<6} {n:<28} {det}")
print("\n  🟢 RIEN NE CASSE." if not mauvais else "\n  🔴 A CORRIGER.")
sys.exit(1 if mauvais else 0)
