"""
Ensō-seat verification + seam extraction. Runs INSIDE Ensō
(Blender 5.3 under Wine) -- see gown_roundtrip.py for the driver.

  blender.exe -b --python enso_side.py -- REPO_DIR BEFORE AFTER CYCLE TARGET SEAMS.json OUTDIR

Why this exists: Blender 5.x saves a new .blend format that
Blender 4.2.3 cannot open at all ("not a blend file"), so the
AFTER file of a sidecar trip can never be diffed in the 4.2 seat
directly. But the newer seat reads BOTH files (5.x opens 4.2 files
fine), and roundtrip_doctor.py is plain Blender Python -- so leg 1
of the gate runs here: verify BEFORE vs AFTER and BEFORE vs CYCLE
with the very same hashing code, and write the reports out.

Leg 2 needs the seams back in a native 4.2 file. Seam flags do not
survive any interchange format, but a seam SET does: this script
also dumps the target object's seam edges from AFTER as sorted
vertex-index pairs (edge identity that survives any faithful load
of the same mesh) into SEAMS.json, for tests/apply_seams.py to
re-apply in Blender 4.2.3.
"""

import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
repo_dir, before_p, after_p, cycle_p, target, seams_p, outdir = argv[:7]
sys.path.insert(0, repo_dir.replace("\\", "/"))
import roundtrip_doctor as rd  # noqa: E402


def run_verify(before, after, tag):
    ok, report = rd.verify(before, after)
    with open(os.path.join(outdir, "%s-report.json" % tag), "w") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(outdir, "%s-report.txt" % tag), "w") as f:
        f.write(rd.format_report(report) + "\n")
    print("VERIFY %s -> %s" % (tag, report["verdict"]), flush=True)
    return ok


def main():
    print("ENSO_SIDE_BLENDER:", bpy.app.version_string, flush=True)
    ok_after = run_verify(before_p, after_p, "enso-after")
    ok_cycle = run_verify(before_p, cycle_p, "enso-cycle")

    bpy.ops.wm.open_mainfile(filepath=after_p)
    obj = bpy.context.scene.objects[target]
    pairs = sorted(
        tuple(sorted(int(v) for v in e.vertices))
        for e in obj.data.edges if e.use_seam)
    with open(seams_p, "w") as f:
        json.dump({"object": target, "seam_pairs": [list(p) for p in pairs]}, f, indent=1)
    print("SEAM_PAIRS_DUMPED: %d" % len(pairs), flush=True)
    print("ENSO_SIDE_DONE after=%s cycle=%s" % (ok_after, ok_cycle), flush=True)


main()
