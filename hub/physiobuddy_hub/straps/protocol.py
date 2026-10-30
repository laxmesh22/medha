"""Decoder for the Auri strap BLE protocol v3 (contract: firmware/protocol/PROTOCOL.md; firmware side: firmware/auri_strap/src/auri_ble.h).

Pure Python, no BLE dependency, so the hub and tests can import it. Quaternions are (w, x, y, z).
A v2 status record (protocol byte 2, no type 0x07) still decodes. Nothing here requires v3.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

PROTOCOL_VERSION = 3

SERVICE_UUID = "3c3ff578-acd0-46f5-a868-3ef18783e0b1"
IMU_DATA_UUID = "55b3d211-8c74-4650-9156-6b55c5d4384a"
RAW_DATA_UUID = "eaa61235-25bd-4c94-acef-04fde856d914"
COMMAND_UUID = "98d96b03-6a94-49f4-8044-9659ea5c31bb"
STATUS_UUID = "25fc04e0-6984-40dd-a21c-f6d007e20fcd"

DEVICE_NAMES = {1: "AURI-ARM", 2: "AURI-TRUNK"}
SENSOR_NAMES = {0: "upper_arm", 1: "forearm", 2: "trunk"}  # the hub's IMU_SENSORS names

CMD_TARE, CMD_HAPTIC, CMD_RATE, CMD_STREAM, CMD_IMU_RESET, CMD_TIME_PING, CMD_POWER = (
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07)
PWR_RUN, PWR_SLOW, PWR_LIGHT = 0, 1, 2


@dataclass(frozen=True)
class ImuSample:
    unit: int
    sensor: int
    valid: bool
    calib_ok: bool
    accuracy: int
    reset: bool
    seq: int
    t_ms: int
    quat: tuple[float, float, float, float]  # w, x, y, z


@dataclass(frozen=True)
class RawSample:
    unit: int
    sensor: int
    seq: int
    t_ms: int
    gyro: Optional[tuple[float, float, float]]     # rad/s, None if not valid
    gravity: Optional[tuple[float, float, float]]  # m/s^2, None if not valid


@dataclass(frozen=True)
class Status:
    protocol: int
    firmware: str
    unit: int
    present: tuple[int, ...]
    ok: tuple[int, ...]
    battery_mv: Optional[int]  # None = no divider fitted (unavailable), never 0
    i2c_errors: int
    streaming: bool
    rate_hz: int
    haptics: bool
    notify_drops: int  # notifications the device could not queue since boot (saturates at 255)


@dataclass(frozen=True)
class Pong:
    host_us: int
    t_ms: int


@dataclass(frozen=True)
class Power:
    """STATUS type 0x07. Absent on v2 firmware; the hub treats that as unknown, not as a fault."""

    flags: int
    low: bool       # bit0, firmware warn
    critical: bool  # bit1, firmware reports-off
    state: int      # 0 run, 1 slow advertising, 2 light sleep
    tx_power_dbm: int
    idle_timeout_s: int


def battery_pct(mv: Optional[int]) -> Optional[int]:
    """3300 mV = 0, 4200 mV = 100, clamped, integer division as in the firmware. None if mv is missing."""
    if not mv:
        return None
    if mv >= 4200:
        return 100
    if mv <= 3300:
        return 0
    return (mv - 3300) * 100 // 900


def battery_low(mv: Optional[int]) -> Optional[bool]:
    """True at 15% or below. None when the millivolt reading is unavailable (None or 0)."""
    pct = battery_pct(mv)
    if pct is None:
        return None
    return pct <= 15


def _bits(mask: int) -> tuple[int, ...]:
    return tuple(i for i in range(8) if mask >> i & 1)


def decode_imu(data: bytes) -> ImuSample:
    if len(data) != 17:
        raise ValueError(f"IMU_DATA must be 17 bytes, got {len(data)}")
    ident, flags, seq, t_ms, qw, qx, qy, qz, _ = struct.unpack("<BBHI4hB", data)
    return ImuSample(ident >> 4, ident & 0x0F, bool(flags & 1), bool(flags & 2), flags >> 2 & 3, bool(flags & 0x10),
                     seq, t_ms, (qw / 16384, qx / 16384, qy / 16384, qz / 16384))


def decode_imu_data(data: bytes) -> tuple[ImuSample, Optional[RawSample]]:
    """An IMU_DATA notification: 17 bytes (orientation; the RAW_DATA record comes separately) or, in v2 when the
    MTU allows, 37 bytes (orientation + the matching gyro/gravity record in one notification)."""
    if len(data) == 37:
        return decode_imu(data[:17]), decode_raw(data[17:])
    return decode_imu(data), None


def decode_raw(data: bytes) -> RawSample:
    if len(data) != 20:
        raise ValueError(f"RAW_DATA must be 20 bytes, got {len(data)}")
    ident, flags, seq, t_ms, *v = struct.unpack("<BBHI6h", data)
    gyro = tuple(x / 1024 for x in v[:3]) if flags & 1 else None
    grav = tuple(x / 256 for x in v[3:]) if flags & 2 else None
    return RawSample(ident >> 4, ident & 0x0F, seq, t_ms, gyro, grav)


def decode_status(data: bytes) -> Status | Pong | Power:
    if data[:1] == b"\x06":
        if len(data) != 13:
            raise ValueError(f"time pong must be 13 bytes, got {len(data)}")
        host_us, t_ms = struct.unpack("<QI", data[1:])
        return Pong(host_us, t_ms)
    if data[:1] == b"\x07":
        if len(data) != 6:
            raise ValueError(f"power record must be 6 bytes, got {len(data)}")
        _kind, flags, state, tx, idle_s = struct.unpack("<BBBbH", data)
        return Power(flags, bool(flags & 1), bool(flags & 2), state, tx, idle_s)
    if len(data) != 16 or data[0] != 0x01:
        raise ValueError("unknown STATUS record")
    _, proto, ma, mi, pa, unit, present, ok, mv, i2c, stream, rate, hap, drops = struct.unpack("<8BHH4B", data)
    return Status(proto, f"{ma}.{mi}.{pa}", unit, _bits(present), _bits(ok), mv or None, i2c, bool(stream), rate,
                  bool(hap), drops)


def command(opcode: int, *args: int) -> bytes:
    """Encode a COMMAND write: command(CMD_RATE, 100), command(CMD_TIME_PING, host_us)."""
    if opcode == CMD_TIME_PING:
        return struct.pack("<BQ", opcode, args[0])
    return bytes([opcode, *args])
