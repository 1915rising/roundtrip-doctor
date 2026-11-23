"""
Synthetic test suite for roundtrip-doctor. Runs inside Blender:

  blender -b --factory-startup --python tests/run_tests.py

Builds a small mesh, saves a BEFORE file, then produces AFTER variants
and asserts the gate's verdict on each:

  identical copy            -> PASS, zero seam delta
  seams painted only        -> PASS, delta == exactly the painted set
  one vertex moved          -> FAIL (vertices channel named)
  one UV coordinate moved   -> FAIL (uv channel named)
  topology change (split)   -> FAIL (counts named)
  mesh object removed       -> FAIL (missing object named)
  CLI exit codes            -> 0 for the seams-only case, 1 for moved

Prints one line per check and a final "N/N PASS" summary; raises
SystemExit(1) if anything fails.
"""

import os
import subprocess
import sys
import tempfile

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import roundtrip_doctor as rd  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("%s: %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)


def build_base(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # 3x3-vertex grid, 4 quad faces, one UV layer.
    verts = [(x * 0.5, y * 0.5, 0.0) for y in range(3) for x in range(3)]
    faces = [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)]
    me = bpy.data.meshes.new("GridMesh")
    me.from_pydata(verts, [], faces)
    me.update()
    uv = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        uv.data[loop.index].uv = (me.vertices[loop.vertex_index].co.x,
                                  me.vertices[loop.vertex_index].co.y)
    obj = bpy.data.objects.new("Grid", me)
    bpy.context.scene.collection.objects.link(obj)
    # a second, untouched object so multi-object diffs are exercised
    me2 = bpy.data.meshes.new("OtherMesh")
    me2.from_pydata([(0, 0, 1), (1, 0, 1), (0, 1, 1)], [], [(0, 1, 2)])
    me2.update()
    obj2 = bpy.data.objects.new("Other", me2)
    bpy.context.scene.collection.objects.link(obj2)
    bpy.ops.wm.save_as_mainfile(filepath=path)


def open_and(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    return bpy.context.scene.objects["Grid"]


def save(path):
    bpy.ops.wm.save_as_mainfile(filepath=path)


def main():
    tmp = tempfile.mkdtemp(prefix="roundtrip-doctor-tests-")
    before = os.path.join(tmp, "before.blend")

    build_base(before)

    # 1 -- identical copy
    p = os.path.join(tmp, "identical.blend")
    open_and(before)
    save(p)
    ok, rep = rd.verify(before, p)
    e = rep["objects"]["Grid"]
    check("identical copy passes", ok and rep["verdict"] == "PASS")
    check("identical copy has zero seam delta",
          e["seams_added"] == [] and e["seams_removed"] == [])

    # 2 -- seams painted only (edges 0, 3, 5 of Grid)
    painted = {0, 3, 5}
    p = os.path.join(tmp, "seams.blend")
    obj = open_and(before)
    for i in painted:
        obj.data.edges[i].use_seam = True
    save(p)
    ok, rep = rd.verify(before, p)
    e = rep["objects"]["Grid"]
    check("seams-only change passes", ok)
    check("seam delta is exactly the painted set",
          set(e["seams_added"]) == painted and e["seams_removed"] == [],
          "added=%s" % (e["seams_added"],))
    check("untouched second object passes too",
          rep["objects"]["Other"]["status"] == "PASS")

    # 3 -- one vertex moved
    p = os.path.join(tmp, "moved.blend")
    obj = open_and(before)
    obj.data.vertices[4].co.x += 0.01
    save(p)
    ok, rep = rd.verify(before, p)
    e = rep["objects"]["Grid"]
    check("moved vertex fails the gate", not ok)
    check("moved vertex names the vertices channel",
          "vertices" in e["changed_channels"], str(e["changed_channels"]))

    # 4 -- one UV coordinate moved
    p = os.path.join(tmp, "uv_moved.blend")
    obj = open_and(before)
    layer = obj.data.uv_layers["UVMap"]
    layer.data[0].uv = (0.99, 0.99)
    save(p)
    ok, rep = rd.verify(before, p)
    e = rep["objects"]["Grid"]
    check("moved UV fails the gate", not ok)
    check("moved UV names the uv channel",
          any("uv" in c for c in e["changed_channels"]),
          str(e["changed_channels"]))

    # 5 -- topology change: split the mesh by adding a vertex + face
    p = os.path.join(tmp, "topo.blend")
    obj = open_and(before)
    me = obj.data
    me.vertices.add(1)
    me.vertices[-1].co = (2.0, 2.0, 0.0)
    me.update()
    save(p)
    ok, rep = rd.verify(before, p)
    check("topology/count change fails the gate", not ok)

    # 6 -- object removed
    p = os.path.join(tmp, "missing.blend")
    open_and(before)
    other = bpy.context.scene.objects["Other"]
    bpy.data.objects.remove(other, do_unlink=True)
    save(p)
    ok, rep = rd.verify(before, p)
    check("removed object fails the gate", not ok)
    check("removed object is named",
          rep["objects"]["Other"]["status"] == "FAIL")

    # 7 -- CLI exit codes end to end
    script = os.path.join(REPO, "roundtrip_doctor.py")
    seams_p = os.path.join(tmp, "seams.blend")
    moved_p = os.path.join(tmp, "moved.blend")
    for label, after_p, want in (("seams-only", seams_p, 0),
                                 ("moved-vertex", moved_p, 1)):
        r = subprocess.run(
            [bpy.app.binary_path, "-b", "--factory-startup",
             "--python", script, "--", before, after_p],
            capture_output=True, text=True)
        check("CLI exit code %d for %s" % (want, label),
              r.returncode == want, "got %d" % r.returncode)

    passed = sum(1 for _, c in RESULTS if c)
    print("TESTS: %d/%d PASS" % (passed, len(RESULTS)), flush=True)
    if passed != len(RESULTS):
        raise SystemExit(1)


main()
