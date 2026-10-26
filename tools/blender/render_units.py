"""Product renders of the CAD assemblies (GLB from hardware/cad/physio_pod.py): hero + exploded view per unit.

    blender -b --factory-startup -P tools/blender/render_units.py -- hardware/cad/out/glb hardware/renders [samples]

EEVEE, studio lighting. Exploded view lifts lid, deck and electronics along +Z so the inside is visible.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = Path(argv[0]).resolve(), Path(argv[1]).resolve()   # Blender needs absolute output paths
samples = int(argv[2]) if len(argv) > 2 else 32
out.mkdir(parents=True, exist_ok=True)

EXPLODE = {"lid": 34.0, "lipo": 22.0, "drv2605": 22.0, "deck": 14.0, "bno085": 7.0, "xiao": 7.0, "switch": 7.0,
           "motor": 4.0, "body": 0.0, "base": -6.0}


def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = samples
    sc.render.resolution_x, sc.render.resolution_y = 1600, 1000
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.045, 0.055, 0.07, 1)
    bg.inputs[1].default_value = 0.6
    sc.world = world
    for name, loc, energy, size in (("key", (0.25, -0.3, 0.35), 40, 0.25), ("fill", (-0.35, -0.15, 0.12), 12, 0.4), ("rim", (0, 0.35, 0.25), 25, 0.2)):
        l = bpy.data.lights.new(name, "AREA")
        l.energy, l.size = energy, size
        o = bpy.data.objects.new(name, l)
        o.location = loc
        o.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(o)
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
    floor = bpy.context.object
    m = bpy.data.materials.new("floor")
    m.diffuse_color = (0.05, 0.06, 0.075, 1)
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.06, 0.075, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.35
    floor.data.materials.append(m)
    return sc, floor


def import_unit(path):
    """Import a CadQuery GLB. Its numbers are millimetres, so the top-level objects are scaled to metres."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.parent is None:
            o.scale = tuple(s * 0.001 for s in o.scale)
            o.location = o.location * 0.001
    bpy.context.view_layer.update()
    objs = [o for o in new if o.type == "MESH"]
    # make materials a little nicer: satin plastic
    for o in objs:
        for slot in o.material_slots:
            if slot.material and slot.material.use_nodes:
                p = slot.material.node_tree.nodes.get("Principled BSDF")
                if p:
                    p.inputs["Roughness"].default_value = 0.42
    return objs


def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def part_key(o):
    n = o.name.lower()
    for k in EXPLODE:
        if k in n:
            return k
    return None


def render(sc, objs, floor, name, exploded):
    def shift(sign):
        # world-space offset: imported meshes sit under a scaled (mm -> m) parent
        for o in objs:
            k = part_key(o)
            if k:
                mw = o.matrix_world.copy()
                mw.translation.z += sign * EXPLODE[k] * unit_scale
                o.matrix_world = mw
        bpy.context.view_layer.update()

    if exploded:
        shift(+1)
    lo, hi = bounds(objs)
    floor.location.z = lo.z - 0.0005
    centre = (lo + hi) / 2
    span = max((hi - lo).length, 1e-3)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 85
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    cam.location = centre + Vector((1.0, -1.35, 0.85 if not exploded else 0.55)).normalized() * span * 3.1
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.clip_start, cam_data.clip_end = span * 0.01, span * 50
    sc.camera = cam
    sc.render.filepath = str(out / f"{name}_{'exploded' if exploded else 'hero'}.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", sc.render.filepath)
    if exploded:
        shift(-1)
    bpy.data.objects.remove(cam)


for glb in sorted(src.glob("unit_*.glb")):
    sc, floor = setup_scene()
    objs = import_unit(glb)
    lo, hi = bounds(objs)
    unit_scale = 0.001       # explode offsets are given in mm
    print(f"{glb.stem}: size {tuple(round(v * 1000, 1) for v in (hi - lo))} mm")
    for exploded in (False, True):
        render(sc, objs, floor, glb.stem, exploded)
