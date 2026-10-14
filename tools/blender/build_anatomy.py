"""Build the rigged, real-anatomy GLB used by the station's X-ray view.

    blender -b --factory-startup -P tools/blender/build_anatomy.py -- <zanatomy_dir> <out.glb>

Source: Z-Anatomy FBX exports (SkeletalSystem100 / MuscularSystem100 / Joints100), derived from BodyParts3D.
LICENCE OF THE OUTPUT: CC BY-SA 4.0. Attribution: "BodyParts3D, The Database Center for Life Science,
CC BY-SA 2.1 Japan" and "Z-Anatomy, CC BY-SA 4.0".

Output: one skinned model (Z-Anatomy is in anatomical position: arms down, facing -Y, Z up, metres)
  * PB_SKELETON: all bones joined (rigid weights per bone)
  * PB_M__<muscle>__<L|R>: each shoulder/arm muscle separate (fibre shader + highlighting in the app)
  * PB_J__<structure>__<L|R>: shoulder joint capsule, labrum, ligaments, bursa
  * armature bones PB_Pelvis > PB_Thorax > (PB_Neck > PB_Head), PB_Girdle_X > PB_Humerus_X > PB_Forearm_X > PB_Hand_X
Muscles crossing the shoulder/elbow get smooth weights so they stretch when the arm moves.
"""

import re
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = Path(argv[0]), Path(argv[1])

SHOULDER_MUSCLES = [
    "Acromial part of deltoid muscle", "Clavicular part of deltoid muscle", "Scapular spinal part of deltoid muscle",
    "Descending part of trapezius muscle", "Transverse part of trapezius muscle", "Ascending part of trapezius muscle",
    "Supraspinatus muscle", "Infraspinatus muscle", "Teres minor muscle", "Teres major muscle", "Subscapularis muscle",
    "Clavicular head of pectoralis major muscle", "Sternocostal head of pectoralis major muscle", "Pectoralis minor muscle",
    "Long head of biceps brachii", "Short head of biceps brachii", "Long head of triceps brachii",
    "Lateral head of triceps brachii", "Medial head of triceps brachii", "Coracobrachialis muscle",
    "Brachialis muscle", "Brachioradialis muscle", "Latissimus dorsi muscle", "Rhomboid major muscle",
    "Rhomboid minor muscle", "Levator scapulae", "Serratus anterior muscle", "Sternocleidomastoid muscle",
    "Extensor carpi radialis longus", "Extensor carpi radialis brevis", "Flexor carpi radialis",
    "Humeral head of flexor carpi ulnaris", "Humero-ulnar head of flexor digitorum superficialis",
    "Superficial head of pronator teres", "Humeral head of extensor carpi ulnaris", "Subdeltoid bursa",
]
SHOULDER_JOINTS = [
    "Articular capsule of glenohumeral joint", "Glenoid labrum", "Superior glenohumeral ligament",
    "Middle glenohumeral ligament", "Inferior glenohumeral ligament", "Coracohumeral ligament",
    "Transverse humeral ligament", "Articular capsule of acromioclavicular joint", "Acromioclavicular ligament",
    "Articular capsule of sternoclavicular joint", "Articular capsule of elbow joint",
]
# Muscles whose proximal part belongs to the thorax (not the shoulder girdle)
THORAX_ORIGIN = ("pectoralis major", "Latissimus", "Sternocleidomastoid")
# Muscles spanning spine <-> scapula: blend thorax/girdle by distance from the midline
MIDLINE_BLEND = ("trapezius", "Rhomboid", "Levator scapulae", "Serratus")

MARKER = re.compile(r"\.(o|e|i|j)[0-9]*[lr]?$|^\(|^\[")
HAND_BONE = re.compile(r"metacarpal|phalanx of .* hand|phalanx of .*finger of hand|Scaphoid|Lunate|Triquetrum|"
                       r"Pisiform|Trapezium|Trapezoid|Capitate|Hamate|Sesamoid bones? of hand", re.I)
LOWER_BODY = re.compile(r"Femur|Tibia|Fibula|Patella|Hip bone|Sacrum|Coccy|Vertebra L|foot|Talus|Calcaneus|Navicular|"
                        r"Cuboid|Cuneiform|metatarsal|toe", re.I)
HEAD_BONE = re.compile(r"Frontal|Parietal|Occipital|Temporal|Sphenoid|Ethmoid|Mandible|Maxilla|Zygomatic|Nasal|"
                       r"Lacrimal|Palatine|Vomer|concha|Hyoid|tooth|teeth|incisor|molar|canine", re.I)


def side_of(name):
    return "R" if name.endswith(".r") else "L" if name.endswith(".l") else None


def base_name(name):
    return re.sub(r"\.(l|r)$", "", name)


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
    return [o for o in bpy.data.objects if o not in before]


def keep_only(objs, predicate):
    keep = [o for o in objs if o.type == "MESH" and predicate(o)]
    # freeze world transforms first: removing the importer's parent empties would drop them
    bpy.context.view_layer.update()
    frozen = [(o, o.matrix_world.copy()) for o in keep]
    for o, mw in frozen:
        o.parent = None
        o.matrix_world = mw
    drop = [o for o in objs if o not in keep]
    bpy.data.batch_remove(drop)
    return keep


def world_verts(o):
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(o.matrix_world)
    return co @ M[:3, :3].T + M[:3, 3]


def bake(o, ratio):
    """Apply transforms and decimate (via evaluated copy, fast), smooth shading."""
    o.parent = None
    o.data = o.data.copy()
    o.data.transform(o.matrix_world)
    o.matrix_world.identity()
    if ratio < 0.999:
        m = o.modifiers.new("dec", "DECIMATE")
        m.ratio = ratio
        dg = bpy.context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
        o.modifiers.clear()
        o.data = new
    for p in o.data.polygons:
        p.use_smooth = True


bpy.ops.wm.read_factory_settings(use_empty=True)
bones_objs = keep_only(import_fbx(SRC / "SkeletalSystem100.fbx"),
                       lambda o: not MARKER.search(o.name) and len(o.data.vertices) > 60)
mus_names = {f"{m}.{s}" for m in SHOULDER_MUSCLES for s in "lr"}
muscles = keep_only(import_fbx(SRC / "MuscularSystem100.fbx"), lambda o: o.name in mus_names)
joint_names = {f"{j}.{s}" for j in SHOULDER_JOINTS for s in "lr"}
joints = keep_only(import_fbx(SRC / "Joints100.fbx"), lambda o: o.name in joint_names)
print("selected", len(bones_objs), "bones,", len(muscles), "muscles,", len(joints), "joint structures")
print("missing muscles", sorted(mus_names - {o.name for o in muscles}))
print("missing joints", sorted(joint_names - {o.name for o in joints}))

by_name = {o.name: o for o in bones_objs}

# ---------------------------------------------------------------- landmarks (before decimation)
def centroid(objs, sel=None):
    v = np.concatenate([world_verts(o) for o in objs])
    return (v[sel(v)] if sel else v).mean(0)


L = {}
for s, sfx in (("R", "r"), ("L", "l")):
    hum = world_verts(by_name[f"Humerus.{sfx}"])
    zmax, zmin = hum[:, 2].max(), hum[:, 2].min()
    head = hum[hum[:, 2] > zmax - 0.035].mean(0)
    head[0] -= np.sign(head[0]) * 0.008                       # tubercles pull the centroid lateral
    elbow = hum[hum[:, 2] < zmin + 0.02].mean(0)
    fa = np.concatenate([world_verts(by_name[f"Radius.{sfx}"]), world_verts(by_name[f"Ulna.{sfx}"])])
    wrist = fa[fa[:, 2] < fa[:, 2].min() + 0.015].mean(0)
    mc = world_verts(by_name[f"Third metacarpal bone.{sfx}"])
    hand_end = mc[mc[:, 2] < mc[:, 2].min() + 0.01].mean(0)
    clav = world_verts(by_name[f"Clavicle.{sfx}"])
    sc = clav[np.abs(clav[:, 0]) < np.abs(clav[:, 0]).min() + 0.01].mean(0)
    L[s] = dict(head=head, elbow=elbow, wrist=wrist, hand_end=hand_end, sc=sc)
L["L1"] = centroid([by_name["Vertebra L1"]])
L["C7"] = centroid([by_name["Vertebra C7"]])
L["skull"] = centroid([by_name["Frontal bone"], by_name["Occipital bone"]])
L["pelvis"] = centroid([by_name["Sacrum"]])
for k, v in L.items():
    print("landmark", k, {kk: np.round(vv, 3).tolist() for kk, vv in v.items()} if isinstance(v, dict) else np.round(v, 3).tolist())

# ---------------------------------------------------------------- bake + decimate
for o in bones_objs:
    n = len(o.data.vertices)
    bake(o, min(1.0, max(150, n * 0.14) / n))
for o in muscles:
    n = len(o.data.vertices)
    bake(o, min(1.0, max(400, n * 0.5) / n))
for o in joints:
    bake(o, 1.0)

# ---------------------------------------------------------------- armature
bpy.ops.object.armature_add(location=(0, 0, 0))
arm = bpy.context.object
arm.name = arm.data.name = "PB_Rig"
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
eb.remove(eb[0])


def bone(name, head, tail, parent=None):
    b = eb.new(name)
    b.head, b.tail = tuple(head), tuple(tail)
    if parent:
        b.parent = eb[parent]
    return name


bone("PB_Pelvis", L["pelvis"], L["L1"])
bone("PB_Thorax", L["L1"], L["C7"], "PB_Pelvis")
bone("PB_Neck", L["C7"], L["skull"], "PB_Thorax")
bone("PB_Head", L["skull"], L["skull"] + np.array([0, 0, 0.1]), "PB_Neck")
for s in "RL":
    p = L[s]
    bone(f"PB_Girdle_{s}", p["sc"], p["head"], "PB_Thorax")
    bone(f"PB_Humerus_{s}", p["head"], p["elbow"], f"PB_Girdle_{s}")
    bone(f"PB_Forearm_{s}", p["elbow"], p["wrist"], f"PB_Humerus_{s}")
    bone(f"PB_Hand_{s}", p["wrist"], p["hand_end"], f"PB_Forearm_{s}")
bpy.ops.object.mode_set(mode="OBJECT")
BONES = [b.name for b in arm.data.bones]


# ---------------------------------------------------------------- weights
def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def bone_group(name):
    s = side_of(name)
    b = base_name(name)
    if s and b == "Humerus":
        return f"PB_Humerus_{s}"
    if s and b in ("Radius", "Ulna"):
        return f"PB_Forearm_{s}"
    if s and HAND_BONE.search(b):
        return f"PB_Hand_{s}"
    if s and b in ("Scapula", "Clavicle"):
        return f"PB_Girdle_{s}"
    if LOWER_BODY.search(b):
        return "PB_Pelvis"
    if HEAD_BONE.search(b):
        return "PB_Head"
    if re.search(r"Vertebra C|Atlas|Axis", b):
        return "PB_Neck"
    return "PB_Thorax"


def limb_weights(o, s, proximal_group):
    """Smooth weights for a soft-tissue mesh on side s: hand / forearm / humerus / proximal."""
    p = world_verts(o)
    J = L[s]
    fdir = (J["wrist"] - J["elbow"]) / np.linalg.norm(J["wrist"] - J["elbow"])
    hdir = (J["hand_end"] - J["wrist"]) / np.linalg.norm(J["hand_end"] - J["wrist"])
    d_hum = seg_dist(p, J["head"], J["elbow"])
    d_fore = seg_dist(p, J["elbow"], J["wrist"])
    d_hand = seg_dist(p, J["wrist"], J["wrist"] + hdir * 0.22)   # wrist -> fingertips
    distal = (d_fore < 0.08) | (d_hand < 0.09)                    # forearm muscles with tendons into the hand
    w_hand = smooth(-0.005, 0.02, (p - J["wrist"]) @ hdir) * (d_hand < 0.09)
    w_fore = smooth(-0.015, 0.025, (p - J["elbow"]) @ fdir) * distal * (1 - w_hand)
    w_hum = (1 - smooth(0.035, 0.08, d_hum)) * (1 - w_fore - w_hand)
    w_prox = np.clip(1 - w_hand - w_fore - w_hum, 0, 1)
    W = {f"PB_Hand_{s}": w_hand, f"PB_Forearm_{s}": w_fore, f"PB_Humerus_{s}": w_hum}
    if isinstance(proximal_group, tuple):  # midline blend thorax <-> girdle
        wg = smooth(0.05, 0.12, np.abs(p[:, 0]))
        W[proximal_group[0]] = w_prox * (1 - wg)
        W[proximal_group[1]] = w_prox * wg
    else:
        W[proximal_group] = w_prox
    return W


def write_groups(o, W):
    total = sum(W.values())
    total[total == 0] = 1
    for g, w in W.items():
        w = w / total
        idx = np.nonzero(w > 0.002)[0]
        if len(idx) == 0:
            continue
        vg = o.vertex_groups.get(g) or o.vertex_groups.new(name=g)
        for i in idx:
            vg.add([int(i)], float(w[i]), "REPLACE")


def bind(o):
    o.parent = arm
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def mat(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    return m


for o in bones_objs:
    g = bone_group(o.name)
    vg = o.vertex_groups.new(name=g)
    vg.add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
    o.data.materials.clear()
    o.data.materials.append(mat("Bone", (0.91, 0.87, 0.78)))

for o in muscles:
    s = side_of(o.name)
    b = base_name(o.name)
    if any(k in b for k in MIDLINE_BLEND):
        prox = ("PB_Thorax", f"PB_Girdle_{s}")
    elif any(k in b for k in THORAX_ORIGIN):
        prox = "PB_Thorax"
    else:
        prox = f"PB_Girdle_{s}"
    write_groups(o, limb_weights(o, s, prox))
    o.data.materials.clear()
    o.data.materials.append(mat("Bursa" if "bursa" in b else "Muscle", (0.62, 0.16, 0.14)))
    o.name = f"PB_M__{b.replace(' ', '_')}__{s}"

for o in joints:
    s = side_of(o.name)
    b = base_name(o.name)
    W = limb_weights(o, s, f"PB_Girdle_{s}") if "elbow" in b else {f"PB_Girdle_{s}": np.ones(len(o.data.vertices))}
    write_groups(o, W)
    o.data.materials.clear()
    o.data.materials.append(mat("Ligament", (0.85, 0.88, 0.95)))
    o.name = f"PB_J__{b.replace(' ', '_')}__{s}"

# join all bones into one mesh (one draw call); vertex groups merge by name
bpy.ops.object.select_all(action="DESELECT")
for o in bones_objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = bones_objs[0]
bpy.ops.object.join()
skeleton = bpy.context.view_layer.objects.active
skeleton.name = "PB_SKELETON"

for o in [skeleton] + muscles + joints:
    bind(o)

stats = {"skeleton_verts": len(skeleton.data.vertices),
         "muscle_verts": sum(len(o.data.vertices) for o in muscles),
         "joint_verts": sum(len(o.data.vertices) for o in joints), "bones": BONES}
print("stats", stats)

OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(OUT), export_format="GLB", export_skins=True, export_animations=False,
                          export_yup=True, export_morph=False, export_materials="EXPORT")
print("wrote", OUT, OUT.stat().st_size)
