"""Build a Blender scene: the station's Rocketbox patient wearing the Physio Buddy units, then animate + render.

    blender -b --factory-startup -P tools/blender/device_on_avatar.py -- <mode> [options]
      mode = still   -> renders hardware/renders/avatar_still.png (placement check)
      mode = video   -> renders the animated shots to hardware/renders/frames/<shot>/####.png
      --avatar web/public/models/Sports_Male_04.glb  --side right  --samples 32  --res 1920x1080

Placement is computed, not hand-tuned: units are dropped onto the evaluated skin by raycasting from outside toward
the limb axis (upper arm: lateral, 45 % down the humerus; forearm: dorsal, 75 % toward the wrist; chest: sternum).
Straps are rings shrink-wrapped onto the skin. Everything is parented to the arm / spine bones, so it follows the
animated exercise.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = argv[0] if argv else "still"


def opt(name, default):
    return argv[argv.index(name) + 1] if name in argv else default


AVATAR = (ROOT / opt("--avatar", "web/public/models/Sports_Male_04.glb")).resolve()
SIDE = opt("--side", "right")
SAMPLES = int(opt("--samples", "32"))
TRUNK = opt("--trunk", "waist")   # waist (belt at the navel line, default) | sternum (chest band; measures the thorax)
RES = tuple(int(v) for v in opt("--res", "1920x1080").split("x"))
GLB = ROOT / "hardware" / "cad" / "out" / "glb"
OUT = (ROOT / "hardware" / "renders").resolve()
S = "R" if SIDE == "right" else "L"

BONES = {"spine": "Bip01 Spine2", "neck": "Bip01 Neck", "clav": f"Bip01 {S} Clavicle", "pelvis": "Bip01 Pelvis",
         "arm": f"Bip01 {S} UpperArm", "fore": f"Bip01 {S} Forearm", "hand": f"Bip01 {S} Hand",
         "arm_o": f"Bip01 {'L' if S == 'R' else 'R'} UpperArm", "fore_o": f"Bip01 {'L' if S == 'R' else 'R'} Forearm",
         "hand_o": f"Bip01 {'L' if S == 'R' else 'R'} Hand"}

# colours (match the station UI: off-black + clinical teal)
STRAP_COL = (0.012, 0.014, 0.017, 1)
STRAP_EDGE = (0.31, 0.78, 0.65, 1)


# ------------------------------------------------------------------------------------------------ scene
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.eevee.taa_render_samples = SAMPLES
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.render.fps = 30
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.03, 0.038, 0.05, 1)
    bg.inputs[1].default_value = 0.5
    sc.world = world
    return sc


def light(name, loc, energy, size, colour=(1, 1, 1), target=(0, 0, 1.2)):
    l = bpy.data.lights.new(name, "AREA")
    l.energy, l.size, l.color = energy, size, colour
    o = bpy.data.objects.new(name, l)
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(o)
    return o


def studio():
    light("key", (1.6, -2.4, 2.6), 500, 2.0)
    light("fill", (-2.4, -1.6, 1.4), 160, 3.0, (0.85, 0.9, 1.0))
    light("rim", (0.4, 2.6, 2.4), 420, 1.5, (0.75, 1.0, 0.92))
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=1.6, fill_type="NGON", location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "floor"
    m = bpy.data.materials.new("floor")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.055, 0.065, 0.08, 1)
    p.inputs["Roughness"].default_value = 0.3
    floor.data.materials.append(m)


def mat(name, rgba, rough=0.5, metal=0.0, emit=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = rgba
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = emit
        p.inputs["Emission Strength"].default_value = 2.0
    return m


# ------------------------------------------------------------------------------------------------ avatar
def import_avatar():
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(AVATAR))
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    junk = [o for o in new if o.type == "MESH" and o.name.startswith("Icosphere")]
    new = [o for o in new if o not in junk]
    for o in junk:
        bpy.data.objects.remove(o)                      # stray helper object shipped inside the Rocketbox export
    meshes = [o for o in new if o.type == "MESH"]
    print("avatar meshes:", [(o.name, len(o.data.vertices), [s.material.name for s in o.material_slots if s.material])
                             for o in meshes])
    print("armature:", arm.name, "scale", tuple(round(v, 4) for v in arm.matrix_world.to_scale()))
    body = max(meshes, key=lambda o: len(o.data.vertices))      # the skinned body/clothes mesh
    return arm, meshes, body


def bone_world(arm, name):
    pb = arm.pose.bones[name]
    return arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail, pb


def aim(arm, name, direction, ref_child=None):
    """Rotate pose bone so that head->(child head or tail) points along world `direction` (swing only)."""
    pb = arm.pose.bones[name]
    bpy.context.view_layer.update()
    head = arm.matrix_world @ pb.head
    tip = arm.matrix_world @ (arm.pose.bones[ref_child].head if ref_child else pb.tail)
    cur = (tip - head).normalized()
    q = cur.rotation_difference(Vector(direction).normalized())
    rot_world = q.to_matrix().to_4x4()
    mw = arm.matrix_world @ pb.matrix
    new_world = Matrix.Translation(head) @ rot_world @ Matrix.Translation(-head) @ mw
    pb.matrix = arm.matrix_world.inverted() @ new_world
    bpy.context.view_layer.update()


def bvh_of(obj):
    """BVH of the evaluated (posed) mesh. BVHTree.FromObject works in the object's LOCAL space."""
    dg = bpy.context.evaluated_depsgraph_get()
    return BVHTree.FromObject(obj.evaluated_get(dg), dg), obj.matrix_world.copy()


def surface_point(bvh_m, axis_point, radial):
    """Raycast (world space) from outside toward the limb axis; returns world (point, normal)."""
    bvh, mw = bvh_m
    inv = mw.inverted()
    origin = axis_point + radial.normalized() * 0.35
    o_l = inv @ origin
    d_l = (inv.to_3x3() @ -radial.normalized()).normalized()
    hit, normal, _, dist = bvh.ray_cast(o_l, d_l, 1000.0)
    if hit is None:
        raise RuntimeError(f"no skin hit while placing a unit (origin {tuple(round(v, 3) for v in origin)})")
    n_w = (mw.inverted().transposed().to_3x3() @ normal).normalized()
    return mw @ hit, n_w


def perpendicular(v, axis):
    a = axis.normalized()
    return (v - a * v.dot(a)).normalized()


# ------------------------------------------------------------------------------------------------ device
def import_unit(name):
    """Import a CadQuery GLB (mm), return a single empty 'unit root' in metres at the base origin."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(GLB / f"{name}.glb"))
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(f"{name}_root", None)
    bpy.context.scene.collection.objects.link(root)
    for o in new:
        if o.parent is None:
            o.parent = root
    root.scale = (0.001, 0.001, 0.001)
    for o in new:
        if o.type == "MESH":
            for s in o.material_slots:
                if s.material and s.material.use_nodes:
                    p = s.material.node_tree.nodes.get("Principled BSDF")
                    if p:
                        p.inputs["Roughness"].default_value = 0.4
    return root, [o for o in new if o.type == "MESH"]


def place(root, point, normal_out, along, lift=0.0018):
    """Unit frame: +Z out of the skin, +X along `along` (lid arrow direction), origin on the skin + strap."""
    z = normal_out.normalized()
    x = perpendicular(along, z)
    y = z.cross(x)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = point + z * lift
    root.matrix_world = m @ Matrix.Diagonal((0.001, 0.001, 0.001, 1))


def strap_ring(name, centre, axis, radius, width, target, colour_mat, edge_mat):
    """Band around `axis` through `centre`, shrink-wrapped onto `target`'s skin (applied, then rigid)."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=radius, depth=width, end_fill_type="NOTHING",
                                        location=centre)
    ring = bpy.context.object
    ring.name = name
    ring.rotation_mode = "QUATERNION"
    ring.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(axis.normalized())
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=3)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    sw = ring.modifiers.new("wrap", "SHRINKWRAP")
    sw.target = target
    sw.wrap_method = "PROJECT"
    sw.use_negative_direction = True
    sw.use_positive_direction = False
    sw.offset = 0.0012
    bpy.ops.object.modifier_apply(modifier="wrap")
    sol = ring.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = 0.0022
    sol.offset = 1.0
    sol.material_offset_rim = 1
    ring.modifiers.new("smooth", "SUBSURF").levels = 1
    ring.data.materials.append(colour_mat)
    ring.data.materials.append(edge_mat)
    for p in ring.data.polygons:
        p.use_smooth = True
    return ring


def parent_to_bone(obj, arm, bone):
    bpy.context.view_layer.update()
    mw = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    bpy.context.view_layer.update()
    obj.matrix_world = mw


def anchor(name, world_point, arm, bone):
    e = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(e)
    e.matrix_world = Matrix.Translation(world_point)   # set the world matrix directly: .location is not
    e.empty_display_size = 0.01                        # reflected in matrix_world until the depsgraph updates
    bpy.context.view_layer.update()
    parent_to_bone(e, arm, bone)
    return e


def cable(anchors, mat_):
    """Qwiic cable through anchors (empties parented to bones). Each control point (with its two handles) is bound
    to its anchor by a Hook modifier, so the cable is re-evaluated with the pose on every frame and in renders."""
    bpy.context.view_layer.update()
    curve = bpy.data.curves.new("qwiic_cable", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0019
    curve.bevel_resolution = 4
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(len(anchors) - 1)
    for bp, a in zip(sp.bezier_points, anchors):
        bp.co = a.matrix_world.translation
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    obj = bpy.data.objects.new("qwiic_cable", curve)
    bpy.context.scene.collection.objects.link(obj)
    curve.materials.append(mat_)
    for i, a in enumerate(anchors):
        hk = obj.modifiers.new(f"hook_{i}", "HOOK")
        hk.object = a
        hk.vertex_indices_set([3 * i, 3 * i + 1, 3 * i + 2])     # handle_left, co, handle_right
        hk.matrix_inverse = a.matrix_world.inverted()            # bind at the current (build) pose
        hk.center = a.matrix_world.translation
    return obj


# ------------------------------------------------------------------------------------------------ build
def build():
    sc = reset()
    studio()
    arm, meshes, body = import_avatar()
    bpy.context.view_layer.update()
    # place feet on the floor
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    zmin = min((ev.matrix_world @ v.co).z for v in ev.data.vertices)
    arm.location.z -= zmin
    print(f"feet were at z={zmin:.3f} m; avatar height {max((ev.matrix_world @ v.co).z for v in ev.data.vertices) - zmin:.3f} m")
    bpy.context.view_layer.update()

    bvh = bvh_of(body)
    strap_m, edge_m = mat("strap", STRAP_COL, 0.92), mat("strap_edge", STRAP_EDGE, 0.5)
    cable_m = mat("cable", (0.02, 0.02, 0.02, 1), 0.4)
    anterior = Vector((0, -1, 0))                     # Rocketbox faces -Y after import
    outward = Vector((-1 if SIDE == "right" else 1, 0, 0))
    up = Vector((0, 0, 1))

    # upper arm: lateral surface, 45 % from shoulder to elbow
    h, _, _ = bone_world(arm, BONES["arm"])
    e, _, _ = bone_world(arm, BONES["fore"])
    axis = (e - h).normalized()
    c = h.lerp(e, 0.45)
    lateral = perpendicular(outward + up, axis)
    p, n = surface_point(bvh, c, lateral)
    ua_root, ua_parts = import_unit("unit_upperarm")
    place(ua_root, p, lateral, -axis)                 # lid arrow -> shoulder, so the cable exit (-X) faces the elbow
    ring_ua = strap_ring("strap_upperarm", c, axis, 0.085, 0.025, body, strap_m, edge_m)

    # forearm: dorsal surface, 75 % toward the wrist
    w, _, _ = bone_world(arm, BONES["hand"])
    faxis = (w - e).normalized()
    fc = e.lerp(w, 0.75)
    dorsal = perpendicular(up, faxis)
    fp, fn = surface_point(bvh, fc, dorsal)
    fa_root, fa_parts = import_unit("unit_forearm")
    place(fa_root, fp, dorsal, faxis)
    ring_fa = strap_ring("strap_forearm", fc, faxis, 0.07, 0.025, body, strap_m, edge_m)

    # chest: sternum at mid-chest, 16 cm below the shoulder joints (below the armpits, so the T-pose arms used
    # while wrapping the strap are out of the way)
    sh, _, _ = bone_world(arm, BONES["spine"])
    nk, _, _ = bone_world(arm, BONES["neck"])
    ao, _, _ = bone_world(arm, BONES["arm_o"])
    shoulder_z = (h.z + ao.z) / 2
    if TRUNK == "waist":
        pv, _, _ = bone_world(arm, BONES["pelvis"])
        cc = Vector(((h.x + ao.x) / 2, sh.y, pv.z + 0.09))    # belt at the navel line, above the shorts
        trunk_unit, trunk_bone, band_w = "unit_waist", BONES["pelvis"], 0.04
    else:
        cc = Vector(((h.x + ao.x) / 2, sh.y, shoulder_z - 0.16))
        trunk_unit, trunk_bone, band_w = "unit_chest", BONES["spine"], 0.03
    # raise both arms overhead while wrapping the trunk band, so it can only land on the torso
    for a_b, f_b, s in ((BONES["arm"], BONES["fore"], outward.x), (BONES["arm_o"], BONES["fore_o"], -outward.x)):
        aim(arm, a_b, Vector((s * 0.35, 0.0, 1.0)), ref_child=f_b)
    bvh_up = bvh_of(body)
    cp, cn = surface_point(bvh_up, cc, anterior)
    ch_root, ch_parts = import_unit(trunk_unit)
    place(ch_root, cp, anterior, up)                  # lid arrow points up
    ring_ch = strap_ring(f"strap_{TRUNK}", cc, up, 0.32, band_w, body, strap_m, edge_m)
    reset_pose(arm)

    for obj, bone in ((ua_root, BONES["arm"]), (ring_ua, BONES["arm"]), (fa_root, BONES["fore"]),
                      (ring_fa, BONES["fore"]), (ch_root, trunk_bone), (ring_ch, trunk_bone)):
        parent_to_bone(obj, arm, bone)

    # Qwiic cable: arm pod -X wall grommet -> over the lateral elbow -> forearm pod -X wall grommet
    pod_l = {"upperarm": 60.7, "forearm": 36.6}
    a0 = ua_root.matrix_world @ Vector((-(pod_l["upperarm"] / 2 + 2.0) - 2.0, 6.0, 6.0))
    a1 = ua_root.matrix_world @ Vector((-(pod_l["upperarm"] / 2 + 2.0) - 16.0, 4.0, 1.0))
    elbow_lat, _ = surface_point(bvh, e, lateral)
    a2 = elbow_lat + lateral * 0.006
    b1 = fa_root.matrix_world @ Vector((-(pod_l["forearm"] / 2 + 2.0) - 14.0, 0.0, 1.0))
    b0 = fa_root.matrix_world @ Vector((-(pod_l["forearm"] / 2 + 2.0) - 2.0, 0.0, 4.0))
    anchors = [anchor("cab_a0", a0, arm, BONES["arm"]), anchor("cab_a1", a1, arm, BONES["arm"]),
               anchor("cab_elbow", a2, arm, BONES["fore"]), anchor("cab_b1", b1, arm, BONES["fore"]),
               anchor("cab_b0", b0, arm, BONES["fore"])]
    cable(anchors, cable_m)
    return sc, arm, {"upperarm": ua_root, "forearm": fa_root, "chest": ch_root}, cable_m


# ------------------------------------------------------------------------------------------------ poses
def pose_neutral(arm):
    """Arms relaxed by the sides (Rocketbox rest is a T/A pose)."""
    for a_b, f_b, h_b, sgn in ((BONES["arm"], BONES["fore"], BONES["hand"], -1 if SIDE == "right" else 1),
                               (BONES["arm_o"], BONES["fore_o"], BONES["hand_o"], 1 if SIDE == "right" else -1)):
        aim(arm, a_b, Vector((sgn * 0.12, 0.02, -1.0)), ref_child=f_b)
        aim(arm, f_b, Vector((sgn * 0.08, -0.12, -1.0)), ref_child=h_b)


def arm_dir(elev_deg, plane_deg):
    """Humerus direction for elevation (0 = down) in a plane (0 = forward/flexion, 90 = sideways/abduction)."""
    e, p = math.radians(elev_deg), math.radians(plane_deg)
    out = -1 if SIDE == "right" else 1
    return Vector((out * math.sin(e) * math.sin(p), -math.sin(e) * math.cos(p), -math.cos(e)))


def key_arm(arm, frame, elev, plane, elbow_flex=8.0, er_deg=None):
    """Keyframe the affected arm: humerus elevation/plane, forearm straight-ish or ER at 90 deg elbow."""
    bpy.context.scene.frame_set(frame)
    pose_neutral_other(arm)
    aim(arm, BONES["arm"], arm_dir(elev, plane), ref_child=BONES["fore"])
    u = arm_dir(elev, plane)
    if er_deg is None:
        f = arm_dir(min(elev + elbow_flex, 180), plane)
    else:
        out = -1 if SIDE == "right" else 1
        r = math.radians(er_deg)
        f = Vector((out * math.sin(r), -math.cos(r), 0.0))   # elbow 90: forearm horizontal, rotated outward
    aim(arm, BONES["fore"], f, ref_child=BONES["hand"])
    for b in (BONES["arm"], BONES["fore"], BONES["arm_o"], BONES["fore_o"]):
        pb = arm.pose.bones[b]
        pb.rotation_mode = "QUATERNION"
        pb.keyframe_insert("rotation_quaternion", frame=frame)


def pose_neutral_other(arm):
    sgn = 1 if SIDE == "right" else -1
    aim(arm, BONES["arm_o"], Vector((sgn * 0.12, 0.02, -1.0)), ref_child=BONES["fore_o"])
    aim(arm, BONES["fore_o"], Vector((sgn * 0.08, -0.12, -1.0)), ref_child=BONES["hand_o"])


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Quaternion()
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()


# ------------------------------------------------------------------------------------------------ cameras
def camera(name, loc, target, lens=50):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = 4.0
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    tgt = bpy.data.objects.new(name + "_target", None)
    bpy.context.scene.collection.objects.link(tgt)
    tgt.location = target
    tr = cam.constraints.new("TRACK_TO")
    tr.target = tgt
    tr.track_axis, tr.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
    cd.dof.focus_object = tgt
    return cam, tgt


def render_still(sc):
    sc.frame_set(1)
    cam, _ = camera("still_cam", (1.0, -2.6, 1.5), (-0.05, 0, 1.15), 45)
    sc.camera = cam
    OUT.mkdir(parents=True, exist_ok=True)
    sc.render.filepath = str(OUT / "avatar_still.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", sc.render.filepath)


# ------------------------------------------------------------------------------------------------ animation
FPS = 30
SHOTS = {   # name: (first frame, last frame) on the avatar timeline
    "flexion": (1, 180),
    "abduction": (181, 330),
    "rotation": (331, 450),
}


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def rep(i, n, peak, rise=0.28, hold=0.38, start=0.08):
    """Value of a smooth raise-hold-lower rep at frame index i of n."""
    t = i / max(n - 1, 1)
    up = smooth((t - start) / rise)
    down = smooth((t - start - rise - hold) / rise)
    return peak * (up - down)


_prev_q: dict = {}


def key_pose(arm, frame, elev, plane, er=None):
    """Pose + keyframe the affected arm (and keep the other arm relaxed). Quaternions kept sign-continuous."""
    reset_pose(arm)
    pose_neutral_other(arm)
    aim(arm, BONES["arm"], arm_dir(max(elev, 6.0), plane), ref_child=BONES["fore"])
    if er is None:
        f = arm_dir(min(max(elev, 6.0) + 10.0, 179.0), plane)
    else:
        out = -1 if SIDE == "right" else 1
        r = math.radians(er)
        f = Vector((out * math.sin(r), -math.cos(r), -0.05))
    aim(arm, BONES["fore"], f, ref_child=BONES["hand"])
    for b in (BONES["arm"], BONES["fore"], BONES["arm_o"], BONES["fore_o"]):
        pb = arm.pose.bones[b]
        q = pb.rotation_quaternion.copy()
        if b in _prev_q and _prev_q[b].dot(q) < 0:
            q.negate()
            pb.rotation_quaternion = q
        _prev_q[b] = q.copy()
        pb.keyframe_insert("rotation_quaternion", frame=frame)


def animate(arm):
    for name, (f0, f1) in SHOTS.items():
        n = f1 - f0 + 1
        for i in range(0, n, 2):
            fr = f0 + i
            if name == "flexion":
                key_pose(arm, fr, 6 + rep(i, n, 134), 4)
            elif name == "abduction":
                key_pose(arm, fr, 6 + rep(i, n, 104), 88)
            else:
                key_pose(arm, fr, 6, 10, er=rep(i, n, 50, rise=0.25, hold=0.4))
    for act in bpy.data.actions:
        for fc in getattr(act, "fcurves", []):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"


def shot_cameras():
    """One tracking camera per avatar shot, with a slow dolly."""
    cams = {}
    c, t = camera("cam_flexion", (1.6, -2.9, 1.55), (0.0, 0.0, 1.2), 42)
    c.keyframe_insert("location", frame=SHOTS["flexion"][0])
    c.location = (0.7, -3.1, 1.5)
    c.keyframe_insert("location", frame=SHOTS["flexion"][1])
    cams["flexion"] = c
    side = -1 if SIDE == "right" else 1
    c, t = camera("cam_abduction", (side * 1.25, -1.25, 1.55), (side * 0.25, 0.0, 1.35), 50)
    c.keyframe_insert("location", frame=SHOTS["abduction"][0])
    c.location = (side * 1.45, -0.95, 1.6)
    c.keyframe_insert("location", frame=SHOTS["abduction"][1])
    cams["abduction"] = c
    c, t = camera("cam_rotation", (side * 0.95, -0.85, 1.3), (side * 0.3, -0.12, 1.12), 50)
    c.keyframe_insert("location", frame=SHOTS["rotation"][0])
    c.location = (side * 0.55, -1.05, 1.3)
    c.keyframe_insert("location", frame=SHOTS["rotation"][1])
    cams["rotation"] = c
    return cams


def render_range(sc, cam, f0, f1, folder):
    d = OUT / "frames" / folder
    d.mkdir(parents=True, exist_ok=True)
    sc.camera = cam
    sc.frame_start, sc.frame_end = f0, f1
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = str(d) + "/"
    bpy.ops.render.render(animation=True)
    print("rendered", folder, f0, f1)


# ------------------------------------------------------------------------------------------------ product shot
def product_shot(n=120):
    sc = reset()
    light("key", (0.25, -0.3, 0.35), 40, 0.25, target=(0, 0, 0.02))
    light("fill", (-0.35, -0.15, 0.12), 12, 0.4, target=(0, 0, 0.02))
    light("rim", (0, 0.35, 0.25), 25, 0.2, target=(0, 0, 0.02))
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=0.5, fill_type="NGON", location=(0, 0, -0.0135))
    bpy.context.object.data.materials.append(mat("floor", (0.05, 0.06, 0.075, 1), 0.3))
    root, parts = import_unit("unit_upperarm")
    lift = {"lid": 34.0, "lipo": 22.0, "drv2605": 22.0, "deck": 14.0, "bno085": 7.0, "xiao": 7.0, "switch": 7.0,
            "motor": 4.0}
    for o in parts:
        k = next((k for k in lift if k in o.name.lower()), None)
        if k is None:
            continue
        z0 = o.location.z
        for fr, f in ((1, 1.0), (int(n * 0.25), 1.0), (int(n * 0.75), 0.0), (n, 0.0)):
            o.location.z = z0 + lift[k] * f
            o.keyframe_insert("location", index=2, frame=fr)
    c, t = camera("cam_product", (0.12, -0.17, 0.11), (0, 0, 0.012), 70)
    c.data.dof.aperture_fstop = 8.0
    for fr, ang in ((1, -35), (n, 25)):
        a = math.radians(ang)
        c.location = (0.21 * math.sin(a), -0.21 * math.cos(a), 0.11)
        c.keyframe_insert("location", frame=fr)
    render_range(sc, c, 1, n, "1_product")


# ------------------------------------------------------------------------------------------------ edit
CAPTIONS = [
    ("1_product", "Physio Buddy upper-arm pod", "BNO085 IMU + XIAO ESP32-S3 + haptics + 500 mAh LiPo, PB-rail quick release"),
    ("2_flexion", f"Worn: upper arm, forearm, {TRUNK}", "Strap-fixed rail mounts: each sensor sits the same way every session"),
    ("3_abduction", "Side raise", f"The pod moves rigidly with the humerus; the {TRUNK} pod is the body reference"),
    ("4_rotation", "Outward rotation, elbow at 90", "The forearm pod measures rotation the camera cannot see"),
]


def edit_video(out_name="physio_buddy_device.mp4"):
    sc = reset()
    sc.sequence_editor_create()
    seq = sc.sequence_editor
    frame = 1
    for ch, (folder, title, sub) in enumerate(CAPTIONS):
        files = sorted((OUT / "frames" / folder).glob("*.png"))
        if not files:
            print("missing frames for", folder)
            continue
        strip = seq.strips.new_image(folder, str(files[0]), channel=1, frame_start=frame)
        for f in files[1:]:
            strip.elements.append(f.name)
        n = len(files)
        for text, size, y, start_off in ((title, 64, 0.12, 6), (sub, 34, 0.065, 12)):
            t = seq.strips.new_effect(f"{folder}_{size}", "TEXT", channel=2 if size == 64 else 3,
                                      frame_start=frame + start_off, length=n - start_off - 4)
            t.text = text
            t.font_size = size
            t.location = (0.06, y)
            t.anchor_x = "LEFT"
            t.color = (0.92, 0.95, 0.96, 1) if size == 64 else (0.31, 0.78, 0.65, 1)
            t.use_shadow = True
            t.use_box = True   # dark backing so captions read on the white product shot and over the body
            t.box_color = (0.02, 0.025, 0.03, 0.72)
            t.box_margin = 0.012
        frame += n
    sc.frame_start, sc.frame_end = 1, frame - 1
    if hasattr(sc.render.image_settings, "media_type"):   # Blender 5: video output is a separate media type
        sc.render.image_settings.media_type = "VIDEO"
    sc.render.image_settings.file_format = "FFMPEG"
    sc.render.ffmpeg.format = "MPEG4"
    sc.render.ffmpeg.codec = "H264"
    sc.render.ffmpeg.constant_rate_factor = "HIGH"
    sc.render.ffmpeg.ffmpeg_preset = "GOOD"
    sc.render.filepath = str(OUT / out_name)
    bpy.ops.render.render(animation=True)
    print("video", sc.render.filepath, "frames", frame - 1)


if __name__ == "__main__":
    if MODE == "product":
        product_shot()
    elif MODE == "edit":
        edit_video()
    else:
        sc, arm, units, cable_m = build()
        reset_pose(arm)
        pose_neutral(arm)
        if MODE == "still":
            render_still(sc)
            bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "avatar_scene.blend"))
        elif MODE in ("shots", "test"):
            animate(arm)
            cams = shot_cameras()
            for i, name in enumerate(SHOTS, start=2):
                f0, f1 = SHOTS[name]
                if MODE == "test":   # one frame at the peak of each rep
                    mid = f0 + int((f1 - f0) * 0.5)
                    sc.camera = cams[name]
                    sc.frame_set(mid)
                    sc.render.filepath = str(OUT / f"test_{name}.png")
                    bpy.ops.render.render(write_still=True)
                    print("rendered", sc.render.filepath)
                else:
                    render_range(sc, cams[name], f0, f1, f"{i}_{name}")
            bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "avatar_scene.blend"))
