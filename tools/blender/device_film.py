"""Physio Buddy device film, v2: clean Blender footage (no captions) plus per-frame tracking data for the Remotion edit.

    blender -b --factory-startup -P tools/blender/device_film.py -- <shot|all|test> [--engine cycles|eevee] [--samples 96]

Shots (frame counts match the Remotion timeline in video/src/timeline.ts):
    product   135  upper-arm unit explodes and reassembles on a cyclorama, slow orbit
    rail       90  pod slides onto its base along the PB-rail and latches
    family     75  upper-arm, forearm and waist units side by side
    reveal    150  the patient wearing all three units, camera arcs around
    flexion   180  forward raise
    abduction 150  side raise
    rotation  120  outward rotation, elbow at 90 deg

Frames go to hardware/renders/frames/v2/<shot>/####.png. Tracking data goes to video/public/data/<shot>.json:
screen positions (pixels) of the units / components for the callouts, and for the exercise shots the arm angles
measured from the posed skeleton (geometry, the same way the station measures them; nothing is typed in by hand).
`test` (or `<shot> --still [--at 0.55]`) renders one frame per shot to hardware/renders/test_v2_<shot>.png.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device_on_avatar as D  # noqa: E402  (scene helpers, avatar build, poses)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOT = argv[0] if argv else "test"


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


ENGINE = opt("--engine", "cycles")
SAMPLES = int(opt("--samples", "96"))
ROOT = D.ROOT
FRAMES = (ROOT / "hardware" / "renders" / "frames" / "v2").resolve()
DATA = (ROOT / "video" / "public" / "data").resolve()
W, H = D.RES
LENGTHS = {"product": 135, "rail": 90, "family": 75, "reveal": 150, "flexion": 180, "abduction": 150, "rotation": 120}
TEAL = (0.31, 0.78, 0.65)


# ------------------------------------------------------------------------------------------------ look
def setup(sc):
    if ENGINE == "cycles":
        sc.render.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                if any(d.type == backend for d in prefs.devices):
                    break
            except TypeError:
                continue
        for d in prefs.devices:
            d.use = d.type == prefs.compute_device_type      # NVIDIA only: not the Intel iGPU, not the CPU
        sc.cycles.device = "GPU"
        sc.cycles.samples = SAMPLES
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.use_denoising = True
        if prefs.compute_device_type == "OPTIX":
            sc.cycles.denoiser = "OPTIX"       # OIDN took ~35 s a frame here; the OptiX denoiser runs on the RTX GPU
        sc.cycles.max_bounces = 6
        sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
    else:
        sc.render.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = SAMPLES
        if hasattr(sc.eevee, "use_raytracing"):
            sc.eevee.use_raytracing = True
    sc.render.use_motion_blur = True
    sc.render.motion_blur_shutter = 0.5
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.view_settings.exposure = float(opt("--exposure", "-0.1"))
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    world = sc.world.node_tree.nodes["Background"]
    world.inputs[0].default_value = (0.012, 0.016, 0.022, 1)
    world.inputs[1].default_value = 0.35


def cyclorama(scale=1.0, colour=(0.008, 0.01, 0.013, 1), y_wall=2.4):
    """Seamless studio sweep: floor curving up into a back wall at +Y (the avatar faces -Y, cameras sit at -Y)."""
    import bmesh
    bm = bmesh.new()
    prof = [(-6.0, 0.0), (y_wall - 1.4, 0.0)]
    r = 1.4
    for i in range(1, 13):
        a = math.radians(90 * i / 12)
        prof.append((y_wall - r + r * math.sin(a), r - r * math.cos(a)))
    prof.append((y_wall, 6.0))
    half = 8.0
    rows = []
    for y, z in prof:
        rows.append((bm.verts.new((-half * scale, y * scale, z * scale)), bm.verts.new((half * scale, y * scale, z * scale))))
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    me = bpy.data.meshes.new("cyclorama")
    bm.to_mesh(me)
    ob = bpy.data.objects.new("cyclorama", me)
    bpy.context.scene.collection.objects.link(ob)
    for p in me.polygons:
        p.use_smooth = True
    m = D.mat("cyc", colour, 0.85)   # matte: no softbox reflections on the sweep
    m.node_tree.nodes["Principled BSDF"].inputs["Specular IOR Level"].default_value = 0.12   # 4 % F0 would read grey
    ob.data.materials.append(m)
    return ob


def area(name, loc, energy, size, colour=(1, 1, 1), target=(0, 0, 1.1), shape="RECTANGLE", size_y=None, spread=None):
    o = D.light(name, loc, energy, size, colour, target)
    o.data.shape = shape
    if spread:
        o.data.spread = math.radians(spread)   # focused softbox: a pool of light, the floor falls off to dark
    if size_y:
        o.data.size_y = size_y
    return o


def spot(name, loc, energy, target, angle=60, blend=1.0, colour=(1, 1, 1)):
    l = bpy.data.lights.new(name, "SPOT")
    l.energy, l.color = energy, colour
    l.spot_size, l.spot_blend = math.radians(angle), blend
    o = bpy.data.objects.new(name, l)
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(o)
    return o


def body_lights():
    area("key", (1.8, -2.6, 2.9), 900, 2.4, (1.0, 0.97, 0.93), size_y=1.6)
    area("fill", (-2.6, -2.0, 1.3), 180, 3.0, (0.82, 0.88, 1.0))
    area("rim_teal", (1.7, 1.6, 2.3), 700, 1.0, (0.55, 1.0, 0.85), target=(0, 0, 1.25))
    area("rim_cool", (-1.8, 1.5, 2.2), 450, 1.0, (0.72, 0.82, 1.0), target=(0, 0, 1.25))
    spot("wall_glow", (0.0, -0.5, 3.4), 1500, (0.0, 2.4, 1.3), angle=55, colour=(0.45, 0.95, 0.82))


def product_lights(c=(0, 0, 0.015)):
    area("key", (0.22, -0.28, 0.32), 6, 0.28, (1.0, 0.97, 0.93), target=c, spread=28)
    area("fill", (-0.34, -0.16, 0.10), 2.5, 0.4, (0.82, 0.88, 1.0), target=c, spread=40)
    area("rim_teal", (0.18, 0.26, 0.16), 7, 0.12, (0.55, 1.0, 0.85), target=c, spread=35)
    area("rim_cool", (-0.2, 0.24, 0.18), 4.5, 0.12, (0.72, 0.82, 1.0), target=c, spread=35)
    spot("wall_glow", (0.0, -0.05, 0.4), 22, (0.0, 0.24, 0.06), angle=55, colour=(0.45, 0.95, 0.82))


# ------------------------------------------------------------------------------------------------ tracking
def screen(sc, cam, world_co):
    v = world_to_camera_view(sc, cam, world_co)
    return [round(v.x * W, 1), round((1 - v.y) * H, 1), bool(v.z > 0 and 0 <= v.x <= 1 and 0 <= v.y <= 1)]


def centre(obj):
    """World-space bounding-box centre of a mesh object."""
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return sum(pts, Vector()) / 8


def render_shot(sc, cam, f0, name, track):
    """Render LENGTHS[name] frames from f0 and write per-frame tracking data (track(frame) -> dict)."""
    n = LENGTHS[name]
    rows = []
    for i in range(n):
        sc.frame_set(f0 + i)
        rows.append(track(f0 + i))
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{name}.json").write_text(json.dumps({"shot": name, "fps": D.FPS, "width": W, "height": H,
                                                    "frames": rows}, separators=(",", ":")), encoding="utf-8")
    sc.camera = cam
    if SHOT == "test" or "--still" in argv:
        sc.frame_set(f0 + int(n * float(opt("--at", "0.55"))))
        sc.render.filepath = str((ROOT / "hardware" / "renders" / f"test_v2_{name}.png").resolve())
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)
        return
    d = FRAMES / name
    d.mkdir(parents=True, exist_ok=True)
    if "--frames" in argv:      # re-render part of a shot (offsets within it), keeping the frames already there
        a = int(argv[argv.index("--frames") + 1])
        b = int(argv[argv.index("--frames") + 2])
        sc.frame_start, sc.frame_end = f0 + a, f0 + b
        sc.render.filepath = str(d) + "/"
        bpy.ops.render.render(animation=True)
        print("rendered", name, f"frames {a}-{b}")
        return
    for old in d.glob("*.png"):
        old.unlink()
    sc.frame_start, sc.frame_end = f0, f0 + n - 1
    sc.render.filepath = str(d) + "/"
    bpy.ops.render.render(animation=True)
    print("rendered", name, n, "frames")


def local_dir(o, world_axis):
    """Local-space vector for 1 mm of world travel along `world_axis`. The glTF import turns the CAD's Z-up into
    Y-up on the unit's parent empty, so 'up' is not local Z."""
    bpy.context.view_layer.update()            # the 0.001 root scale is not in matrix_world until an update
    return (o.parent.matrix_world.to_3x3().inverted() @ Vector(world_axis)) * 0.001


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)       # smootherstep


# ------------------------------------------------------------------------------------------------ product shots
def graphite(parts):
    """Strap bases print in black PETG: give them a satin graphite finish that still reads on the dark floor."""
    m = D.mat("graphite", (0.035, 0.038, 0.042, 1), 0.38)
    for o in parts:
        if o.name.startswith("base"):
            o.data.materials.clear()
            o.data.materials.append(m)


def product_look(sc):
    """Product shots: the focused softboxes are strong at 0.3 m, so expose about two stops down."""
    sc.view_settings.view_transform = opt("--view", "AgX")
    sc.view_settings.look = "AgX - Medium High Contrast" if sc.view_settings.view_transform == "AgX" else "None"
    sc.view_settings.exposure = float(opt("--pexposure", "-2.0"))


def unit_scene(name="unit_upperarm"):
    sc = D.reset()
    setup(sc)
    product_look(sc)
    cyclorama(scale=0.06, y_wall=2.4)
    product_lights()
    root, parts = D.import_unit(name)
    graphite(parts)
    return sc, root, {o.name.split(".")[0]: o for o in parts}


EXPLODE = {"lid": 36.0, "lipo": 24.0, "drv2605": 24.0, "deck": 15.0, "bno085": 7.5, "xiao": 7.5, "switch": 7.5,
           "motor": 4.0}
LABELS = {"lid": "Snap lid", "lipo": "500 mAh LiPo", "drv2605": "DRV2605L haptics", "bno085": "BNO085 IMU",
          "xiao": "XIAO ESP32-S3", "base": "PB-rail strap base", "body": "Pod body"}


def shot_product():
    sc, root, parts = unit_scene()
    n = LENGTHS["product"]
    for key, o in parts.items():
        lift = EXPLODE.get(key)
        if lift is None:
            continue
        p0, up = o.location.copy(), local_dir(o, (0, 0, 1))
        for i in range(n):
            t = i / (n - 1)
            f = ease((t - 0.10) / 0.27) - ease((t - 0.72) / 0.22)
            o.location = p0 + up * (lift * f)
            o.keyframe_insert("location", frame=1 + i)
    cam, tgt = D.camera("cam_product", (0, 0, 0), (0.004, 0, 0.03), 60)
    cam.data.dof.aperture_fstop = 5.6
    for i in range(0, n, 3):
        t = i / (n - 1)
        a = math.radians(-38 + 60 * t)
        r = 0.30 - 0.03 * math.sin(math.pi * t)
        cam.location = (r * math.sin(a), -r * math.cos(a), 0.13 + 0.03 * math.sin(math.pi * t))
        cam.keyframe_insert("location", frame=1 + i)

    def track(f):
        return {k: screen(sc, cam, centre(parts[k])) for k in LABELS if k in parts}
    render_shot(sc, cam, 1, "product", track)


def shot_rail():
    sc, root, parts = unit_scene()
    n = LENGTHS["rail"]
    pod = [o for k, o in parts.items() if k != "base"]
    click = 60                                           # frame (1-based) where the latch engages
    for o in pod:
        p0, along = o.location.copy(), local_dir(o, (1, 0, 0))
        for i in range(n):
            f = 1 + i
            if f <= 12:
                dx = 70.0
            elif f <= click:
                dx = 70.0 * (1 - ease((f - 12) / (click - 12)) ** 0.85)
            else:
                dx = -0.35 * math.exp(-(f - click) / 3.0) * math.cos((f - click) * 1.3)  # tiny settle at the stop
            o.location = p0 + along * dx
            o.keyframe_insert("location", frame=f)
    cam, tgt = D.camera("cam_rail", (0.04, -0.235, 0.085), (0.03, 0, 0.012), 40)
    cam.data.dof.aperture_fstop = 4.0
    cam.keyframe_insert("location", frame=1)
    cam.location = (0.03, -0.215, 0.075)
    cam.keyframe_insert("location", frame=n)

    def track(f):
        return {"pod": screen(sc, cam, centre(parts["lid"])), "base": screen(sc, cam, centre(parts["base"])),
                "click": f == click}
    render_shot(sc, cam, 1, "rail", track)


def shot_family():
    sc = D.reset()
    setup(sc)
    product_look(sc)
    cyclorama(scale=0.08, y_wall=2.4)
    product_lights((0, 0, 0.012))
    n = LENGTHS["family"]
    roots = {}
    for name, x in (("unit_forearm", -0.085), ("unit_upperarm", 0.0), ("unit_waist", 0.09)):
        r, ps = D.import_unit(name)
        graphite(ps)
        r.location = (x, 0, 0)
        r.rotation_mode = "XYZ"
        for f, a in ((1, -24), (n, 12)):
            r.rotation_euler = (0, 0, math.radians(a))
            r.keyframe_insert("rotation_euler", index=2, frame=f)
        roots[name.replace("unit_", "")] = r
    cam, tgt = D.camera("cam_family", (0.014, -0.40, 0.17), (0.014, 0, 0.036), 50)
    cam.data.dof.aperture_fstop = 8.0
    cam.keyframe_insert("location", frame=1)
    cam.location = (0.004, -0.37, 0.15)
    cam.keyframe_insert("location", frame=n)

    def track(f):
        return {k: screen(sc, cam, r.matrix_world @ Vector((4.0, 0, 34.0))) for k, r in roots.items()}
    render_shot(sc, cam, 1, "family", track)


# ------------------------------------------------------------------------------------------------ avatar shots
AV = {"reveal": 1, "flexion": 151, "abduction": 331, "rotation": 481}   # first frame of each shot on the avatar timeline


def angles(arm):
    """Shoulder elevation (humerus vs trunk axis) and external rotation (forearm in the horizontal plane), degrees."""
    b = D.BONES
    sh, _, _ = D.bone_world(arm, b["arm"])
    el, _, _ = D.bone_world(arm, b["fore"])
    wr, _, _ = D.bone_world(arm, b["hand"])
    pv, _, _ = D.bone_world(arm, b["pelvis"])
    nk, _, _ = D.bone_world(arm, b["neck"])
    trunk_up = (nk - pv).normalized()
    hum = (el - sh).normalized()
    elev = math.degrees(hum.angle(-trunk_up))
    fore = wr - el
    fh = Vector((fore.x, fore.y, 0))
    out = -1 if D.SIDE == "right" else 1
    er = math.degrees(math.atan2(out * fh.x, -fh.y)) if fh.length > 1e-4 else 0.0
    return round(elev, 1), round(er, 1)


def avatar_scene():
    sc, arm, units, _ = D.build()
    setup(sc)
    # replace the v1 studio (round floor + lights) with the sweep and the film lights
    for o in list(bpy.data.objects):
        if o.type == "LIGHT" or o.name.startswith("floor"):
            bpy.data.objects.remove(o)
    cyclorama(scale=1.0, y_wall=2.4)
    body_lights()
    D.reset_pose(arm)
    D.pose_neutral(arm)
    # timeline: reveal holds the neutral pose, then the three exercises (same rep shapes as v1)
    for i in range(0, LENGTHS["reveal"], 10):
        D.key_pose(arm, AV["reveal"] + i, 6, 4)
    for name in ("flexion", "abduction", "rotation"):
        f0, n = AV[name], LENGTHS[name]
        for i in range(0, n, 2):
            if name == "flexion":
                D.key_pose(arm, f0 + i, 6 + D.rep(i, n, 134), 4)
            elif name == "abduction":
                D.key_pose(arm, f0 + i, 6 + D.rep(i, n, 104), 88)
            else:
                D.key_pose(arm, f0 + i, 6, 10, er=D.rep(i, n, 50, rise=0.25, hold=0.4))
    for act in bpy.data.actions:
        for fc in getattr(act, "fcurves", []):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
    return sc, arm, units


def pod_points(units):
    lift = Vector((4.0, 0, 16.0))        # middle of the pod above the base origin (mm, unit frame)
    return {k: (u.matrix_world @ lift) for k, u in units.items()}


def avatar_cameras():
    side = -1 if D.SIDE == "right" else 1
    cams = {}
    c, t = D.camera("cam_reveal", (0, 0, 0), (0.0, 0.0, 1.12), 35)
    c.data.dof.aperture_fstop = 2.8
    n = LENGTHS["reveal"]
    for i in range(0, n, 5):
        u = i / (n - 1)
        a = math.radians(-50 + 75 * D.smooth(u))
        r = 3.4 - 0.9 * D.smooth(u)
        c.location = (r * math.sin(a), -r * math.cos(a), 1.35 + 0.15 * u)
        c.keyframe_insert("location", frame=AV["reveal"] + i)
    cams["reveal"] = c
    c, t = D.camera("cam_flexion", (1.7, -2.8, 1.5), (0.0, 0.0, 1.25), 40)
    c.data.dof.aperture_fstop = 2.8
    c.keyframe_insert("location", frame=AV["flexion"])
    c.location = (2.3, -2.2, 1.45)
    c.keyframe_insert("location", frame=AV["flexion"] + LENGTHS["flexion"] - 1)
    cams["flexion"] = c
    c, t = D.camera("cam_abduction", (side * 0.4, -2.6, 1.45), (side * 0.25, 0.0, 1.35), 42)
    c.data.dof.aperture_fstop = 2.8
    c.keyframe_insert("location", frame=AV["abduction"])
    c.location = (side * 0.9, -2.3, 1.5)
    c.keyframe_insert("location", frame=AV["abduction"] + LENGTHS["abduction"] - 1)
    cams["abduction"] = c
    c, t = D.camera("cam_rotation", (side * 0.8, -1.6, 1.7), (side * 0.2, -0.1, 1.12), 45)
    c.data.dof.aperture_fstop = 2.8
    c.keyframe_insert("location", frame=AV["rotation"])
    c.location = (side * 0.45, -1.7, 1.65)
    c.keyframe_insert("location", frame=AV["rotation"] + LENGTHS["rotation"] - 1)
    cams["rotation"] = c
    return cams


def shots_avatar(which):
    sc, arm, units = avatar_scene()
    cams = avatar_cameras()
    for name in which:
        cam = cams[name]

        def track(f, cam=cam):
            pts = pod_points(units)
            elev, er = angles(arm)
            return {"upperarm": screen(sc, cam, pts["upperarm"]), "forearm": screen(sc, cam, pts["forearm"]),
                    "trunk": screen(sc, cam, pts["chest"]), "elevation": elev, "rotation": er}
        render_shot(sc, cam, AV[name], name, track)


if __name__ == "__main__":
    avatar = [s for s in ("reveal", "flexion", "abduction", "rotation")]
    if SHOT in ("all", "test"):
        shot_product()
        shot_rail()
        shot_family()
        shots_avatar(avatar)
    elif SHOT == "avatar":
        shots_avatar(avatar)
    elif SHOT in avatar:
        shots_avatar([SHOT])
    else:
        {"product": shot_product, "rail": shot_rail, "family": shot_family}[SHOT]()
