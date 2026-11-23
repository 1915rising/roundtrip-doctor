#!/usr/bin/env python3
"""
Gown round-trip driver -- the end-to-end reproduction of the case
roundtrip-doctor was built for. Plain Python 3 (no Blender needed
for the driver itself); it shells out to three runtimes.

The trip, as it actually works (this driver is also the proof):

  1. Ensō (Blender 5.3 under Wine) runs tests/enso_trip_gown.py:
     paints a 43-edge seam chain onto GenGown in a copy of a
     female avatar's Christmas gown blend via Sculpt UVs' write path, saves
     AFTER, then erases and saves CYCLE.
  2. FORMAT WALL, demonstrated: Blender 4.2.3 cannot open the
     5.x-saved AFTER file at all ("not a blend file" -- Blender 5
     writes a new file format). The verifier CLI is run against it
     and must refuse with exit code 2.
  3. Leg 1 gate, in the seat that can read both files: Ensō runs
     tests/enso_side.py -- the same roundtrip_doctor code verifies
     BEFORE vs AFTER (PASS, seam delta == the painted chain) and
     BEFORE vs CYCLE (PASS, zero delta), and dumps AFTER's seam set
     as vertex-index pairs.
  4. Leg 2 gate, in the 4.2 seat: tests/apply_seams.py re-applies
     the seam set to the BEFORE file in Blender 4.2.3, producing a
     native RETURNED file; the verifier CLI must PASS it with a
     seam delta of exactly the applied edges.
  5. Negative: tests/move_vertex.py sabotages RETURNED (one vertex
     moved 1 mm); the verifier must FAIL it, naming vertices.

Usage:
  python3 tests/gown_roundtrip.py [--work DIR] [--examples DIR]

Defaults point at this machine's layout (the VM where the tool was
developed): the gown blend (RTD_GOWN, a generic default path), the
native Blender 4.2.3 build and the Ensō/Wine install in
~/workspace/tools/. Override with the environment variables
RTD_BLENDER, RTD_WINE, RTD_ENSO_EXE, RTD_WINEPREFIX, RTD_GOWN.
Reports land in examples/ (or --examples DIR).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

BLENDER = os.environ.get(
    "RTD_BLENDER", os.path.join(HOME, "workspace/tools/blender-4.2.3-linux-x64/blender"))
WINE = os.environ.get(
    "RTD_WINE", os.path.join(HOME, "workspace/tools/wine-staging/extracted/opt/wine-staging/bin/wine"))
ENSO_EXE = os.environ.get(
    "RTD_ENSO_EXE", os.path.join(
        HOME, "workspace/tools/enso-engine/app/EnsoEngine-1.1-beta-windows-x64-portable/blender.exe"))
WINEPREFIX = os.environ.get(
    "RTD_WINEPREFIX", os.path.join(HOME, "workspace/tools/enso-engine/wineprefix-staging"))
GOWN = os.environ.get(
    "RTD_GOWN", os.path.join(HOME, "workspace/models/christmas-gown.blend"))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("%s: %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)


def zpath(p):
    return "Z:" + os.path.abspath(p).replace("/", "\\")


def run(cmd, env=None, label=""):
    print("+ %s" % label, flush=True)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-5:])
    print(tail, flush=True)
    return r


def verify_cli(before, after, report_txt=None, report_json=None):
    cmd = [BLENDER, "-b", "--factory-startup", "--python",
           os.path.join(REPO, "roundtrip_doctor.py"), "--", before, after]
    if report_txt:
        cmd += ["--report", report_txt]
    if report_json:
        cmd += ["--json", report_json]
    return run(cmd, label="verify(4.2.3) %s" % os.path.basename(after))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/roundtrip-gown")
    ap.add_argument("--examples", default=os.path.join(REPO, "examples"))
    args = ap.parse_args()
    work = args.work
    os.makedirs(work, exist_ok=True)
    os.makedirs(args.examples, exist_ok=True)

    before = os.path.join(work, "before.blend")
    after = os.path.join(work, "after.blend")
    cycle = os.path.join(work, "cycle.blend")
    returned = os.path.join(work, "returned.blend")
    moved = os.path.join(work, "moved.blend")
    drawn_json = os.path.join(work, "drawn.json")
    seams_json = os.path.join(work, "seams.json")
    applied_json = os.path.join(work, "applied.json")
    shutil.copyfile(GOWN, before)
    print("BEFORE copied from %s" % GOWN, flush=True)
    wine_env = dict(os.environ, WINEPREFIX=WINEPREFIX, WINEDEBUG="-all")

    # 1 -- the Ensō trip: draw 43 seams, save AFTER; erase, save CYCLE
    r = run([WINE, ENSO_EXE, "-b", "--python",
             zpath(os.path.join(HERE, "enso_trip_gown.py")), "--",
             zpath(before), zpath(after), zpath(cycle), zpath(drawn_json)],
            env=wine_env, label="Ensō seam trip")
    check("Ensō trip completed", r.returncode == 0 and "ENSO_TRIP_DONE" in r.stdout,
          "rc=%d" % r.returncode)
    if not (os.path.isfile(after) and os.path.isfile(drawn_json)):
        print("ABORT: Ensō did not produce the after file", flush=True)
        raise SystemExit(1)
    drawn = json.load(open(drawn_json))
    target = drawn["object"]
    chain = set(drawn["chain"])
    print("Ensō painted %d seams on %s" % (len(chain), target), flush=True)

    # 2 -- the format wall: 4.2.3 must refuse the 5.x file outright
    r = verify_cli(before, after)
    check("4.2.3 cannot read the 5.x file directly (format wall)",
          r.returncode == 2, "rc=%d" % r.returncode)

    # 3 -- leg 1 gate inside Ensō + seam-set dump
    r = run([WINE, ENSO_EXE, "-b", "--python",
             zpath(os.path.join(HERE, "enso_side.py")), "--",
             zpath(REPO), zpath(before), zpath(after), zpath(cycle),
             target, zpath(seams_json), zpath(work)],
            env=wine_env, label="Ensō-seat verify + seam dump")
    check("Ensō-seat gate ran", r.returncode == 0 and "ENSO_SIDE_DONE" in r.stdout,
          "rc=%d" % r.returncode)
    rep = json.load(open(os.path.join(work, "enso-after-report.json")))
    e = rep["objects"][target]
    check("leg 1: Ensō-seat verifier PASSes the drawn trip",
          rep["verdict"] == "PASS", rep["verdict"])
    check("leg 1: seam delta == the exact chain Ensō painted",
          set(e["seams_added"]) == chain and e["seams_removed"] == [],
          "added=%d" % len(e["seams_added"]))
    others = {n: o for n, o in rep["objects"].items() if n != target}
    check("leg 1: all %d other objects byte-identical" % len(others),
          all(o["status"] == "PASS" and not o.get("seams_added")
              and not o.get("seams_removed") for o in others.values()))
    rep = json.load(open(os.path.join(work, "enso-cycle-report.json")))
    check("leg 1: draw+erase cycle PASSes with zero delta",
          rep["verdict"] == "PASS" and all(
              not o.get("seams_added") and not o.get("seams_removed")
              for o in rep["objects"].values()), rep["verdict"])
    shutil.copyfile(os.path.join(work, "enso-after-report.txt"),
                    os.path.join(args.examples, "gown-enso-seat-report.txt"))

    # 4 -- leg 2: re-apply the seam set in 4.2.3, gate the returned file
    r = run([BLENDER, "-b", "--factory-startup", "--python",
             os.path.join(HERE, "apply_seams.py"), "--",
             before, seams_json, returned, applied_json],
            label="apply seams in 4.2.3")
    check("return leg applied", r.returncode == 0 and os.path.isfile(returned))
    applied = set(json.load(open(applied_json))["applied_edge_indices"])
    rep_json = os.path.join(work, "returned-report.json")
    rep_txt = os.path.join(args.examples, "gown-roundtrip-report.txt")
    r = verify_cli(before, returned, rep_txt, rep_json)
    rep = json.load(open(rep_json))
    e = rep["objects"][target]
    check("leg 2: 4.2.3 verifier PASSes the returned file", r.returncode == 0,
          "rc=%d verdict=%s" % (r.returncode, rep["verdict"]))
    check("leg 2: seam delta == exactly the applied edges",
          set(e["seams_added"]) == applied and e["seams_removed"] == [],
          "added=%d applied=%d" % (len(e["seams_added"]), len(applied)))

    # 5 -- negative: one vertex moved by 1 mm in the returned file
    r = run([BLENDER, "-b", "--factory-startup", "--python",
             os.path.join(HERE, "move_vertex.py"), "--",
             returned, moved, target, "0", "0.001"],
            label="build sabotaged copy")
    check("sabotage fixture built", r.returncode == 0 and os.path.isfile(moved))
    rep_json = os.path.join(work, "moved-report.json")
    rep_txt = os.path.join(args.examples, "gown-negative-report.txt")
    r = verify_cli(before, moved, rep_txt, rep_json)
    rep = json.load(open(rep_json))
    e = rep["objects"][target]
    check("negative: verifier FAILs the moved-vertex copy", r.returncode == 1,
          "rc=%d verdict=%s" % (r.returncode, rep["verdict"]))
    check("negative: names the vertices channel",
          "vertices" in e["changed_channels"], str(e["changed_channels"]))

    passed = sum(1 for _, c in RESULTS if c)
    print("GOWN ROUND TRIP: %d/%d PASS" % (passed, len(RESULTS)), flush=True)
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
