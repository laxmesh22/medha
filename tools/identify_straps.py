"""Shake one strap at a time so each BLE address gets a slot.

Connects every advertising AURI strap, streams at 50 Hz, and writes
hub/straps_slots.local.json. A slot is recorded only when one address's gyro
peak is clearly larger than the others. Nothing is guessed.

    hub/.venv/Scripts/python.exe tools/identify_straps.py
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hub"))

from bleak import BleakClient, BleakScanner  # noqa: E402
from physiobuddy_hub.straps.protocol import (  # noqa: E402
    CMD_RATE, CMD_STREAM, COMMAND_UUID, IMU_DATA_UUID, RAW_DATA_UUID, SERVICE_UUID, command, decode_imu_data,
    decode_raw,
)

OUT = ROOT / "hub" / "straps_slots.local.json"
PROMPTS = (
    ("upper_arm", "Shake the UPPER ARM strap now"),
    ("forearm", "Shake the FOREARM strap now"),
    ("trunk", "Shake the WAIST strap now"),
)
WINDOW_S = 20.0
PEAK_MIN = 1.0


def _mag(gyro) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in gyro))


class _Gyro:
    def __init__(self) -> None:
        self.peak = 0.0
        self.last = 0.0
        self.n = 0

    def add(self, gyro) -> None:
        if gyro is None:
            return
        mag = _mag(gyro)
        self.last = mag
        self.peak = max(self.peak, mag)
        self.n += 1

    def reset(self) -> None:
        self.peak = 0.0
        self.last = 0.0
        self.n = 0


async def _discover() -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    want = SERVICE_UUID.lower()

    def on_adv(device, adv):
        name = adv.local_name or device.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        if name.startswith("AURI-") or want in uuids:
            found[device.address.upper()] = name or device.name or ""

    scanner = BleakScanner(detection_callback=on_adv)
    print("Scanning 8 s for AURI straps…", flush=True)
    await scanner.start()
    await asyncio.sleep(8)
    await scanner.stop()
    return sorted(found.items())


def _winner(tracks: dict[str, _Gyro]) -> str | None:
    ranked = sorted(tracks.items(), key=lambda item: item[1].peak, reverse=True)
    if not ranked or ranked[0][1].peak < PEAK_MIN:
        return None
    if len(ranked) > 1 and ranked[0][1].peak < 2.0 * max(ranked[1][1].peak, 1e-6):
        return None
    return ranked[0][0]


async def _session(address: str, tracks: dict[str, _Gyro], stop: asyncio.Event) -> None:
    def on_bytes(_sender, data: bytearray) -> None:
        raw = bytes(data)
        try:
            if len(raw) in (17, 37):
                _imu, extra = decode_imu_data(raw)
                if extra is not None and extra.gyro is not None:
                    tracks[address].add(extra.gyro)
                return
            sample = decode_raw(raw)
        except ValueError:
            return
        tracks[address].add(sample.gyro)

    async with BleakClient(address, timeout=15.0) as client:
        await client.start_notify(IMU_DATA_UUID, on_bytes)
        await client.start_notify(RAW_DATA_UUID, on_bytes)
        await client.write_gatt_char(COMMAND_UUID, command(CMD_RATE, 50), response=True)
        await client.write_gatt_char(COMMAND_UUID, command(CMD_STREAM, 1), response=True)
        await stop.wait()


async def main() -> int:
    devices = await _discover()
    if not devices:
        print("No AURI strap is advertising. Check the battery and the slide switch, then run this again.")
        return 1
    print("Found:", ", ".join(f"{name or 'AURI'} {addr}" for addr, name in devices), flush=True)
    tracks = {addr: _Gyro() for addr, _name in devices}
    stop = asyncio.Event()
    tasks = [asyncio.create_task(_session(addr, tracks, stop)) for addr, _name in devices]
    await asyncio.sleep(2.0)
    mapping: dict[str, str] = {}
    try:
        for slot, prompt in PROMPTS:
            for track in tracks.values():
                track.reset()
            print(f"\n{prompt}. You have {WINDOW_S:.0f} s.", flush=True)
            end = time.perf_counter() + WINDOW_S
            next_print = 0.0
            while time.perf_counter() < end:
                now = time.perf_counter()
                if now >= next_print:
                    bits = "  ".join(f"{addr[-5:]} {_Gyro_line(tracks[addr])}" for addr, _n in devices)
                    print(bits, flush=True)
                    next_print = now + 1.0
                await asyncio.sleep(0.05)
            chosen = _winner(tracks)
            if chosen is None or chosen in mapping:
                print(f"{slot}: not recorded. One strap has to move much more than the others.", flush=True)
                continue
            mapping[chosen] = slot
            print(f"{slot}: {chosen}  peak {tracks[chosen].peak:.2f} rad/s", flush=True)
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    if not mapping:
        print("No slot was recorded. The file was not changed.")
        return 1
    existing = {}
    if OUT.is_file():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    for addr, slot in mapping.items():
        existing[addr] = slot
    OUT.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    for addr, slot in sorted(existing.items()):
        print(f"  {addr}  {slot}")
    return 0


def _Gyro_line(track: _Gyro) -> str:
    return f"|g| {track.last:5.2f}  peak {track.peak:5.2f}  n {track.n}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
