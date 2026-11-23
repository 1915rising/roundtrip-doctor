"""
Ensō-side half of the gown round-trip test. Runs INSIDE Ensō
(Blender 5.3 under Wine) -- see gown_roundtrip.py for the driver.

  blender.exe -b --python enso_trip_gown.py -- BEFORE AFTER CYCLE DRAWN.json

Opens BEFORE (a copy of the Christmas gown blend), paints a
43-edge connected seam chain onto GenGown through Sculpt UVs' own
validated write path (SurfaceCache.apply -- the function every brush
stroke ends in; the stroke operator itself is modal and cannot be
driven headless), and saves AFTER. Then reopens AFTER, erases the
chain back off, and saves CYCLE (the full draw+erase round trip).

DRAWN.json records the target object, the exact chain painted, and
the seam counts, so the 4.2.3-side verifier's delta can be checked
against ground truth rather than against itself.
"""

import json
import os
import sys

import bmesh
import bpy

CHAIN_TARGET = 43
SCULPT_UVS_ZIP = r"Z:\home\hatch\workspace\tools\sculpt-uvs\add-on-sculpt-uvs-v1.0.0.zip"


def ensure_sculpt_uvs():
    try:
        from bl_ext.user_default.sculpt_uvs.surface import SurfaceCache  # noqa: F401
        print("SCULPT_UVS: already installed", flush=True)
        return
    except ImportError:
        pass
    r = bpy.ops.extensions.package_install_files(
        filepath=SCULPT_UVS_ZIP, repo="user_default", enable_on_install=True)
    print("SCULPT_UVS: install result %s" % (r,), flush=True)
    from bl_ext.user_default.sculpt_uvs.surface import SurfaceCache  # noqa: F401


def make_cache(obj):
    from bl_ext.user_default.sculpt_uvs.surface import SurfaceCache
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    for els in (bm.verts, bm.edges, bm.faces):
        els.ensure_lookup_table()
        els.index_update()
    cache = SurfaceCache.__new__(SurfaceCache)
    cache.mesh = obj.data
    cache.edges = [tuple(v.index for v in e.verts) for e in bm.edges]
    cache.positions = [v.co.copy() for v in bm.verts]
    cache.seams = {e.index for e in bm.edges if e.seam}
    return bm, cache


def walk_chain(bm, target_len):
    """A connected chain of edges, walking across shared faces
    (same method as the original Sculpt UVs verification)."""
    edge_faces = {}
    for f in bm.faces:
        for e in f.edges:
            edge_faces.setdefault(e.index, []).append(f.index)
    face_edges = {f.index: [e.index for e in f.edges] for f in bm.faces}
    chain, used = [], set()
    cur = bm.edges[0].index
    while len(chain) < target_len:
        if cur in used:
            break
        used.add(cur)
        chain.append(cur)
        nxt = None
        for fi in edge_faces.get(cur, []):
            for ei in face_edges[fi]:
                if ei not in used:
                    nxt = ei
                    break
            if nxt is not None:
                break
        if nxt is None:
            break
        cur = nxt
    return chain


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    before_p, after_p, cycle_p, drawn_p = argv[:4]
    print("ENSO_BLENDER_VERSION:", bpy.app.version_string, flush=True)
    ensure_sculpt_uvs()

    bpy.ops.wm.open_mainfile(filepath=before_p)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    obj = bpy.context.scene.objects.get("GenGown") or \
        max(meshes, key=lambda o: len(o.data.polygons))
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    print("TARGET_OBJECT:", obj.name, "polys:", len(obj.data.polygons), flush=True)

    bm, cache = make_cache(obj)
    original_seams = set(cache.seams)
    chain = walk_chain(bm, CHAIN_TARGET)
    print("CHAIN_LEN:", len(chain), flush=True)
    target = original_seams | set(chain)
    changed = cache.apply(target)
    print("APPLY_DRAW_RETURNED:", changed, flush=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.wm.save_as_mainfile(filepath=after_p)
    print("SAVED_AFTER:", after_p, flush=True)

    with open(drawn_p, "w") as f:
        json.dump({"object": obj.name,
                   "chain": sorted(chain),
                   "seams_before": sorted(original_seams),
                   "seams_after": sorted(target)}, f, indent=1)
    print("DRAWN_JSON_WRITTEN", flush=True)

    # Full cycle: reopen the saved AFTER file, erase back to the
    # original seam set, save as CYCLE.
    target_name = obj.name
    bpy.ops.wm.open_mainfile(filepath=after_p)
    obj = bpy.context.scene.objects[target_name]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bm2, cache2 = make_cache(obj)
    print("CYCLE_SEAMS_BEFORE_ERASE:", len(cache2.seams), flush=True)
    changed2 = cache2.apply(set(original_seams))
    print("APPLY_ERASE_RETURNED:", changed2, flush=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.wm.save_as_mainfile(filepath=cycle_p)
    print("SAVED_CYCLE:", cycle_p, flush=True)
    print("ENSO_TRIP_DONE", flush=True)


main()
