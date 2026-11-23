"""
Negative-test fixture builder. Runs inside Blender 4.2.3:

  blender -b --python tests/move_vertex.py -- IN.blend OUT.blend OBJECT VERTEX_INDEX DX

Opens IN.blend, moves one vertex of OBJECT by (DX, 0, 0), saves
OUT.blend. Everything else is untouched -- so a correct verifier
must FAIL this pair and name the vertices channel.
"""

import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
in_p, out_p, obj_name, vi, dx = argv[0], argv[1], argv[2], int(argv[3]), float(argv[4])

bpy.ops.wm.open_mainfile(filepath=in_p)
obj = bpy.context.scene.objects[obj_name]
v = obj.data.vertices[vi]
print("MOVING %s vertex %d from %s by dx=%s" % (obj_name, vi, tuple(v.co), dx))
v.co.x += dx
obj.data.update()
bpy.ops.wm.save_as_mainfile(filepath=out_p)
print("SAVED:", out_p)
