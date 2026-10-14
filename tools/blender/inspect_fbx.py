"""Dump object names + world bounding boxes of an FBX to JSON (for picking anatomy parts)."""
import bpy, sys, json
from mathutils import Vector
argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=argv[0], use_anim=False)
out = []
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = [min(v[i] for v in bb) for i in range(3)]; mx = [max(v[i] for v in bb) for i in range(3)]
    out.append({"name": o.name, "verts": len(o.data.vertices), "min": [round(x, 4) for x in mn], "max": [round(x, 4) for x in mx],
                "parent": o.parent.name if o.parent else None})
json.dump(out, open(argv[1], "w"), indent=0)
print("objects", len(out))
