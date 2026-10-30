"""Clinical shoulder angles from the three straps (upper arm, forearm, trunk/waist BNO085s).

Same output as ``SkeletonKinematics`` (a ``CameraAngles``: same thorax convention, same formulas, same thresholds and
flags), so the coach's rule checks and PB-MotionNet treat camera and straps alike. Degrees come from geometry only.

Inputs per frame: each sensor's orientation quaternion (w, x, y, z), sensor -> its own gravity-aligned world frame
(BNO085 game rotation vector: Z up, yaw reference arbitrary and different for every sensor).

Mounting. Pod axes are fixed by the CAD (hardware/README.md): X along the lid arrow, Z out of the lid (away from the
skin). The firmware must remap the BNO085 so its axes match the pod. Arrow directions: upper arm -> shoulder, forearm
-> wrist, trunk -> up. ``NOMINAL_MOUNTS`` turns that into segment axes (thorax convention: X anterior, Y up, Z right).

Calibration (``StrapCalibration``). N-pose: stand upright, arms relaxed at the sides, palms toward the thighs (thumbs
forward). Every segment frame is then taken to be aligned with one body frame B, which removes the unknown yaw
reference of each sensor:  segment orientation in B  Q(t) = A^T R(c)^T R(t) A  (A = segment -> sensor mount, R(c) the
sensor orientation at calibration). Gravity at calibration corrects the mount tilt. A slow straight-arm forward raise
(``refine_with_forward_raise``) fixes the strap's rotation about the limb, which gravity cannot see; without it the
error equals how far the strap is turned on the arm.

Anything that cannot be computed is unavailable, never 0. Shrug needs the camera (the straps do not see the scapula).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..datatypes import GOOD, LOW, CameraAngles, Measurement
from .skeleton_kin import (
    MIN_ELEVATION_FOR_PLANE_DEG, ROT_ELBOW_DRIFT_WARN_DEG, ROT_ELBOW_FLEX_RANGE, ROT_MAX_ELEVATION_DEG,
    TRUNK_LEAN_WARN_DEG, _angle_deg, _name_movement,
)

SENSORS = ("upper_arm", "forearm", "trunk")
WORLD_UP = np.array([0.0, 0.0, 1.0])          # gravity-aligned sensor world (BNO085 game rotation vector)
DOWN = np.array([0.0, -1.0, 0.0])             # segment / thorax "down"
MIN_LEAN_TILT = 0.2                            # sin of ~12 deg: below this the lean's direction is noise
MIN_RAISE_SPAN_DEG = 40.0                      # the arm must travel this far to fix the forearm's axis
MAX_FOREARM_FIT_DEG = 12.0                     # worse than this the elbow was not straight during the raise

# Where each pod axis points on the body in the N-pose, in segment axes: (pod X, pod Y, pod Z). Pod Y = Z x X.
_M = {
    ("upper_arm", "right"): ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),     # X up the humerus, Z lateral (+Z)
    ("upper_arm", "left"): ((0, 1, 0), (1, 0, 0), (0, 0, -1)),      # Z lateral = -Z of the thorax
    ("forearm", "right"): ((0, -1, 0), (1, 0, 0), (0, 0, 1)),       # X toward the wrist, Z dorsal (lateral in N-pose)
    ("forearm", "left"): ((0, -1, 0), (-1, 0, 0), (0, 0, -1)),
    ("trunk", "right"): ((0, 1, 0), (0, 0, 1), (1, 0, 0)),          # X up, Z anterior (pod on the front of the belt)
    ("trunk", "left"): ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
}


def nominal_mount(sensor: str, side: str) -> np.ndarray:
    """Segment -> sensor rotation A for a pod worn as the guide shows."""
    M = np.array(_M[(sensor, side)], float).T        # sensor -> segment, columns = pod axes in segment coords
    return M.T


def quat_to_matrix(q) -> np.ndarray:
    w, x, y, z = (float(v) for v in q)
    n = np.sqrt(w * w + x * x + y * y + z * z)
    if not np.isfinite(n) or n < 1e-9:
        raise ValueError("invalid quaternion")
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def matrix_to_quat(R: np.ndarray) -> np.ndarray:
    R = np.asarray(R, float)
    tr = np.trace(R)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def axis_angle(axis, angle_rad: float) -> np.ndarray:
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * K @ K


def align(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Smallest rotation taking unit vector a onto unit vector b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    s, c = float(np.linalg.norm(v)), float(np.dot(a, b))
    if s < 1e-9:
        if c > 0:
            return np.eye(3)
        perp = np.cross(a, [1.0, 0, 0] if abs(a[0]) < 0.9 else [0, 1.0, 0])
        return axis_angle(perp, np.pi)
    return axis_angle(v, np.arctan2(s, c))


def mean_rotation(Rs: list) -> np.ndarray:
    """Chordal L2 mean of rotation matrices (fine for the small spread of a still pose)."""
    U, _, Vt = np.linalg.svd(np.sum(Rs, axis=0))
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1
        R = U @ Vt
    return R


@dataclass
class StrapCalibration:
    side: str
    ref: dict                                  # sensor -> R(c), sensor -> its world, at the N-pose
    mount: dict                                # sensor -> A, segment -> sensor
    # sensor -> True once its forward is fixed (arms: the raise; trunk: the lean)
    forward_raise: dict = field(default_factory=dict)

    def gravity_offset_deg(self, sensor: str) -> Optional[float]:
        """How far gravity turned the nominal mount, in degrees. None when that strap was not in the N-pose."""
        if sensor not in self.mount:
            return None
        corrected = self.mount[sensor] @ nominal_mount(sensor, self.side).T
        cosine = float(np.clip((np.trace(corrected) - 1.0) / 2.0, -1.0, 1.0))
        return float(np.degrees(np.arccos(cosine)))

    @classmethod
    def from_npose(cls, side: str, quats: dict) -> "StrapCalibration":
        """``quats``: sensor -> list of quaternions recorded while standing still in the N-pose (~2 s)."""
        ref, mount = {}, {}
        for s, qs in quats.items():
            if s not in SENSORS or not len(qs):
                continue
            Rc = mean_rotation([quat_to_matrix(q) for q in qs])
            A = nominal_mount(s, side)
            up_sensor = Rc.T @ WORLD_UP                      # measured "up" in pod axes
            C = align(A @ np.array([0.0, 1.0, 0.0]), up_sensor)   # every segment is vertical in the N-pose
            ref[s], mount[s] = Rc, C @ A
        return cls(side, ref, mount)

    def to_dict(self) -> dict:
        """The worn orientation, so a later session can keep this mount."""
        def mats(group):
            return {name: np.asarray(value, float).round(8).tolist() for name, value in group.items()}
        return {
            "side": self.side,
            "ref": mats(self.ref),
            "mount": mats(self.mount),
            "forward_raise": {name: bool(done) for name, done in self.forward_raise.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StrapCalibration":
        ref = {name: np.asarray(value, float) for name, value in (data.get("ref") or {}).items()}
        mount = {name: np.asarray(value, float) for name, value in (data.get("mount") or {}).items()}
        return cls(str(data.get("side") or "right"), ref, mount, dict(data.get("forward_raise") or {}))

    def refine_with_forward_raise(self, gyro: dict) -> None:
        """``gyro``: sensor -> (T, 3) rates in pod axes during a slow straight-arm forward raise. Flexion turns the
        humerus and forearm about the segment +Z axis; turning the mount about the limb axis (segment Y) until the
        measured rotation axis lies on segment Z removes the strap's rotation about the arm."""
        for s in ("upper_arm", "forearm"):
            g = np.asarray(gyro.get(s, []), float)
            if s not in self.mount or self.forward_raise.get(s) or len(g) < 10:
                continue
            fast = g[np.linalg.norm(g, axis=1) > 10.0]       # deg/s: only the moving part of the raise
            if len(fast) < 10:
                continue
            w, v = np.linalg.eigh(fast.T @ fast)
            axis = v[:, -1]
            A = self.mount[s]
            z_s, y_s = A @ np.array([0, 0, 1.0]), A @ np.array([0, 1.0, 0])
            if np.dot(axis, z_s) < 0:
                axis = -axis
            a_p = axis - np.dot(axis, y_s) * y_s                # project both onto the plane normal to the limb
            z_p = z_s - np.dot(z_s, y_s) * y_s
            if np.linalg.norm(a_p) < 0.5 or np.linalg.norm(z_p) < 0.5:
                continue
            ang = np.arctan2(np.dot(y_s, np.cross(z_p, a_p)), np.dot(z_p, a_p))
            self.mount[s] = axis_angle(y_s, ang) @ A
            self.forward_raise[s] = True

    def refine_from_raise_direction(self, samples: dict) -> list:
        """``samples``: sensor -> list of (quaternion, gyro or None).

        The N-pose already set which chip axis is up. A box that lies flat, or sits
        crooked on the strap, still leaves forward and sideways swapped. The direction
        the arm actually moved in this raise is taken as forward.
        """
        trunks = []
        for quat, _gyro in samples.get("trunk") or []:
            Q = self.segment("trunk", quat)
            if Q is not None:
                trunks.append(Q)
        Qt = mean_rotation(trunks) if trunks else None
        done = []
        for name in ("upper_arm", "forearm"):
            rows = samples.get(name) or []
            if name not in self.mount or self.forward_raise.get(name) or len(rows) < 8:
                continue
            headings = []
            for quat, _gyro in rows:
                Qa = self.segment(name, quat)
                if Qa is None:
                    continue
                limb = Qa @ DOWN
                if Qt is not None:
                    limb = Qt.T @ limb
                flat = np.array([float(limb[0]), 0.0, float(limb[2])])
                n = float(np.linalg.norm(flat))
                if n > 0.35:
                    headings.append(flat / n)
            if len(headings) < 8:
                continue
            mean = np.mean(headings, axis=0)
            n = float(np.linalg.norm(mean))
            if n < 0.5:
                continue
            mean /= n
            # Heading 0 is anterior (+X). Rotate the mount about the limb so this raise lands there.
            az = float(np.arctan2(mean[2], mean[0]))
            self.mount[name] = self.mount[name] @ axis_angle(np.array([0.0, 1.0, 0.0]), -az)
            self.forward_raise[name] = True
            done.append(name)
        return done

    def align_forearm_to_upper_arm(self, samples: dict) -> Optional[float]:
        """``samples``: sensor -> list of (quaternion, gyro or None) during a straight-arm raise.

        The N-pose takes the forearm's long axis from gravity, so a forearm that was not hanging straight (elbow a
        little bent, hand on the thigh) leaves the axis tilted, and wrist twist then swings the error around. With the
        elbow straight the forearm points where the upper arm points all through the raise, which fixes the long
        axis (2 dof) and its forward (1 dof) together. Returns the mean fit error in degrees, or None when rejected.

        The two streams are paired by their position in the capture: both run at the same rate and the raise is slow.
        """
        if "forearm" not in self.ref or "upper_arm" not in self.ref:
            return None
        fore = [quat_to_matrix(q) for q, _g in samples.get("forearm") or []]
        arms = [self.segment("upper_arm", q) for q, _g in samples.get("upper_arm") or []]
        arms = [Q for Q in arms if Q is not None]
        if len(fore) < 20 or len(arms) < 20:
            return None
        n = min(len(fore), len(arms))
        R = [fore[round(i * (len(fore) - 1) / (n - 1))] for i in range(n)]
        u = np.array([arms[round(i * (len(arms) - 1) / (n - 1))] @ DOWN for i in range(n)])
        if max(_angle_deg(u[0], v) for v in u) < MIN_RAISE_SPAN_DEG:
            return None                               # the arm did not travel far enough to pin the forearm down
        W0 = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])      # body frame -> sensor world, body up = world up
        best = None
        for step in (1.0, 0.05):
            centre = 0.0 if best is None else best[0]
            for psi in np.radians(np.arange(-180.0, 180.0, step) if step == 1.0 else centre + np.arange(-1.0, 1.0, step)):
                W = axis_angle(WORLD_UP, psi) @ W0
                w = u @ W.T                            # target directions in the forearm sensor's world
                a = np.sum([Rt.T @ wt for Rt, wt in zip(R, w)], axis=0)
                a /= np.linalg.norm(a)
                cost = float(np.sum([np.linalg.norm(Rt @ a - wt) ** 2 for Rt, wt in zip(R, w)]))
                if best is None or cost < best[3]:
                    best = (float(np.degrees(psi)), W, a, cost)
        _, W, a, _ = best
        err = float(np.mean([_angle_deg(Rt @ a, wt) for Rt, wt in zip(R, u @ W.T)]))
        if err > MAX_FOREARM_FIT_DEG:
            return None                                # the elbow bent during the raise; keep the N-pose axis
        # Keep segment() unchanged: a virtual reference orientation in which this long axis hangs straight down,
        # and the mount that makes reference @ mount = W.
        Rc = align(a, -WORLD_UP)
        self.ref["forearm"] = Rc
        self.mount["forearm"] = Rc.T @ W
        self.forward_raise["forearm"] = True
        return err

    def refine_trunk_from_lean(self, samples: dict) -> bool:
        """``samples``: sensor -> list of (quaternion, gyro or None) during a slow forward lean from the hips.

        The N-pose sets only which way is up on the waist box. Worn on the back, the side or upside down, its
        forward stays unknown and a forward lean reads as sideways or backward. The way the trunk tipped is
        taken as forward.
        """
        rows = samples.get("trunk") or []
        if "trunk" not in self.mount or self.forward_raise.get("trunk") or len(rows) < 8:
            return False
        headings = []
        for quat, _gyro in rows:
            Qt = self.segment("trunk", quat)
            if Qt is None:
                continue
            top = Qt @ np.array([0.0, 1.0, 0.0])
            flat = np.array([float(top[0]), 0.0, float(top[2])])
            n = float(np.linalg.norm(flat))
            if n > MIN_LEAN_TILT:
                headings.append(flat / n)
        if len(headings) < 8:
            return False
        mean = np.mean(headings, axis=0)
        n = float(np.linalg.norm(mean))
        if n < 0.5:
            return False
        mean /= n
        az = float(np.arctan2(mean[2], mean[0]))
        self.mount["trunk"] = self.mount["trunk"] @ axis_angle(np.array([0.0, 1.0, 0.0]), -az)
        self.forward_raise["trunk"] = True
        return True

    def segment(self, sensor: str, q) -> Optional[np.ndarray]:
        """Segment orientation in the body frame B (rotation, segment -> B)."""
        if sensor not in self.ref or q is None:
            return None
        try:
            R = quat_to_matrix(q)
        except ValueError:
            return None
        A = self.mount[sensor]
        return A.T @ self.ref[sensor].T @ R @ A

    def up_in_segment(self, sensor: str, q) -> Optional[np.ndarray]:
        """World up in segment axes, straight from gravity (no calibration assumption)."""
        if sensor not in self.mount or q is None:
            return None
        try:
            R = quat_to_matrix(q)
        except ValueError:
            return None
        return self.mount[sensor].T @ (R.T @ WORLD_UP)

    def gyro_in_segment(self, sensor: str, gyro) -> Optional[np.ndarray]:
        if sensor not in self.mount or gyro is None:
            return None
        g = np.asarray(gyro, float)
        return None if not np.all(np.isfinite(g)) else self.mount[sensor].T @ g


class StrapKinematics:
    """Per-frame angles from the three straps. Output matches ``SkeletonKinematics.compute``."""

    def __init__(self, calibration: StrapCalibration):
        self.cal = calibration
        self.side = calibration.side
        self.z_sign = 1.0 if self.side == "right" else -1.0

    def compute(self, quats: dict) -> CameraAngles:
        na = Measurement.unavailable
        flags: list = []
        Qt = self.cal.segment("trunk", quats.get("trunk"))
        Qa = self.cal.segment("upper_arm", quats.get("upper_arm"))
        Qf = self.cal.segment("forearm", quats.get("forearm"))
        q_arm = GOOD if self.cal.forward_raise.get("upper_arm") else LOW

        # trunk lean from gravity in the trunk segment (camera convention)
        lean_sag = lean_lat = na("waist strap missing")
        up_t = self.cal.up_in_segment("trunk", quats.get("trunk"))
        if up_t is not None:
            lean_sag = Measurement(float(np.degrees(np.arctan2(-up_t[0], up_t[1]))), GOOD)
            lean_lat = Measurement(float(np.degrees(np.arctan2(-up_t[2] * self.z_sign, up_t[1]))), GOOD)
            if abs(lean_sag.value) > TRUNK_LEAN_WARN_DEG:
                flags.append("TRUNK_LEAN_SAGITTAL")
            if abs(lean_lat.value) > TRUNK_LEAN_WARN_DEG:
                flags.append("TRUNK_LEAN_LATERAL")

        # apparent elevation: humerus vs world vertical (arm strap + gravity only)
        app = na("upper-arm strap missing")
        up_a = self.cal.up_in_segment("upper_arm", quats.get("upper_arm"))
        if up_a is not None:
            app = Measurement(_angle_deg(DOWN, -up_a / np.linalg.norm(up_a)), GOOD)

        elev = plane = na("upper-arm or waist strap missing")
        movement = None
        u = None
        if Qa is not None and Qt is not None:
            u = Qt.T @ Qa @ DOWN                      # humerus direction in the thorax
            u[2] *= self.z_sign
            elev = Measurement(_angle_deg(u, DOWN), q_arm)
            if elev.value < MIN_ELEVATION_FOR_PLANE_DEG:
                plane = na("arm near side")
                movement = "rest"
            else:
                plane = Measurement(float(np.degrees(np.arctan2(u[2], u[0]))), q_arm)
                movement = _name_movement(plane.value)

        if Qf is None:
            elbow = rot = na("forearm strap missing")
        elif u is None:
            elbow = rot = na("upper-arm or waist strap missing")
        else:
            f = Qt.T @ Qf @ DOWN
            f[2] *= self.z_sign
            elbow = Measurement(_angle_deg(u, f), q_arm)
            rot = self._rotation(elev, elbow, f, flags)

        if elev.value is not None and app.value is not None and abs(app.value - elev.value) > TRUNK_LEAN_WARN_DEG:
            flags.append("APPARENT_TRUE_GAP")
        shrug = na("shrug needs the camera")
        return CameraAngles(self.side, movement, elev, app, plane, elbow, rot, lean_sag, lean_lat, shrug, flags)

    @staticmethod
    def _rotation(elev: Measurement, elbow: Measurement, f: np.ndarray, flags: list) -> Measurement:
        if elev.value is None or elev.value > ROT_MAX_ELEVATION_DEG:
            return Measurement.unavailable("rotation needs elbow at side")
        if not (ROT_ELBOW_FLEX_RANGE[0] <= elbow.value <= ROT_ELBOW_FLEX_RANGE[1]):
            return Measurement.unavailable("rotation needs elbow ~90 deg")
        if float(np.hypot(f[0], f[2])) < 0.5:
            return Measurement.unavailable("forearm not horizontal")
        if elev.value > ROT_ELBOW_DRIFT_WARN_DEG:
            flags.append("ELBOW_DRIFT")
        return Measurement(float(np.degrees(np.arctan2(f[2], f[0]))), elev.quality)
