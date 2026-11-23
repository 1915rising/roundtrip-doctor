"""
Return-leg seam application. Runs inside Blender 4.2.3:

  blender -b --python tests/apply_seams.py -- BEFORE.blend SEAMS.json OUT.blend APPLIED.json

Opens the BEFORE file (native 4.2), sets the target object's seam
flags to exactly the seam set dumped from the Ensō seat
(tests/enso_side.py, as vertex-index pairs), saves OUT.blend, and
records the applied edge indices in APPLIED.json so the driver can
check the verifier's reported delta against them.

This is how seam work done in a Blender 5.x sidecar seat gets back
into a 4.2 pipeline file: the 5.x .blend itself cannot be read by
4.2 (new file format), but the seam set is just data, and it is
re-applied here -- after which roundtrip_doctor.py gates the
returned file like any other AFTER file.
"""

import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
in_p, seams_p, out_p, applied_p = argv[:4]

with open(seams_p) as f:
    spec = json.load(f)
target_pairs = {tuple(p) for p in spec["seam_pairs"]}
obj_name = spec["object"]

bpy.ops.wm.open_mainfile(filepath=in_p)
obj = bpy.context.scene.objects[obj_name]
applied = []
for e in obj.data.edges:
    pair = tuple(sorted(int(v) for v in e.vertices))
    e.use_seam = pair in target_pairs
    if e.use_seam:
        applied.append(e.index)
obj.data.update()
print("APPLIED %d seams on %s" % (len(applied), obj_name), flush=True)

with open(applied_p, "w") as f:
    json.dump({"object": obj_name, "applied_edge_indices": applied}, f, indent=1)
bpy.ops.wm.save_as_mainfile(filepath=out_p)
print("SAVED:", out_p, flush=True)
