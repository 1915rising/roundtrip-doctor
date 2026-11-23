#!/usr/bin/env python3
"""
roundtrip_doctor.py -- verify that a Blender sidecar trip changed only
seam flags, and nothing else.

Some Blender tools only exist for Blender 5.x (extensions with a 5.0+
version floor), while production pipelines sit on the 4.2 LTS. The
working pattern is a sidecar trip: take the .blend into the 5.x seat,
do the one job only that seat can do (the motivating case: painting
UV seam flags with Sculpt UVs in a Blender 5.3 fork), save, and bring
the file back to 4.2. Seam flags are plain mesh data and travel with
the file -- but "travels fine" was, until this tool, a claim verified
by hand exactly once.

roundtrip-doctor turns that trip into a gated operation. Give it the
.blend from BEFORE the trip and the .blend from AFTER, and it diffs
every mesh object in Blender 4.2.3:

  * SHA256 of vertex coordinates
  * SHA256 of edge topology (vertex pairs)
  * SHA256 of face topology (loop structure + loop vertex indices)
  * SHA256 of every UV layer's coordinates
  * the seam-flag set, reported as an explicit added/removed delta

Verdict: PASS only if every non-seam channel is byte-identical and
the only difference anywhere is seam flags. Anything else -- a moved
vertex, a retriangulated face, a touched UV, a missing object --
fails the gate and is named in the report.

Usage (inside Blender, background mode is fine):

  blender -b --python roundtrip_doctor.py -- BEFORE.blend AFTER.blend
      [--object NAME] [--json report.json] [--report report.txt]

Exit codes: 0 = PASS (only seam flags changed), 1 = FAIL (something
else changed), 2 = usage / file error.

The module is also importable from a Blender Python session:

  import roundtrip_doctor as rd
  ok, report = rd.verify("before.blend", "after.blend")

Copyright (c) 2026 1915rising -- MIT License (see LICENSE).
"""

import hashlib
import json
import os
import sys

import bpy
import numpy as np

__version__ = "1.0.0"

CHANNELS = ("vertices", "edges", "faces", "uvs")


# ---------------------------------------------------------------------------
# Snapshot: hash the mesh data channels of every mesh object in a file.
# ---------------------------------------------------------------------------

def _sha(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()


def snapshot_object(obj):
    """Hash all gated channels of one mesh object. Returns a dict."""
    me = obj.data
    nv = len(me.vertices)
    ne = len(me.edges)
    nf = len(me.polygons)
    nl = len(me.loops)

    verts = np.empty(nv * 3, dtype=np.float32)
    if nv:
        me.vertices.foreach_get("co", verts)

    edge_pairs = np.empty(ne * 2, dtype=np.int32)
    seam_flags = np.empty(ne, dtype=bool)
    if ne:
        me.edges.foreach_get("vertices", edge_pairs)
        me.edges.foreach_get("use_seam", seam_flags)

    loop_starts = np.empty(nf, dtype=np.int32)
    loop_totals = np.empty(nf, dtype=np.int32)
    loop_verts = np.empty(nl, dtype=np.int32)
    if nf:
        me.polygons.foreach_get("loop_start", loop_starts)
        me.polygons.foreach_get("loop_total", loop_totals)
    if nl:
        me.loops.foreach_get("vertex_index", loop_verts)

    uv_hashes = {}
    for layer in me.uv_layers:
        arr = np.empty(nl * 2, dtype=np.float32)
        if nl:
            layer.data.foreach_get("uv", arr)
        uv_hashes[layer.name] = _sha(arr.tobytes())

    seams = set(int(i) for i in np.flatnonzero(seam_flags))

    return {
        "counts": {"vertices": nv, "edges": ne, "faces": nf, "loops": nl},
        "hashes": {
            "vertices": _sha(verts.tobytes()),
            "edges": _sha(edge_pairs.tobytes()),
            "faces": _sha(loop_starts.tobytes() + loop_totals.tobytes()
                          + loop_verts.tobytes()),
        },
        "uv_layers": uv_hashes,
        "seams": seams,
    }


def snapshot_file(path):
    """Open a .blend and snapshot every mesh object in it."""
    bpy.ops.wm.open_mainfile(filepath=path)
    snap = {}
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            snap[obj.name] = snapshot_object(obj)
    return snap


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_snapshots(before, after, object_filter=None):
    """Compare two snapshots. Returns (ok, per-object report dict)."""
    names = set(before) | set(after)
    if object_filter:
        names &= {object_filter}
    objects = {}
    all_ok = True
    for name in sorted(names):
        entry = {"status": "PASS"}
        if name not in before:
            entry.update(status="FAIL", problem="object only in AFTER file")
            all_ok = False
            objects[name] = entry
            continue
        if name not in after:
            entry.update(status="FAIL", problem="object only in BEFORE file")
            all_ok = False
            objects[name] = entry
            continue
        b, a = before[name], after[name]
        entry["counts"] = b["counts"]
        changed = []
        if b["counts"] != a["counts"]:
            changed.append("counts %s -> %s" % (b["counts"], a["counts"]))
        for ch in ("vertices", "edges", "faces"):
            if b["hashes"][ch] != a["hashes"][ch]:
                changed.append(ch)
        if set(b["uv_layers"]) != set(a["uv_layers"]):
            changed.append("uv layer set %s -> %s"
                           % (sorted(b["uv_layers"]), sorted(a["uv_layers"])))
        else:
            for layer in b["uv_layers"]:
                if b["uv_layers"][layer] != a["uv_layers"][layer]:
                    changed.append("uv layer %r" % layer)
        entry["changed_channels"] = changed
        # Seam delta is only meaningful when edge topology is identical;
        # edge indices are the shared language between the two files.
        if b["hashes"]["edges"] == a["hashes"]["edges"]:
            added = sorted(a["seams"] - b["seams"])
            removed = sorted(b["seams"] - a["seams"])
            entry["seams_before"] = len(b["seams"])
            entry["seams_after"] = len(a["seams"])
            entry["seams_added"] = added
            entry["seams_removed"] = removed
        else:
            entry["seams_comparable"] = False
        if changed:
            entry["status"] = "FAIL"
            all_ok = False
        objects[name] = entry
    return all_ok, objects


def verify(before_path, after_path, object_filter=None):
    """Full gate: snapshot both files and diff. Returns (ok, report)."""
    before = snapshot_file(before_path)
    after = snapshot_file(after_path)
    if object_filter and object_filter not in before and object_filter not in after:
        raise ValueError("object %r not found in either file" % object_filter)
    if not before and not after:
        raise ValueError("no mesh objects in either file")
    ok, objects = diff_snapshots(before, after, object_filter)
    report = {
        "tool": "roundtrip-doctor %s" % __version__,
        "blender": bpy.app.version_string,
        "before": os.path.abspath(before_path),
        "after": os.path.abspath(after_path),
        "object_filter": object_filter,
        "verdict": "PASS" if ok else "FAIL",
        "objects": objects,
    }
    return ok, report


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------

def _fmt_indices(indices, limit=20):
    if indices is None:
        return "n/a"
    if not indices:
        return "none"
    shown = indices[:limit]
    s = ", ".join(str(i) for i in shown)
    if len(indices) > limit:
        s += ", ... (%d total)" % len(indices)
    return s


def format_report(report):
    lines = []
    lines.append("Roundtrip Doctor %s -- Blender %s"
                 % (__version__, report["blender"]))
    lines.append("BEFORE: %s" % report["before"])
    lines.append("AFTER:  %s" % report["after"])
    if report.get("object_filter"):
        lines.append("OBJECT FILTER: %s" % report["object_filter"])
    lines.append("")
    for name in sorted(report["objects"]):
        e = report["objects"][name]
        lines.append("[%s] %s" % (e["status"], name))
        if "problem" in e:
            lines.append("    problem: %s" % e["problem"])
            continue
        c = e["counts"]
        lines.append("    mesh: %d verts | %d edges | %d faces | %d loops"
                     % (c["vertices"], c["edges"], c["faces"], c["loops"]))
        if e.get("changed_channels"):
            lines.append("    CHANGED (not seams): %s"
                         % ", ".join(e["changed_channels"]))
        else:
            lines.append("    vertices/edges/faces/UVs: byte-identical")
        if e.get("seams_comparable") is False:
            lines.append("    seams: NOT comparable (edge topology changed)")
        elif "seams_added" in e:
            lines.append("    seams: %d -> %d (added %d, removed %d)"
                         % (e["seams_before"], e["seams_after"],
                            len(e["seams_added"] or []),
                            len(e["seams_removed"] or [])))
            lines.append("    seams added:   %s" % _fmt_indices(e["seams_added"]))
            lines.append("    seams removed: %s" % _fmt_indices(e["seams_removed"]))
    lines.append("")
    lines.append("VERDICT: %s" % report["verdict"])
    if report["verdict"] == "PASS":
        lines.append("Only seam flags changed. The sidecar trip is clean.")
    else:
        lines.append("Something other than seam flags changed. "
                     "Do not trust this round trip.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    positional = []
    opts = {"object": None, "json": None, "report": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--object", "--json", "--report") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 2
        elif a.startswith("--"):
            raise SystemExit("unknown option: %s" % a)
        else:
            positional.append(a)
            i += 1
    if len(positional) != 2:
        raise SystemExit("usage: roundtrip_doctor.py -- BEFORE.blend AFTER.blend "
                         "[--object NAME] [--json PATH] [--report PATH]")
    return positional[0], positional[1], opts


def main(argv=None):
    argv = sys.argv if argv is None else argv
    try:
        before_path, after_path, opts = _parse_args(argv)
    except SystemExit as e:
        print("ERROR: %s" % e, flush=True)
        os._exit(2)
    for p in (before_path, after_path):
        if not os.path.isfile(p):
            print("ERROR: file not found: %s" % p, flush=True)
            os._exit(2)
    try:
        ok, report = verify(before_path, after_path, opts["object"])
    except Exception as e:
        print("ERROR: %s: %s" % (type(e).__name__, e), flush=True)
        os._exit(2)
    text = format_report(report)
    print(text, flush=True)
    if opts["report"]:
        with open(opts["report"], "w") as f:
            f.write(text + "\n")
    if opts["json"]:
        with open(opts["json"], "w") as f:
            json.dump(report, f, indent=1)
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
