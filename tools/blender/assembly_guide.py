"""Physio Buddy assembly guide: one short Blender clip per build step, plus tracking data for the Remotion edit.

    blender -b --factory-startup -P tools/blender/assembly_guide.py -- <clip|all|test> [--samples 48] [--still --at 0.9]

Everything shown is what the CAD in hardware/cad/physio_pod.py actually has: no screws. The lid clicks on (snap
ridges), the pod locks onto its base with the PB-rail latch, boards sit on rails / corner pads held by ribs and foam
tape, straps thread through the base slots. Wire routes follow agenthandoff.md section 6 (XIAO D4 = SDA, D5 = SCL on
one long edge, 3V3 / GND on the other, LiPo through the slide switch to the BAT pads underneath; Qwiic colours:
black GND, red 3V3, blue SDA, yellow SCL).

Frames: hardware/renders/frames/guide/<clip>/####.png. Tracking: video/public/guide/<clip>.json (pixel positions
of the parts and features the callouts point at). Clip lengths match video/src/guide/steps.ts.
"""

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device_film as F  # noqa: E402  (studio, lights, Cycles setup, camera helper via F.D)

D = F.D
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
CLIP = argv[0] if argv else "test"
ROOT = D.ROOT
FRAMES = (ROOT / "hardware" / "renders" / "frames" / "guide").resolve()
DATA = (ROOT / "video" / "public" / "guide").resolve()
W, H = D.RES

LENGTHS = {"kit": 110, "neoprene": 70, "bno": 70, "motor": 55, "switch": 55, "xiao": 75, "wires": 90, "deck": 50,
           "top": 95, "lid": 60, "forearm": 110, "waist": 100, "strap": 120, "charge": 70, "power": 50}

# CAD facts (hardware/cad/physio_pod.py), pod frame in mm
FLOOR = 2.0
RAIL_H = 3.0
BASE_BOTTOM_C = -(3.0 + 0.25 + 1.8)          # base underside on the centre line (RAIL_H + RAIL_CLR + BASE_FLOOR)
RADIUS = {"unit_upperarm": 46.0, "unit_forearm": 30.0, "unit_waist": 140.0}
SLOT_Y = 30.6 / 2 + 0.5 + 4.5 + 3.6 / 2       # strap slot centre (arm base): strip_y + label_gap + STRAP_T / 2
WING_TOP = -(3.0 + 0.25) + 0.4

COL = {"red": (0.75, 0.04, 0.03, 1), "black": (0.012, 0.012, 0.014, 1), "blue": (0.03, 0.18, 0.8, 1),
       "yellow": (0.85, 0.62, 0.02, 1), "foam": (0.82, 0.82, 0.78, 1), "velcro": (0.03, 0.035, 0.04, 1),
       "neoprene": (0.025, 0.025, 0.028, 1), "skin": (0.78, 0.55, 0.42, 1), "plug": (0.06, 0.065, 0.07, 1),
       "metal": (0.75, 0.76, 0.78, 1)}


# ------------------------------------------------------------------------------------------------ helpers
def mm(*v):
    return Vector(v) * 0.001


def box_world(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def centre(o):
    lo, hi = box_world(o)
    return (lo + hi) / 2


def wdelta(o, v):
    """World displacement (metres) -> the object's local location delta (its parent is the Y-up glTF empty)."""
    if o.parent is None:
        return Vector(v)
    bpy.context.view_layer.update()
    return o.parent.matrix_world.to_3x3().inverted() @ Vector(v)


def vis(o, frame, on):
    o.hide_render = o.hide_viewport = not on
    o.keyframe_insert("hide_render", frame=frame)
    o.keyframe_insert("hide_viewport", frame=frame)


def show_between(o, f_on, f_off=None):
    vis(o, 0, False)
    vis(o, f_on, True)
    if f_off is not None:
        vis(o, f_off, False)


def ease(t):
    return F.ease(t)


def move_in(o, f0, f1, offset, hold=0):
    """Object sits at final + offset (world metres) until f0, eases to final by f1."""
    base = o.location.copy()
    d = wdelta(o, offset)
    for f, k in ((0, 1.0), (f0, 1.0), (f1, 0.0)):
        o.location = base + d * k
        o.keyframe_insert("location", frame=f)
    o.location = base


def pop_in(o, f0, f1):
    s = o.scale.copy()
    for f, k in ((0, 0.0), (f0, 0.0), (f1, 1.0)):
        o.scale = s * max(k, 1e-4)
        o.keyframe_insert("scale", frame=f)
    o.scale = s


_mats: dict = {}


def mat_of(key, rough=0.5, metal=0.0):
    if key not in _mats:
        _mats[key] = D.mat(key, COL[key], rough, metal)
    return _mats[key]


def block(name, size_mm, at, colour, rough=0.6, bevel=0.3):
    bpy.ops.mesh.primitive_cube_add(size=1, location=at)
    o = bpy.context.object
    o.name = name
    o.scale = Vector(size_mm) * 0.001
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        bv = o.modifiers.new("bevel", "BEVEL")
        bv.width = bevel * 0.001
        bv.segments = 3
    o.data.materials.append(mat_of(colour, rough))
    return o


def wire(name, pts, colour, radius_mm=0.45):
    """Insulated wire through world points (metres). Its bevel_factor_end is animated to 'draw' it."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius_mm * 0.001
    cu.bevel_resolution = 3
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    o = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(o)
    cu.materials.append(mat_of(colour, 0.7))
    return o


def draw(o, f0, f1):
    cu = o.data
    for f, v in ((0, 0.0), (f0, 0.0), (f1, 1.0)):
        cu.bevel_factor_end = v
        cu.keyframe_insert("bevel_factor_end", frame=f)


def bundle(prefix, pts, colours, spacing_mm=0.95, axis=(0, 1, 0)):
    """Parallel wires (e.g. a Qwiic run) offset sideways along `axis`."""
    out = []
    n = len(colours)
    for i, c in enumerate(colours):
        off = Vector(axis) * ((i - (n - 1) / 2) * spacing_mm * 0.001)
        out.append(wire(f"{prefix}_{c}", [p + off for p in pts], c))
    return out


QWIIC = ["black", "red", "blue", "yellow"]


# ------------------------------------------------------------------------------------------------ scene
def stage(unit="unit_upperarm", lift_to_floor=True):
    _mats.clear()                       # D.reset() reloads factory settings: cached materials are gone
    sc = D.reset()
    F.setup(sc)
    F.product_look(sc)
    F.cyclorama(scale=0.07, y_wall=2.4)
    F.product_lights((0, 0, 0.015))
    root, parts = D.import_unit(unit)
    F.graphite(parts)
    P = {o.name.split(".")[0]: o for o in parts}
    bpy.context.view_layer.update()
    if lift_to_floor:
        zmin = min(box_world(o)[0].z for o in parts)
        root.location.z -= zmin
        bpy.context.view_layer.update()
    sc.render.fps = 30
    return sc, root, P


def pod_frame(P):
    """Key positions of the pod body in world metres (from its bounding box + CAD offsets)."""
    lo, hi = box_world(P["body"])
    cy = (lo.y + hi.y) / 2
    z0 = lo.z + RAIL_H * 0.001                      # pod floor underside (the tongue hangs below it)
    return {"lo": lo, "hi": hi, "cy": cy, "cx": (lo.x + hi.x) / 2, "z0": z0,
            "grommet": Vector((lo.x, cy + 0.006, z0 + 0.0052)),
            "switch_slot": Vector((lo.x, cy - 0.006, z0 + 0.0024)),
            "usb": Vector((hi.x, cy, z0 + 0.007))}


def hide_all_but(P, keep, frame=0):
    for k, o in P.items():
        if k not in keep:
            vis(o, frame, False)


def camera(name, loc, target, lens=60, fstop=5.6, shift=0.14):
    c, t = D.camera(name, loc, target, lens)
    c.data.dof.aperture_fstop = fstop
    c.data.shift_x = shift              # subject sits left of centre: the right third is the step panel
    return c, t


def orbit(c, centre_pt, r, z, a0, a1, n, f0=1):
    for i in range(0, n, 3):
        u = i / max(n - 1, 1)
        a = math.radians(a0 + (a1 - a0) * u)
        c.location = (centre_pt.x + r * math.sin(a), centre_pt.y - r * math.cos(a), z)
        c.keyframe_insert("location", frame=f0 + i)


def screen(sc, cam, p):
    return F.screen(sc, cam, p)


def render(sc, cam, name, points):
    """points: {key: callable(frame)->world Vector}; renders LENGTHS[name] frames from frame 1."""
    n = LENGTHS[name]
    sc.camera = cam
    rows = []
    for f in range(1, n + 1):
        sc.frame_set(f)
        rows.append({k: screen(sc, cam, fn()) for k, fn in points.items()})
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{name}.json").write_text(json.dumps({"clip": name, "frames": rows}, separators=(",", ":")), "utf-8")
    if CLIP == "test" or "--still" in argv:
        sc.frame_set(1 + int((n - 1) * float(F.opt("--at", "0.92"))))
        sc.render.filepath = str((ROOT / "hardware" / "renders" / f"test_guide_{name}.png").resolve())
        bpy.ops.render.render(write_still=True)
        print("rendered", sc.render.filepath)
        return
    d = FRAMES / name
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.png"):
        old.unlink()
    sc.frame_start, sc.frame_end = 1, n
    sc.render.filepath = str(d) + "/"
    bpy.ops.render.render(animation=True)
    print("rendered", name, n, "frames")


def foam_pads(o, size=(5, 5, 0.8), inset=2.5):
    """Four foam-tape squares under the corners of a board (world)."""
    lo, hi = box_world(o)
    pads = []
    for sx in (0, 1):
        for sy in (0, 1):
            x = lo.x + inset * 0.001 if sx == 0 else hi.x - inset * 0.001
            y = lo.y + inset * 0.001 if sy == 0 else hi.y - inset * 0.001
            pads.append(block(f"foam_{o.name}_{sx}{sy}", size, Vector((x, y, lo.z - size[2] * 0.0005)), "foam", 0.9, 0.2))
    return pads


def tape_sheet(o, size_xy, z_under=True):
    lo, hi = box_world(o)
    c = (lo + hi) / 2
    return block(f"tape_{o.name}", (size_xy[0], size_xy[1], 0.8), Vector((c.x, c.y, lo.z - 0.0004)), "foam", 0.9, 0.2)


# ------------------------------------------------------------------------------------------------ pod build order
ORDER = ["bno", "motor", "switch", "xiao", "wires", "deck", "top", "lid"]
STEP_PARTS = {"bno": ["bno085"], "motor": ["motor"], "switch": ["switch"], "xiao": ["xiao"], "wires": [],
              "deck": ["deck"], "top": ["lipo", "drv2605"], "lid": ["lid"]}


def build_extras(P, pf):
    """Foam, wires and the Qwiic lead for the upper-arm pod, at their final places. Returns {name: [objects]}."""
    ex = {}
    ex["bno_pads"] = foam_pads(P["bno085"])
    blo, bhi = box_world(P["bno085"])
    xlo, xhi = box_world(P["xiao"])
    zt = max(bhi.z, xhi.z) + 0.003
    # BNO085 Qwiic (+X end) -> XIAO: SDA/SCL to D4/D5 on the -Y edge, 3V3/GND to the +Y edge (XIAO pinout)
    c0 = Vector((bhi.x - 0.002, pf["cy"], bhi.z + 0.0005))
    sig = [c0 + mm(0, -1.2, 0), c0 + mm(3, -2, 3), Vector((xlo.x + 0.006, xlo.y + 0.0012, zt)),
           Vector((xlo.x + 0.008, xlo.y + 0.0006, xhi.z - 0.0012))]
    pwr = [c0 + mm(0, 1.2, 0), c0 + mm(3, 2, 3), Vector((xlo.x + 0.006, xhi.y - 0.0012, zt)),
           Vector((xlo.x + 0.008, xhi.y - 0.0006, xhi.z - 0.0012))]
    ex["i2c"] = bundle("i2c_sig", sig, ["blue", "yellow"], 0.95, (1, 0, 0)) + bundle("i2c_pwr", pwr, ["black", "red"], 0.95, (1, 0, 0))
    # switch -> XIAO BAT+ pad on the underside (the rails leave room under the board)
    slo, shi = box_world(P["switch"])
    s0 = Vector((shi.x, (slo.y + shi.y) / 2, (slo.z + shi.z) / 2))
    ex["bat"] = [wire("bat_plus", [s0, s0 + mm(4, 2, -0.6), Vector((xlo.x + 0.004, pf["cy"] - 0.002, pf["z0"] + FLOOR * 0.001 + 0.0009)),
                                     Vector(((xlo.x + xhi.x) / 2, pf["cy"] - 0.002, xlo.z - 0.0006))], "red")]
    # Qwiic lead from the BNO085's second connector (-X end) out through the grommet toward the forearm
    q0 = Vector((blo.x + 0.002, pf["cy"] + 0.003, blo.z + 0.004))
    g = pf["grommet"]
    ex["qwiic_out"] = bundle("qwiic_out", [q0, q0 + mm(-1.5, 2, 2), g + mm(2.5, 0, 0), g, g + mm(-12, 0, -1.5), g + mm(-40, 6, -6)],
                             QWIIC, 0.55, (0, 0, 1))
    return ex


def build_top_extras(P, pf):
    ex = {}
    ex["lipo_tape"] = [tape_sheet(P["lipo"], (24, 18))]
    ex["drv_tape"] = [tape_sheet(P["drv2605"], (12, 12))]
    llo, lhi = box_world(P["lipo"])
    dlo, dhi = box_world(P["drv2605"])
    slo, shi = box_world(P["switch"])
    xlo, xhi = box_world(P["xiao"])
    mlo, mhi = box_world(P["motor"])
    # LiPo lead over the deck edge at the -X end: red to the switch, black to BAT- under the XIAO
    l0 = Vector((llo.x + 0.002, lhi.y - 0.002, (llo.z + lhi.z) / 2))
    down = Vector((pf["lo"].x + 0.0035, pf["hi"].y - 0.0035, (llo.z + lhi.z) / 2))
    ex["lipo_lead"] = [
        wire("lipo_red", [l0, l0 + mm(-1.5, 0.5, 0), down, Vector((down.x, down.y - 0.004, slo.z + 0.002)),
                          Vector(((slo.x + shi.x) / 2, shi.y, (slo.z + shi.z) / 2))], "red"),
        wire("lipo_black", [l0 + mm(0, -1.1, 0), l0 + mm(-1.5, -0.6, 0), down + mm(0, -1.1, 0),
                            Vector((down.x + 0.004, pf["cy"] + 0.004, pf["z0"] + 0.0029)),
                            Vector(((xlo.x + xhi.x) / 2, pf["cy"] + 0.002, xlo.z - 0.0006))], "black")]
    # DRV2605L: I2C + power down the +X end to the XIAO edge pins; motor leads up the +Y wall
    d0 = Vector((dhi.x - 0.002, (dlo.y + dhi.y) / 2, dhi.z))
    ex["drv_i2c"] = bundle("drv_i2c", [d0, d0 + mm(0, 0, 2.5), Vector((xhi.x - 0.004, xlo.y + 0.003, dhi.z + 0.001)),
                                        Vector((xhi.x - 0.005, xlo.y + 0.0008, xhi.z - 0.0012))], QWIIC, 0.8, (1, 0, 0))
    m0 = Vector(((mlo.x + mhi.x) / 2, mhi.y, mhi.z))
    ex["motor_lead"] = bundle("motor_lead", [m0, m0 + mm(0, 2.5, 1.5), Vector((m0.x, pf["hi"].y - 0.0032, xhi.z + 0.002)),
                                              Vector((dlo.x + 0.004, pf["hi"].y - 0.0032, dhi.z + 0.0015)),
                                              Vector((dlo.x + 0.006, dhi.y - 0.002, dhi.z))], ["red", "blue"], 0.8, (1, 0, 0))
    return ex


def pod_clip(name):
    """Pod-assembly clips: earlier steps done, this step animates, later steps hidden."""
    sc, root, P = stage("unit_upperarm")
    pf = pod_frame(P)
    n = LENGTHS[name]
    ex = build_extras(P, pf)
    tx = build_top_extras(P, pf)
    k = ORDER.index(name)
    done = [s for s in ORDER[:k]]
    vis(P["base"], 0, False)
    for s in ORDER[k + 1:]:
        for p in STEP_PARTS[s]:
            vis(P[p], 0, False)
    groups_after = {"wires": ["i2c", "bat", "qwiic_out"], "top": ["lipo_tape", "drv_tape", "lipo_lead", "drv_i2c", "motor_lead"],
                    "bno": ["bno_pads"]}
    allx = {**ex, **tx}
    for s, gs in groups_after.items():
        if s not in done and s != name:
            for g in gs:
                for o in allx[g]:
                    vis(o, 0, False)
    pts = {}
    look = Vector((pf["cx"], pf["cy"], pf["z0"] + 0.006))
    cam_r, cam_z, lens = 0.20, 0.17, 55
    if name == "bno":
        for i, o in enumerate(ex["bno_pads"]):
            pop_in(o, 6 + 3 * i, 12 + 3 * i)
        move_in(P["bno085"], 26, 56, mm(0, 0, 28))
        pts = {"bno085": lambda: centre(P["bno085"]), "pad": lambda: centre(ex["bno_pads"][0])}
        look = centre(P["bno085"])
    elif name == "motor":
        move_in(P["motor"], 8, 38, mm(0, 0, 26))
        pts = {"motor": lambda: centre(P["motor"])}
        look = centre(P["motor"])
    elif name == "switch":
        move_in(P["switch"], 8, 40, mm(16, 0, 10))
        pts = {"switch": lambda: centre(P["switch"]), "slot": lambda: pf["switch_slot"]}
        look = centre(P["switch"])
    elif name == "xiao":
        # first drop onto the rails, then slide toward +X until USB-C meets the wall opening
        base = P["xiao"].location.copy()
        P["xiao"].location = base + wdelta(P["xiao"], mm(-14, 0, 22))
        P["xiao"].keyframe_insert("location", frame=0)
        P["xiao"].keyframe_insert("location", frame=6)
        P["xiao"].location = base + wdelta(P["xiao"], mm(-14, 0, 0))
        P["xiao"].keyframe_insert("location", frame=32)
        P["xiao"].location = base
        P["xiao"].keyframe_insert("location", frame=60)
        pts = {"xiao": lambda: centre(P["xiao"]), "usb": lambda: pf["usb"]}
        look = centre(P["xiao"])
    elif name == "wires":
        for i, o in enumerate(ex["i2c"]):
            draw(o, 4 + 2 * i, 34 + 2 * i)
        draw(ex["bat"][0], 34, 58)
        for i, o in enumerate(ex["qwiic_out"]):
            draw(o, 56 + i, 86 + i)
        pts = {"i2c": lambda: ex["i2c"][0].matrix_world @ ex["i2c"][0].data.splines[0].bezier_points[2].co,
               "bat": lambda: ex["bat"][0].data.splines[0].bezier_points[2].co,
               "grommet": lambda: pf["grommet"]}
        look = Vector((pf["cx"] - 0.004, pf["cy"], pf["z0"] + 0.006))
        cam_r = 0.22
    elif name == "deck":
        move_in(P["deck"], 8, 36, mm(0, 0, 26))
        pts = {"deck": lambda: centre(P["deck"])}
        look = centre(P["deck"])
    elif name == "top":
        pop_in(tx["lipo_tape"][0], 4, 10)
        pop_in(tx["drv_tape"][0], 8, 14)
        move_in(P["lipo"], 12, 40, mm(0, 0, 30))
        move_in(P["drv2605"], 24, 50, mm(0, 0, 30))
        for i, o in enumerate(tx["lipo_lead"]):
            draw(o, 52 + i * 2, 74 + i * 2)
        for i, o in enumerate(tx["drv_i2c"] + tx["motor_lead"]):
            draw(o, 60 + i, 90)
        pts = {"lipo": lambda: centre(P["lipo"]), "drv2605": lambda: centre(P["drv2605"]),
               "lead": lambda: tx["lipo_lead"][0].data.splines[0].bezier_points[2].co}
        look = Vector((pf["cx"], pf["cy"], pf["z0"] + 0.012))
    elif name == "lid":
        lid = P["lid"]
        base = lid.location.copy()
        for f, dz in ((0, 30), (8, 30), (36, 1.2), (44, 1.2), (48, -0.25), (51, 0.0)):
            lid.location = base + wdelta(lid, mm(0, 0, dz))
            lid.keyframe_insert("location", frame=f)
        lid.location = base
        pts = {"lid": lambda: centre(P["lid"]), "arrow": lambda: centre(P["lid"]) + mm(-8, 0, 2)}
        look = Vector((pf["cx"], pf["cy"], pf["z0"] + 0.014))
        cam_z = 0.15
    c, _ = camera(f"cam_{name}", (0, 0, 0), look, lens)
    orbit(c, look, cam_r * 0.62, look.z + cam_z * 1.15, -34, -16, n)    # steep enough to see into the pod
    render(sc, c, name, pts)


# ------------------------------------------------------------------------------------------------ other clips
def clip_kit():
    sc, root, P = stage("unit_upperarm")
    pf = pod_frame(P)
    n = LENGTHS["kit"]
    # lay the kit out in rows on the table (world offsets from each part's assembled place)
    layout = {"base": (-0.075, 0.045), "body": (0.0, 0.045), "deck": (0.075, 0.045), "lid": (0.075, 0.0),
              "lipo": (-0.075, -0.005), "bno085": (-0.03, -0.012), "xiao": (0.015, -0.012), "drv2605": (0.05, -0.04),
              "motor": (0.0, -0.045), "switch": (-0.035, -0.045)}
    pts = {}
    for k, (x, y) in layout.items():
        o = P[k]
        lo, hi = box_world(o)
        c = (lo + hi) / 2
        target = Vector((x, y, (hi.z - lo.z) / 2 + 0.0002))
        o.location = o.location + wdelta(o, target - c)
        bpy.context.view_layer.update()
        pts[k] = (lambda o=o: centre(o))
    # loose bits: foam sheet, Qwiic cable, velcro, neoprene, hook-up wire
    block("kit_foam", (30, 20, 0.8), Vector((-0.075, -0.045, 0.0004)), "foam", 0.9, 0.2)
    block("kit_neoprene", (60, 45, 1.0), Vector((0.11, -0.045, 0.0005)), "neoprene", 0.95, 0.4)
    block("kit_velcro", (25, 110, 1.5), Vector((-0.12, 0.0, 0.00075)), "velcro", 0.95, 0.4)
    bundle("kit_qwiic", [Vector((0.03, -0.065, 0.001)), Vector((0.06, -0.07, 0.001)), Vector((0.09, -0.06, 0.001)),
                         Vector((0.12, -0.075, 0.001))], QWIIC, 0.55, (0, 0, 1))
    for i, colr in enumerate(["red", "black"]):
        wire(f"kit_wire_{colr}", [Vector((-0.03 + i * 0.003, -0.07, 0.0006)), Vector((-0.01 + i * 0.003, -0.075, 0.0006)),
                                  Vector((0.01 + i * 0.003, -0.068, 0.0006))], colr)
    pts.update({"foam": lambda: Vector((-0.075, -0.045, 0.001)), "neoprene": lambda: Vector((0.11, -0.045, 0.001)),
                "velcro": lambda: Vector((-0.12, 0.0, 0.002)), "qwiic": lambda: Vector((0.075, -0.067, 0.001))})
    look = Vector((0.0, -0.005, 0.0))
    c, _ = camera("cam_kit", (0, 0, 0), look, 35, 8.0, shift=0.19)     # whole layout left of the step panel
    orbit(c, look, 0.27, 0.36, -14, 4, n)
    render(sc, c, "kit", pts)


def neoprene_strip(base_obj, radius, lift_z):
    """Curved 1 mm strip that follows the base underside (an arc of the limb cylinder)."""
    lo, hi = box_world(base_obj)
    cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
    axis_z = lift_z + (BASE_BOTTOM_C - radius) * 0.001
    half = math.asin(min(0.95, ((hi.y - lo.y) / 2 - 0.004) / (radius * 0.001)))
    bm = bmesh.new()
    rows = []
    segs = 16
    length = (hi.x - lo.x) - 0.006
    r = radius * 0.001 - 0.0002
    for i in range(segs + 1):
        a = -half + 2 * half * i / segs
        y = cy + r * math.sin(a)
        z = axis_z + r * math.cos(a)
        rows.append((bm.verts.new((cx - length / 2, y, z)), bm.verts.new((cx + length / 2, y, z))))
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    me = bpy.data.meshes.new("neoprene")
    bm.to_mesh(me)
    o = bpy.data.objects.new("neoprene", me)
    bpy.context.scene.collection.objects.link(o)
    s = o.modifiers.new("thick", "SOLIDIFY")
    s.thickness = 0.001
    s.offset = 1.0
    o.data.materials.append(mat_of("neoprene", 0.95))
    for p in me.polygons:
        p.use_smooth = True
    return o


def clip_neoprene():
    sc, root, P = stage("unit_upperarm")
    n = LENGTHS["neoprene"]
    hide_all_but(P, {"base"})
    b = P["base"]
    strip = neoprene_strip(b, RADIUS["unit_upperarm"], root.location.z)
    bpy.context.view_layer.update()
    # flip the base upside down (about its own centre), press the strip on, flip back
    piv = centre(b)
    pivot = bpy.data.objects.new("flip_pivot", None)
    sc.collection.objects.link(pivot)
    pivot.location = piv
    bpy.context.view_layer.update()
    for o in (b, strip):
        mw = o.matrix_world.copy()
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()
        o.matrix_world = mw
    s0 = strip.location.copy()
    for f, k in ((0, 1), (24, 1), (44, 0)):
        strip.location = s0 + Vector((0, 0, -0.02 * k))       # pivot space = world axes (pivot is unrotated at bind)
        strip.keyframe_insert("location", frame=f)
    pivot.rotation_mode = "XYZ"
    for f, a in ((0, 180), (48, 180), (66, 360)):
        pivot.rotation_euler = (math.radians(a), 0, 0)
        pivot.keyframe_insert("rotation_euler", frame=f)
    pivot.location = piv + Vector((0, 0, 0.012))
    pivot.keyframe_insert("location", frame=0)
    pivot.keyframe_insert("location", frame=48)
    pivot.location = piv
    pivot.keyframe_insert("location", frame=66)
    look = piv + Vector((0, 0, 0.01))
    c, _ = camera("cam_neoprene", (0, 0, 0), look, 50)
    orbit(c, look, 0.2, look.z + 0.12, -35, -15, n)
    render(sc, c, "neoprene", {"strip": lambda: centre(strip), "base": lambda: centre(b)})


def clip_forearm():
    sc, root, P = stage("unit_forearm")
    n = LENGTHS["forearm"]
    pf = pod_frame(P)
    vis(P["base"], 0, False)
    pads = foam_pads(P["bno085"], (4, 4, 0.8), 2.2)
    for i, o in enumerate(pads):
        pop_in(o, 4 + 2 * i, 10 + 2 * i)
    move_in(P["bno085"], 14, 40, mm(0, 0, 24))
    blo, bhi = box_world(P["bno085"])
    g = Vector((pf["lo"].x, pf["cy"], pf["z0"] + 0.005))
    q0 = Vector((blo.x + 0.002, pf["cy"], blo.z + 0.004))
    cable = bundle("fore_qwiic", [g + mm(-45, -8, -6), g + mm(-14, 0, -1.5), g, g + mm(2.5, 0, 0), q0 + mm(-1.5, 0, 2), q0],
                   QWIIC, 0.55, (0, 0, 1))
    for i, o in enumerate(cable):
        draw(o, 44 + i, 70 + i)
    lid = P["lid"]
    base = lid.location.copy()
    for f, dz in ((0, 28), (74, 28), (96, 1.0), (100, 1.0), (103, -0.25), (106, 0.0)):
        lid.location = base + wdelta(lid, mm(0, 0, dz))
        lid.keyframe_insert("location", frame=f)
    lid.location = base
    look = Vector((pf["cx"] - 0.004, pf["cy"], pf["z0"] + 0.006))
    c, _ = camera("cam_forearm", (0, 0, 0), look, 55)
    orbit(c, look, 0.17, look.z + 0.12, -30, -10, n)
    render(sc, c, "forearm", {"bno085": lambda: centre(P["bno085"]), "grommet": lambda: g, "lid": lambda: centre(lid)})


def clip_waist():
    sc, root, P = stage("unit_waist")
    n = LENGTHS["waist"]
    pf = pod_frame(P)
    vis(P["base"], 0, False)
    pads = foam_pads(P["bno085"])
    seq = [("pads", 2, 10), ("bno085", 8, 26), ("switch", 24, 38), ("xiao", 34, 54), ("deck", 52, 64), ("lipo", 62, 78),
           ("lid", 78, 96)]
    for i, o in enumerate(pads):
        pop_in(o, 2 + i, 8 + i)
    for key, f0, f1 in seq[1:]:
        o = P[key]
        off = {"switch": mm(14, 0, 10), "xiao": mm(-12, 0, 18)}.get(key, mm(0, 0, 26))
        move_in(o, f0, f1, off)
    look = Vector((pf["cx"], pf["cy"], pf["z0"] + 0.008))
    c, _ = camera("cam_waist", (0, 0, 0), look, 50)
    orbit(c, look, 0.21, look.z + 0.14, -40, 10, n)
    render(sc, c, "waist", {"bno085": lambda: centre(P["bno085"]), "xiao": lambda: centre(P["xiao"]),
                            "lipo": lambda: centre(P["lipo"]), "lid": lambda: centre(P["lid"])})


def strap_mesh(cx, cy, axis_z, radius, slot_y, wing_top_z, width=25.0, t=1.5):
    """Velcro strap in the base's YZ section: tail folded over the -Y wing, through the slot, round the limb, up
    through the +Y slot and folded back. Faces are ordered along the strap so a Build modifier threads it."""
    r_in = radius * 0.001 + 0.0009
    r_out = radius * 0.001 + 0.0009 + t * 0.0012 * 2
    sy = slot_y * 0.001
    pts = []

    def arc(r, a0, a1, steps):
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts.append((cy + r * math.sin(a), axis_z + r * math.cos(a)))

    under = axis_z + math.sqrt(max((radius * 0.001) ** 2 - sy ** 2, 0))
    arc(r_out, -62, -40, 4)                                    # tail lying on the strap (velcro hook side)
    pts += [(cy - sy - 0.0045, wing_top_z + 0.0012), (cy - sy, wing_top_z + 0.0009), (cy - sy, under - 0.002)]
    arc(r_in, -math.degrees(math.asin(sy / (radius * 0.001))) - 3, -360 + math.degrees(math.asin(sy / (radius * 0.001))) + 3, 48)
    pts += [(cy + sy, under - 0.002), (cy + sy, wing_top_z + 0.0009), (cy + sy + 0.0045, wing_top_z + 0.0012)]
    arc(r_out, 40, 62, 4)
    bm = bmesh.new()
    hw = width * 0.0005
    rows = [(bm.verts.new((cx - hw, y, z)), bm.verts.new((cx + hw, y, z))) for y, z in pts]
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    me = bpy.data.meshes.new("strap")
    bm.to_mesh(me)
    o = bpy.data.objects.new("velcro_strap", me)
    bpy.context.scene.collection.objects.link(o)
    return o


def clip_strap():
    sc, root, P = stage("unit_upperarm", lift_to_floor=False)
    n = LENGTHS["strap"]
    R = RADIUS["unit_upperarm"]
    # rest the base on a stand-in arm (cylinder along X) that sits on the floor
    root.location.z = (R - (BASE_BOTTOM_C - R)) * 0.001
    bpy.context.view_layer.update()
    axis_z = R * 0.001
    blo, bhi = box_world(P["base"])
    cx, cy = (blo.x + bhi.x) / 2, (blo.y + bhi.y) / 2
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=R * 0.001, depth=0.24, location=(cx, cy, axis_z),
                                        rotation=(0, math.radians(90), 0))
    arm = bpy.context.object
    arm.name = "arm_standin"
    m = D.mat("skin_standin", COL["skin"], 0.55)
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Subsurface Weight"].default_value = 0.25
    arm.data.materials.append(m)
    for poly in arm.data.polygons:
        poly.use_smooth = True
    wing_top_world = root.location.z + WING_TOP * 0.001
    strap = strap_mesh(cx, cy, axis_z, R, SLOT_Y, wing_top_world)
    b = strap.modifiers.new("thread", "BUILD")
    b.frame_start, b.frame_duration = 10, 80
    sol = strap.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = 0.0015
    strap.data.materials.append(mat_of("velcro", 0.95))
    for poly in strap.data.polygons:
        poly.use_smooth = True
    look = Vector((cx, cy, axis_z + R * 0.0006))
    c, _ = camera("cam_strap", (0, 0, 0), look, 45, 5.6, shift=0.12)
    for f, (x, y, z) in ((1, (0.3, -0.22, 0.2)), (n, (0.24, -0.27, 0.16))):
        c.location = (x, y, z)
        c.keyframe_insert("location", frame=f)
    slot_l = Vector((cx, cy - SLOT_Y * 0.001, wing_top_world))
    slot_r = Vector((cx, cy + SLOT_Y * 0.001, wing_top_world))
    render(sc, c, "strap", {"slot_l": lambda: slot_l, "slot_r": lambda: slot_r, "pod": lambda: centre(P["lid"]),
                            "arm": lambda: Vector((cx - 0.09, cy, axis_z))})


def clip_charge():
    sc, root, P = stage("unit_upperarm")
    n = LENGTHS["charge"]
    pf = pod_frame(P)
    vis(P["base"], 0, False)
    port = pf["usb"]
    tip = block("usbc_tip", (6.5, 8.3, 2.5), port + mm(3.2, 0, 0), "metal", 0.25, 1.1)
    tip.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 1.0
    body = block("usbc_overmold", (20, 11, 6.5), port + mm(16.4, 0, 0), "plug", 0.5, 2.2)
    cable = wire("usbc_cable", [port + mm(26, 0, 0), port + mm(40, 4, -1), port + mm(70, 20, -4)], "black", 1.6)
    plug = bpy.data.objects.new("usbc_plug", None)
    sc.collection.objects.link(plug)
    for o in (tip, body, cable):
        o.parent = plug
    for f, dx in ((0, 45), (10, 45), (40, 0), (n, 0)):
        plug.location = (dx * 0.001, 0, 0)
        plug.keyframe_insert("location", frame=f)
    look = port + mm(10, 0, 0)
    c, _ = camera("cam_charge", (0, 0, 0), look, 60, 4.0)
    orbit(c, look, 0.16, look.z + 0.07, 25, 45, n)
    render(sc, c, "charge", {"usb": lambda: port, "plug": lambda: centre(body)})


def clip_power():
    sc, root, P = stage("unit_upperarm")
    n = LENGTHS["power"]
    pf = pod_frame(P)
    vis(P["base"], 0, False)
    s = pf["switch_slot"]
    lever = block("switch_lever", (2.2, 1.6, 1.6), s + mm(-0.6, -1.2, 0), "black", 0.5, 0.3)
    for f, dy in ((0, -1.2), (16, -1.2), (24, 1.2), (n, 1.2)):
        lever.location = s + mm(-0.6, dy, 0)
        lever.keyframe_insert("location", frame=f)
    look = s + mm(4, 0, 2)
    c, _ = camera("cam_power", (0, 0, 0), look, 70, 4.0)
    orbit(c, look, 0.12, look.z + 0.04, -125, -105, n)
    render(sc, c, "power", {"lever": lambda: centre(lever)})


CLIPS = {"kit": clip_kit, "neoprene": clip_neoprene, "forearm": clip_forearm, "waist": clip_waist,
         "strap": clip_strap, "charge": clip_charge, "power": clip_power}


if __name__ == "__main__":
    names = list(LENGTHS) if CLIP in ("all", "test") else [c for c in CLIP.split(",")]
    for nm in names:
        if nm in CLIPS:
            CLIPS[nm]()
        else:
            pod_clip(nm)
