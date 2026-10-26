"""Render an STL from 4 views (iso, front, side, top) into one contact sheet, with a 10 mm grid for scale.

    blender -b --factory-startup -P tools/cad/render_stl.py -- part.stl out_dir

Writes out_dir/<name>_{iso,front,side,top}.png (Workbench engine, fast and deterministic).
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
stl, out_dir = Path(argv[0]), Path(argv[1])
out_dir.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=str(stl))
obj = bpy.context.selected_objects[0]
# centre on the origin, base on the bed (z = 0)
bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
obj.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
size = hi - lo
span = max(size) * 1.35

# 10 mm grid plane under the part for scale
bpy.ops.mesh.primitive_grid_add(x_subdivisions=int(span // 10) + 2, y_subdivisions=int(span // 10) + 2,
                                size=(int(span // 10) + 1) * 10, location=(0, 0, -0.05))
grid = bpy.context.object
wire = grid.modifiers.new("lines", "WIREFRAME")  # renders as thin 10 mm grid lines (display_type is viewport-only)
wire.thickness = 0.25
grid_mat = bpy.data.materials.new("grid")
grid_mat.diffuse_color = (0.55, 0.55, 0.55, 1)
grid.data.materials.append(grid_mat)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
part_mat = bpy.data.materials.new("part")
part_mat.diffuse_color = (0.85, 0.55, 0.2, 1)
obj.data.materials.append(part_mat)
scene.display.shading.show_cavity = True
scene.display.shading.show_object_outline = True
scene.render.resolution_x, scene.render.resolution_y = 900, 700
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.95, 0.95, 0.95)

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
centre = Vector((0, 0, size.z / 2))

views = {
    "iso": (Vector((1, -1.2, 0.9)), False),
    "front": (Vector((0, -1, 0)), True),
    "side": (Vector((1, 0, 0)), True),
    "top": (Vector((0, 0, 1)), True),
}
for name, (direction, ortho) in views.items():
    d = direction.normalized()
    cam.location = centre + d * span * 2.2
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y" if name == "top" else "Z").to_euler()
    cam_data.type = "ORTHO" if ortho else "PERSP"
    cam_data.ortho_scale = span
    cam_data.lens = 50
    cam_data.clip_end = span * 10
    scene.render.filepath = str(out_dir / f"{stl.stem}_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath)
print(f"size_mm {size.x:.2f} {size.y:.2f} {size.z:.2f}")
