"""Decoder for the Auri strap BLE protocol v1 (contract: firmware/protocol/PROTOCOL.md; firmware side: firmware/auri_strap/src/auri_ble.h).

Pure Python, no BLE dependency, so the hub and tests can import it. Quaternions are (w, x, y, z).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

PROTOCOL_VERSION = 1

SERVICE_UUID = "3c3ff578-acd0-46f5-a868-3ef18783e0b1"
IMU_DATA_UUID = "55b3d211-8c74-4650-9156-6b55c5d4384a"
RAW_DATA_UUID = "eaa61235-25bd-4c94-acef-04fde856d914"
COMMAND_UUID = "98d96b03-6a94-49f4-8044-9659ea5c31bb"
STATUS_UUID = "25fc04e0-6984-40dd-a21c-f6d007e20fcd"

DEVICE_NAMES = {1: "AURI-ARM", 2: "AURI-TRUNK"}
SENSOR_NAMES = {0: "upper_arm", 1: "forearm", 2: "trunk"}  # the hub's IMU_SENSORS names

CMD_TARE, CMD_HAPTIC, CMD_RATE, CMD_STREAM, CMD_IMU_RESET, CMD_TIME_PING = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06


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


@dataclass(frozen=True)
class Pong:
    host_us: int
    t_ms: int


def _bits(mask: int) -> tuple[int, ...]:
    return tuple(i for i in range(8) if mask >> i & 1)


def decode_imu(data: bytes) -> ImuSample:
    if len(data) != 17:
        raise ValueError(f"IMU_DATA must be 17 bytes, got {len(data)}")
    ident, flags, seq, t_ms, qw, qx, qy, qz, _ = struct.unpack("<BBHI4hB", data)
    return ImuSample(ident >> 4, ident & 0x0F, bool(flags & 1), bool(flags & 2), flags >> 2 & 3, bool(flags & 0x10),
                     seq, t_ms, (qw / 16384, qx / 16384, qy / 16384, qz / 16384))


def decode_raw(data: bytes) -> RawSample:
    if len(data) != 20:
        raise ValueError(f"RAW_DATA must be 20 bytes, got {len(data)}")
    ident, flags, seq, t_ms, *v = struct.unpack("<BBHI6h", data)
    gyro = tuple(x / 1024 for x in v[:3]) if flags & 1 else None
    grav = tuple(x / 256 for x in v[3:]) if flags & 2 else None
    return RawSample(ident >> 4, ident & 0x0F, seq, t_ms, gyro, grav)


def decode_status(data: bytes) -> Status | Pong:
    if data[:1] == b"\x06":
        if len(data) != 13:
            raise ValueError(f"time pong must be 13 bytes, got {len(data)}")
        host_us, t_ms = struct.unpack("<QI", data[1:])
        return Pong(host_us, t_ms)
    if len(data) != 16 or data[0] != 0x01:
        raise ValueError("unknown STATUS record")
    _, proto, ma, mi, pa, unit, present, ok, mv, i2c, stream, rate, hap, _ = struct.unpack("<8BHH4B", data)
    return Status(proto, f"{ma}.{mi}.{pa}", unit, _bits(present), _bits(ok), mv or None, i2c, bool(stream), rate,
                  bool(hap))


def command(opcode: int, *args: int) -> bytes:
    """Encode a COMMAND write: command(CMD_RATE, 100), command(CMD_TIME_PING, host_us)."""
    if opcode == CMD_TIME_PING:
        return struct.pack("<BQ", opcode, args[0])
    return bytes([opcode, *args])
