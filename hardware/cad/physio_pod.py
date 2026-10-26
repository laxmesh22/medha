"""Physio Buddy wearable hardware: parametric CAD (CadQuery / OpenCascade).

    tools/cad/.venv/Scripts/python.exe hardware/cad/physio_pod.py            # build, fit-check, export everything

Parts (all dimensions mm, print in PETG or PLA, 0.2 mm layers):
  pod_arm_body / pod_arm_deck / pod_arm_lid     Unit A on the upper arm: BNO085 + XIAO ESP32-S3 + coin motor (bottom
                                                layer), 500 mAh LiPo + DRV2605L on the deck (top layer)
  pod_forearm_body / pod_forearm_lid            BNO085 #2 only, Qwiic cable from the arm pod
  pod_chest_lid                                 Unit B uses the arm pod body + deck, with its own lid label
  base_upperarm / base_forearm / base_chest     curved strap saddles: 25 mm velcro slots, PB-rail receiver, click latch

PB-rail: every pod has a dovetail tongue underneath and slides into any base from its +X end until it clicks.
Pull the press tab down to release. The rail fixes the pod's orientation on the strap, so the sensor sits the same
way every session (handoff section 6.3: rigid, repeatable placement) and the pod comes off to charge.

Component bays are sized from seller data with clearance. MEASURE your boards and edit COMPONENTS, then re-run:
the fit check fails loudly if anything collides.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parent / "out"
FONT = "C:/Windows/Fonts/arialbd.ttf"

# ------------------------------------------------------------------------------------------------ parameters
WALL = 2.0          # side walls
FLOOR = 2.0         # pod floor
LID = 2.0           # lid plate
CLR = 0.3           # clearance around every component (per side)
CORNER_R = 3.0      # outer vertical edge radius

# Components: (length X, width Y, height Z). Sources: 7Semi BNO055 listing 27x21x4.75 (BNO085 assumed same family),
# Adafruit BNO085 25.6x22.7x4.6; XIAO ESP32-S3 21x17.8, ~3.6 with USB-C; LiPo 752530 7.5x25x30 + PCM;
# DRV2605L breakouts 23.5x19x5.3; ERM coin motor 10x2.7; SS-12D00 slide switch 8.6x3.6x3.5.
COMPONENTS = {
    "bno085": (27.0, 23.0, 4.8),       # bay fits 7Semi and Adafruit boards
    "xiao": (21.0, 17.8, 3.6),
    "lipo": (33.0, 26.0, 8.0),
    "drv2605": (19.5, 24.0, 5.3),      # rotated: 19.5 along X
    "motor": (10.0, 10.0, 2.7),
    "switch": (3.6, 8.6, 3.5),         # body: 3.6 deep (X) x 8.6 (Y)
}
XIAO_RAISE = 2.2    # XIAO sits on rails: room for BAT-pad wires and the coin motor underneath
BNO_PADS = 1.0      # BNO085 rests on corner pads (clears solder joints)
DECK = 1.2          # deck plate between the two layers

# PB-rail (dovetail along X): narrow at the pod face, wide at the bottom
RAIL_H = 3.0
RAIL_W_TOP = 16.0
RAIL_W_BOT = 20.0
RAIL_END = 3.0      # tongue stops this far short of each pod end
RAIL_CLR = 0.25
STOP_WALL = 3.0     # base wall at the -X end that the pod pushes against
STRAP_W = 25.0      # velcro strap width
STRAP_T = 3.6       # slot thickness (strap + fold)
BASE_FLOOR = 1.8    # material under the rail channel at the centre line (also the latch beam thickness)
LIP = 1.8           # lid locating lip hangs this far into the pod: kept clear of the top components


@dataclass
class PodSpec:
    name: str
    inner_l: float
    inner_w: float
    inner_h: float
    layers: dict = field(default_factory=dict)

    @property
    def outer_l(self):
        return self.inner_l + 2 * WALL

    @property
    def outer_w(self):
        return self.inner_w + 2 * WALL

    @property
    def body_h(self):
        return FLOOR + self.inner_h


def arm_spec() -> PodSpec:
    b, x, li, d, sw = (COMPONENTS[k] for k in ("bno085", "xiao", "lipo", "drv2605", "switch"))
    bottom_l = sw[0] + 1.0 + (b[0] + 2 * CLR) + 1.2 + (x[0] + 2 * CLR) + 1.2   # switch | BNO | divider | XIAO | USB
    top_l = (li[0] + 2 * CLR) + 1.2 + (d[0] + 2 * CLR)
    inner_l = round(max(bottom_l, top_l) + 0.5, 1)
    inner_w = round(max(b[1], x[1], li[1], d[1]) + 2 * CLR, 1)
    h_bottom = max(BNO_PADS + b[2], XIAO_RAISE + x[2]) + 0.8
    h_top = max(li[2], d[2]) + 0.6
    return PodSpec("arm", inner_l, inner_w, round(h_bottom + DECK + h_top + LIP, 1),
                   {"bottom_h": round(h_bottom, 2), "top_h": round(h_top, 2)})


def forearm_spec() -> PodSpec:
    b = COMPONENTS["bno085"]
    return PodSpec("forearm", round(b[0] + 2 * CLR + 5.0, 1), round(b[1] + 2 * CLR + 0.8, 1),
                   round(BNO_PADS + b[2] + 0.8 + LIP, 1), {"bottom_h": round(BNO_PADS + b[2] + 0.8, 2)})


# ------------------------------------------------------------------------------------------------ helpers
def box(l, w, h, x=0.0, y=0.0, z=0.0, r=0.0):
    """Axis-aligned box from z to z+h, centred on (x, y)."""
    b = cq.Workplane("XY").box(l, w, h, centered=(True, True, False))
    if r > 0:
        b = b.edges("|Z").fillet(r)
    return b.translate((x, y, z))


def prism_x(points_yz, x0, length):
    """Extrude a (y, z) polygon along +X from x0."""
    return cq.Workplane("YZ").polyline(points_yz).close().extrude(length).translate((x0, 0, 0))


def prism_y(points_xz, width):
    """Extrude an (x, z) polygon symmetrically along Y."""
    wp = cq.Workplane("XZ").polyline(points_xz).close().extrude(width / 2, both=True)
    return wp


def engrave(part, text, size, x, y, z_top, depth=0.5, rot=0):
    t = (cq.Workplane("XY").text(text, size, -depth, combine=False, fontPath=FONT, halign="center", valign="center")
         .rotate((0, 0, 0), (0, 0, 1), rot).translate((x, y, z_top)))
    return part.cut(t)


def arrow(x, y, z, length, width, height, pointing=+1):
    """Raised arrow on a top face, pointing along +X (pointing=+1) or -X."""
    s = pointing
    pts = [(-length / 2, -width * 0.18), (length * 0.15, -width * 0.18), (length * 0.15, -width / 2), (length / 2, 0),
           (length * 0.15, width / 2), (length * 0.15, width * 0.18), (-length / 2, width * 0.18)]
    pts = [(s * px, py) for px, py in pts]
    return cq.Workplane("XY").polyline(pts).close().extrude(height).translate((x, y, z))


def tongue(spec: PodSpec):
    """PB-rail tongue under a pod (z from -RAIL_H to 0) with a chamfered leading (-X) end."""
    length = spec.outer_l - 2 * RAIL_END
    pts = [(-RAIL_W_TOP / 2, 0), (RAIL_W_TOP / 2, 0), (RAIL_W_BOT / 2, -RAIL_H), (-RAIL_W_BOT / 2, -RAIL_H)]
    t = prism_x(pts, -length / 2, length)
    lead = prism_y([(-length / 2 - 0.01, -RAIL_H - 0.01), (-length / 2 + 2.0, -RAIL_H - 0.01),
                    (-length / 2 - 0.01, -RAIL_H + 1.4)], RAIL_W_BOT + 2)
    return t.cut(lead)


# ------------------------------------------------------------------------------------------------ pods
def pod_body(spec: PodSpec):
    L, W, H = spec.outer_l, spec.outer_w, spec.body_h
    body = box(L, W, H, r=CORNER_R)
    body = body.cut(box(spec.inner_l, spec.inner_w, spec.inner_h + 1, z=FLOOR, r=1.0))
    body = body.union(tongue(spec))
    x0 = -spec.inner_l / 2               # inner -X face
    zf = FLOOR
    b = COMPONENTS["bno085"]

    if spec.name == "forearm":
        bx = x0 + 5.0 + (b[0] + 2 * CLR) / 2
        for sx in (-1, 1):
            for sy in (-1, 1):
                body = body.union(box(3, 3, BNO_PADS, x=bx + sx * (b[0] / 2 - 2), y=sy * (b[1] / 2 - 2), z=zf))
        for sy in (-1, 1):   # crush ribs hold the board snugly in Y
            body = body.union(box(6, 0.5, BNO_PADS + 2.0, x=bx, y=sy * (b[1] / 2 + CLR + 0.15), z=zf))
        body = body.cut(cq.Workplane("YZ").circle(2.6).extrude(WALL + 2).translate((-L / 2 - 1, 0, zf + 3.0)))
        spec.layers["bno_center"] = (round(bx, 2), 0.0)
        return body, {}

    x_, sw, li, d = COMPONENTS["xiao"], COMPONENTS["switch"], COMPONENTS["lipo"], COMPONENTS["drv2605"]
    hb = spec.layers["bottom_h"]
    # bottom layer, -X -> +X: switch | BNO085 bay | divider | XIAO cradle | USB-C wall
    bno_x0 = x0 + sw[0] + 1.0
    bx = bno_x0 + (b[0] + 2 * CLR) / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.union(box(3, 3, BNO_PADS, x=bx + sx * (b[0] / 2 - 2), y=sy * (b[1] / 2 - 2), z=zf))
    for sy in (-1, 1):
        body = body.union(box(6, 0.5, BNO_PADS + 2.0, x=bx, y=sy * (b[1] / 2 + CLR + 0.15), z=zf))
    div_x = bno_x0 + b[0] + 2 * CLR + 0.6
    body = body.union(box(1.2, spec.inner_w, hb, x=div_x, z=zf))
    xiao_x1 = spec.inner_l / 2 - 1.2              # USB-C overhangs the PCB by ~1 mm
    xiao_cx = xiao_x1 - x_[0] / 2
    for sy in (-1, 1):
        body = body.union(box(x_[0] - 4, 1.6, XIAO_RAISE, x=xiao_cx - 1, y=sy * (x_[1] / 2 - 0.7), z=zf))      # rails
        body = body.union(box(x_[0] - 4, 1.0, XIAO_RAISE + 1.6, x=xiao_cx - 1, y=sy * (x_[1] / 2 + CLR + 0.5), z=zf))
    body = body.union(box(1.2, 6, XIAO_RAISE + 1.6, x=xiao_x1 - x_[0] - 0.6 - CLR, z=zf))                      # back stop
    body = body.cut(cq.Workplane("XY").circle(5.3).extrude(1.0).translate((xiao_cx, 0, zf - 1.0)))              # motor
    # USB-C cutout in the +X wall, centred on the connector (sits on top of the PCB)
    usb_z = zf + XIAO_RAISE + 1.2 + 1.6
    body = body.cut(box(WALL + 2, 9.6, 4.2, x=L / 2 - WALL / 2, z=usb_z - 2.1, r=0)
                    .edges("|X").fillet(1.6))
    # switch lever slot + Qwiic cable grommet in the -X wall
    body = body.cut(box(WALL + 2, 7.4, 2.8, x=-L / 2 + WALL / 2, y=-6.0, z=zf + 1.0))
    body = body.cut(cq.Workplane("YZ").circle(2.6).extrude(WALL + 2).translate((-L / 2 - 1, 6.0, zf + 3.2)))
    # deck ledges along both long walls
    for sy in (-1, 1):
        body = body.union(box(spec.inner_l - 2, 1.0, 1.0, y=sy * (spec.inner_w / 2 - 0.5), z=zf + hb - 1.0))
    spec.layers.update({"bno_center": (round(bx, 2), 0.0), "xiao_center": (round(xiao_cx, 2), 0.0),
                        "div_x": round(div_x, 2), "usb_z": round(usb_z, 2)})
    return body, {"lipo_x0": x0 + 0.3, "drv": d, "lipo": li}


SNAP_LEN = 5.0      # snap ridges: short horizontal half-cylinders on the lid lip, grooves in the body walls


def snap_ridge(x, y, z, r):
    """Cylinder along X centred at (x, y, z). Callers offset y a little into the solid so nothing is tangent."""
    return cq.Workplane("YZ").circle(r).extrude(SNAP_LEN).translate((x - SNAP_LEN / 2, y, z))


def lid_snaps(spec: PodSpec, body):
    """Grooves in the body's inner long walls that the lid's ridges snap into."""
    z = spec.body_h - LIP / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.cut(snap_ridge(sx * spec.inner_l * 0.28, sy * (spec.inner_w / 2 + 0.1), z, 0.6))
    return body


def pod_lid(spec: PodSpec, label: str):
    L, W = spec.outer_l, spec.outer_w
    z0 = spec.body_h
    lid = box(L, W, LID, z=z0, r=CORNER_R)
    lip_l, lip_w = spec.inner_l - 0.3, spec.inner_w - 0.3
    lip = box(lip_l, lip_w, LIP, z=z0 - LIP, r=0.8).cut(box(lip_l - 2.4, lip_w - 2.4, LIP, z=z0 - LIP, r=0.5))
    lid = lid.union(lip)
    for sx in (-1, 1):
        for sy in (-1, 1):
            lid = lid.union(snap_ridge(sx * spec.inner_l * 0.28, sy * (lip_w / 2 - 0.1), z0 - LIP / 2, 0.45))
    lid = lid.cut(box(6, 2.2, 1.0, x=L / 2 - 3, z=z0 + LID - 1.0))                         # pry notch
    lid = lid.union(arrow(-L * 0.12, 0, z0 + LID, min(22, L * 0.38), 9, 0.6, pointing=+1))
    lid = engrave(lid, label, 4.2 if spec.name == "arm" else 3.4, L * 0.22, 0, z0 + LID, depth=0.5)
    return lid


def pod_deck(spec: PodSpec, info: dict):
    """Plate between the layers: LiPo pocket + DRV2605L pocket, wire notches."""
    hb = spec.layers["bottom_h"]
    z0 = FLOOR + hb
    l, w = spec.inner_l - 0.4, spec.inner_w - 0.4
    deck = box(l, w, DECK, z=z0, r=0.8)
    li, d = info["lipo"], info["drv"]
    sep_x = -spec.inner_l / 2 + li[0] + 2 * CLR + 0.6
    deck = deck.union(box(1.2, w - 3, 2.0, x=sep_x, z=z0 + DECK))
    for x in (-l / 2 + 4, l / 2 - 4):
        deck = deck.cut(box(5.0, 3.0, DECK, x=x, y=w / 2 - 2.0, z=z0))
    spec.layers.update({"deck_z": round(z0, 2), "sep_x": round(sep_x, 2)})
    return deck


# ------------------------------------------------------------------------------------------------ bases
def base(spec: PodSpec, name: str, radius: float, label: str, label_gap: float = 4.5, strap_w: float = STRAP_W):
    """Curved strap saddle with PB-rail receiver, stop wall, click latch and velcro slots.

    Cross-section from the centre out: pod seat | label strip (``label_gap``: arrow on +Y, text on -Y) | strap slot.
    """
    Lb = spec.outer_l + 4.0
    strip_y = spec.outer_w / 2 + 0.5                 # inner edge of the label strip
    slot_y = strip_y + label_gap + STRAP_T / 2
    Wb = 2 * (slot_y + STRAP_T / 2 + 2.5)
    ch_d = RAIL_H + RAIL_CLR
    z_bot_c = -(ch_d + BASE_FLOOR)          # underside at the centre line
    zc = z_bot_c - radius                   # cylinder (limb) axis
    depth = 14.0
    wing_top = -ch_d + 0.4
    blk = box(Lb, spec.outer_w + 1.0, depth, z=-depth, r=2.0)
    wings = box(Lb, Wb, depth - (-wing_top), z=-depth, r=3.0)
    b = blk.union(wings)
    limb = cq.Workplane("YZ").circle(radius).extrude(Lb + 20).translate((-Lb / 2 - 10, 0, zc))
    b = b.cut(limb)
    # dovetail channel, open at +X, stop wall at -X
    pts = [(-(RAIL_W_TOP / 2 + RAIL_CLR), 0.01), ((RAIL_W_TOP / 2 + RAIL_CLR), 0.01),
           ((RAIL_W_BOT / 2 + RAIL_CLR), -ch_d), (-(RAIL_W_BOT / 2 + RAIL_CLR), -ch_d)]
    b = b.cut(prism_x(pts, -Lb / 2 + STOP_WALL, Lb))
    # velcro slots through the wings
    for sy in (-1, 1):
        b = b.cut(box(strap_w + 1.5, STRAP_T, 40, y=sy * slot_y, z=-30, r=0.8))
    # latch: cantilever beam in the channel floor, anchored toward -X, free end + press tab past the +X end
    pod_cx = -Lb / 2 + STOP_WALL + RAIL_END - (-spec.outer_l / 2)       # pod centre when seated
    tongue_end = pod_cx + spec.outer_l / 2 - RAIL_END
    beam_w = 7.0
    beam_x0 = tongue_end - 13.0
    beam_x1 = Lb / 2
    # two slots free the beam's sides; it stays anchored to the floor at beam_x0 and its +X end is free
    for sy in (-1, 1):
        b = b.cut(box(beam_x1 - beam_x0 + 6, 1.0, 30, x=(beam_x0 + beam_x1) / 2 + 3, y=sy * (beam_w / 2 + 0.5),
                      z=-ch_d - 25))
    b = b.cut(box(beam_x1 - beam_x0, beam_w + 2.0, 0.6, x=(beam_x0 + beam_x1) / 2 + 1, z=-ch_d - 0.6))   # flex relief
    hook = prism_y([(tongue_end + 0.25, -ch_d), (tongue_end + 0.25, -ch_d + 1.2), (tongue_end + 1.4, -ch_d + 1.2),
                    (tongue_end + 3.6, -ch_d)], beam_w - 1.0)
    b = b.union(hook)
    tab = box(4.0, beam_w, 2.2, x=Lb / 2 + 2.0, z=-ch_d - 1.6)
    b = b.union(tab).union(box(1.2, beam_w, 1.4, x=Lb / 2 + 3.2, z=-ch_d + 0.6))
    # label strip: raised arrow (same direction as the lid arrow) on +Y, engraved label on -Y
    mid = strip_y + label_gap / 2
    b = b.union(arrow(0, mid, wing_top, min(16, Lb * 0.3), label_gap - 1.0, 0.6, pointing=+1))
    b = engrave(b, label, label_gap - 1.6, 0, -mid, wing_top, depth=0.4)
    seat = {"pod_cx": round(pod_cx, 3), "tongue_end": round(tongue_end, 3), "Lb": Lb, "Wb": round(Wb, 2),
            "radius": radius, "beam": [round(beam_x0, 2), round(beam_x1, 2)]}
    return b, seat


# ------------------------------------------------------------------------------------------------ dummies + checks
def dummies(spec: PodSpec, info: dict):
    """Simple solids standing in for the electronics, placed where the bays put them."""
    out = {}
    zf = FLOOR
    b = COMPONENTS["bno085"]
    bx, by = spec.layers["bno_center"]
    out["bno085"] = box(b[0], b[1], b[2], x=bx, y=by, z=zf + BNO_PADS)
    if spec.name == "forearm":
        return out
    x_, li, d, m, sw = (COMPONENTS[k] for k in ("xiao", "lipo", "drv2605", "motor", "switch"))
    xc, _ = spec.layers["xiao_center"]
    out["xiao"] = box(x_[0], x_[1], 1.2, x=xc, z=zf + XIAO_RAISE).union(
        box(7.4, 9.0, 3.2, x=xc + x_[0] / 2 - 3.7 + 1.0, z=zf + XIAO_RAISE + 1.2))      # PCB + USB-C
    out["motor"] = cq.Workplane("XY").circle(m[0] / 2).extrude(m[2]).translate((xc, 0, zf - 1.0 + 0.05))
    out["switch"] = box(sw[0], sw[1], sw[2], x=-spec.inner_l / 2 + sw[0] / 2 + 0.2, y=-6.0, z=zf + 0.7)
    dz = spec.layers["deck_z"] + DECK
    lx = info["lipo_x0"] + li[0] / 2 + CLR
    out["lipo"] = box(li[0], li[1], li[2], x=lx, z=dz)
    out["drv2605"] = box(d[0], d[1], d[2], x=spec.inner_l / 2 - CLR - d[0] / 2, z=dz)
    return out


VENDOR = Path(__file__).resolve().parent / "vendor"
VENDOR_FILES = {   # drop manufacturer STEP files here (any of these names, .step or .stp)
    "bno085": ("bno085", "BNO085"), "xiao": ("xiao_esp32s3", "XIAO_ESP32S3"), "drv2605": ("drv2605l", "DRV2605L"),
    "lipo": ("lipo_752530", "LiPo_752530"), "switch": ("ss12d00", "SS-12D00"), "motor": ("coin_motor_10mm",),
}


def vendor_part(key: str, dummy):
    """Replace a stand-in block with the vendor STEP model when present: rotated 90 deg about Z if that matches the
    bay better, then centred on the stand-in's XY and sat on its bottom face. Returns (shape, note)."""
    for stem in VENDOR_FILES.get(key, ()):
        for ext in (".step", ".stp", ".STEP", ".STP"):
            p = VENDOR / f"{stem}{ext}"
            if not p.exists():
                continue
            shape = cq.importers.importStep(str(p))
            db, vb = dummy.val().BoundingBox(), shape.val().BoundingBox()
            if (vb.xlen > vb.ylen) != (db.xlen > db.ylen):
                shape = shape.rotate((0, 0, 0), (0, 0, 1), 90)
                vb = shape.val().BoundingBox()
            shape = shape.translate((db.center.x - vb.center.x, db.center.y - vb.center.y, db.zmin - vb.zmin))
            note = f"{key}: vendor model {p.name} {vb.xlen:.1f} x {vb.ylen:.1f} x {vb.zlen:.1f} mm"
            if vb.xlen > db.xlen + 2 * CLR or vb.ylen > db.ylen + 2 * CLR or vb.zlen > db.zlen + 0.5:
                note += f"  LARGER than the bay ({db.xlen:.1f} x {db.ylen:.1f} x {db.zlen:.1f}): update COMPONENTS"
            return shape, note
    return dummy, None


def interference(a, b) -> float:
    try:
        return float(a.val().intersect(b.val()).Volume())
    except Exception:
        return 0.0


def fit_check(name, parts: dict, comps: dict, tol=0.5) -> list:
    problems = []
    for cn, c in comps.items():
        for pn, p in parts.items():
            v = interference(c, p)
            if v > tol:
                problems.append(f"{name}: {cn} collides with {pn} ({v:.1f} mm^3)")
    keys = list(comps)
    for i, a in enumerate(keys):
        for bk in keys[i + 1:]:
            v = interference(comps[a], comps[bk])
            if v > tol:
                problems.append(f"{name}: {a} collides with {bk} ({v:.1f} mm^3)")
    return problems


# ------------------------------------------------------------------------------------------------ export
COLORS = {"body": (0.93, 0.94, 0.95), "lid": (0.30, 0.78, 0.65), "deck": (0.55, 0.60, 0.66), "base": (0.16, 0.18, 0.21),
          "bno085": (0.15, 0.35, 0.75), "xiao": (0.10, 0.45, 0.20), "lipo": (0.75, 0.70, 0.35),
          "drv2605": (0.55, 0.15, 0.55), "motor": (0.7, 0.7, 0.72), "switch": (0.2, 0.2, 0.2)}


def export_part(shape, name):
    cq.exporters.export(shape, str(OUT / "step" / f"{name}.step"))
    cq.exporters.export(shape, str(OUT / "stl" / f"{name}.stl"), tolerance=0.03, angularTolerance=0.15)


def main():
    for d in ("step", "stl", "glb"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    arm, fore = arm_spec(), forearm_spec()
    report = {"components_mm": COMPONENTS, "parts": {}, "assemblies": {}, "fit_problems": []}

    arm_body, info = pod_body(arm)
    arm_body = lid_snaps(arm, arm_body)
    deck = pod_deck(arm, info)
    fore_body, _ = pod_body(fore)
    fore_body = lid_snaps(fore, fore_body)
    parts = {
        "pod_arm_body": arm_body, "pod_arm_deck": deck, "pod_arm_lid": pod_lid(arm, "PB-ARM"),
        "pod_chest_lid": pod_lid(arm, "PB-CHEST"), "pod_waist_lid": pod_lid(arm, "PB-WAIST"),
        "pod_forearm_body": fore_body, "pod_forearm_lid": pod_lid(fore, "PB-FORE"),
    }
    bases = {}
    for key, spec, radius, label, gap, strap in (("base_upperarm", arm, 46.0, "UPPER ARM", 4.5, STRAP_W),
                                                 ("base_forearm", fore, 30.0, "FOREARM", 3.5, STRAP_W),
                                                 ("base_chest", arm, 160.0, "CHEST", 4.5, STRAP_W),
                                                 ("base_waist", arm, 140.0, "WAIST", 4.5, 40.0)):   # 40 mm belt
        shape, seat = base(spec, key, radius, label, gap, strap)
        parts[key] = shape
        bases[key] = (spec, seat)

    for name, shape in parts.items():
        export_part(shape, name)
        bb = shape.val().BoundingBox()
        report["parts"][name] = {"size_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
                                 "volume_cm3": round(shape.val().Volume() / 1000, 2),
                                 "pla_g": round(shape.val().Volume() / 1000 * 1.24 * 0.6, 1)}   # ~60 % with 25 % infill
        print(f"{name:18} {report['parts'][name]['size_mm']} mm  {report['parts'][name]['volume_cm3']} cm3")

    # fit checks: electronics inside the pods, pods seated in bases (tongue vs channel must not collide)
    arm_c, fore_c = dummies(arm, info), dummies(fore, {})
    report["vendor_models"] = []
    for comps in (arm_c, fore_c):
        for k in list(comps):
            comps[k], note = vendor_part(k, comps[k])
            if note:
                report["vendor_models"].append(note)
                print(note)
    if not report["vendor_models"]:
        print(f"no vendor STEP files in {VENDOR}: fit check uses stand-in blocks")
    report["fit_problems"] += fit_check("arm pod", {"body": arm_body, "deck": deck, "lid": parts["pod_arm_lid"]}, arm_c)
    report["fit_problems"] += fit_check("forearm pod", {"body": fore_body, "lid": parts["pod_forearm_lid"]}, fore_c)
    for bname, (spec, seat) in bases.items():
        body = arm_body if spec.name == "arm" else fore_body
        seated = body.translate((seat["pod_cx"], 0, 0))
        v = interference(seated, parts[bname])
        if v > 0.5:
            report["fit_problems"].append(f"{bname}: seated pod collides with base ({v:.1f} mm^3)")
        report["assemblies"][bname] = seat

    # assemblies (STEP with colours + GLB for Blender / three.js)
    def unit(name, spec, body, lid, base_name, comps, deck_=None):
        seat = bases[base_name][1]
        a = cq.Assembly(name=name)
        a.add(parts[base_name], name="base", color=cq.Color(*COLORS["base"]))
        loc = cq.Location(cq.Vector(seat["pod_cx"], 0, 0))
        a.add(body, name="body", loc=loc, color=cq.Color(*COLORS["body"]))
        if deck_ is not None:
            a.add(deck_, name="deck", loc=loc, color=cq.Color(*COLORS["deck"]))
        a.add(lid, name="lid", loc=loc, color=cq.Color(*COLORS["lid"]))
        for cn, c in comps.items():
            a.add(c, name=cn, loc=loc, color=cq.Color(*COLORS[cn]))
        a.save(str(OUT / "step" / f"{name}.step"))
        a.save(str(OUT / "glb" / f"{name}.glb"))
        return a

    unit("unit_upperarm", arm, arm_body, parts["pod_arm_lid"], "base_upperarm", arm_c, deck)
    unit("unit_forearm", fore, fore_body, parts["pod_forearm_lid"], "base_forearm", fore_c)
    trunk_c = {k: v for k, v in arm_c.items() if k not in ("drv2605", "motor")}   # Unit B: no haptics
    unit("unit_chest", arm, arm_body, parts["pod_chest_lid"], "base_chest", trunk_c, deck)
    unit("unit_waist", arm, arm_body, parts["pod_waist_lid"], "base_waist", trunk_c, deck)

    report["pods"] = {s.name: {"outer_mm": [s.outer_l, s.outer_w, round(s.body_h + LID, 2)],
                               "with_rail_mm": round(s.body_h + LID + RAIL_H, 2), "layers": s.layers}
                      for s in (arm, fore)}
    (OUT / "build_report.json").write_text(json.dumps(report, indent=1))
    print("pods:", json.dumps(report["pods"]))
    if report["fit_problems"]:
        print("FIT PROBLEMS:\n  " + "\n  ".join(report["fit_problems"]))
        sys.exit(1)
    print("fit check: all components clear, pods seat in all bases")


if __name__ == "__main__":
    main()
