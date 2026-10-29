"""Talk to a flashed Auri strap over BLE and print link statistics.

Imports firmware/protocol/auri_ble.py. Does not copy it.
Usage: ble_probe.py [seconds] [address]
The seconds argument is the first listen window (default 50 Hz). Command tests follow it.
An optional BLE address pins the connection when more than one Auri is advertising.
"""
from __future__ import annotations

import asyncio
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "protocol"))
import auri_ble  # noqa: E402

NAMES = ("AURI-ARM", "AURI-TRUNK")


def _norm(v: tuple[float, ...]) -> float:
    return math.sqrt(sum(x * x for x in v))


class Bucket:
    def __init__(self) -> None:
        self.packets = 0
        self.valid = 0
        self.seqs: list[int] = []
        self.t0: float | None = None
        self.t1: float | None = None
        self.accuracy = [0, 0, 0, 0]
        self.quats: list[tuple[float, float, float, float]] = []
        self.flags: list[tuple[bool, bool]] = []  # (valid, reset) in arrival order
        self.times: list[float] = []
        self.gyro: list[tuple[float, float, float]] = []
        self.gravity: list[tuple[float, float, float]] = []

    def add(self, sample: auri_ble.ImuSample) -> None:
        now = time.perf_counter()
        if self.t0 is None:
            self.t0 = now
        self.t1 = now
        self.times.append(now)
        self.packets += 1
        self.valid += int(sample.valid)
        self.seqs.append(sample.seq)
        if 0 <= sample.accuracy <= 3:
            self.accuracy[sample.accuracy] += 1
        self.quats.append(sample.quat)
        self.flags.append((sample.valid, sample.reset))

    def add_raw(self, sample: auri_ble.RawSample) -> None:
        if sample.gyro is not None:
            self.gyro.append(sample.gyro)
        if sample.gravity is not None:
            self.gravity.append(sample.gravity)

    def gaps(self) -> int:
        missing = 0
        for a, b in zip(self.seqs, self.seqs[1:]):
            step = (b - a) & 0xFFFF
            if step == 0:
                continue
            if step > 1:
                missing += step - 1
        return missing

    def rate(self) -> float:
        if self.t0 is None or self.t1 is None or self.t1 <= self.t0:
            return 0.0
        return self.packets / (self.t1 - self.t0)


def report(title: str, buckets: dict[int, Bucket]) -> None:
    print(f"--- {title} ---")
    if not buckets:
        print("no IMU packets")
        return
    for sensor in sorted(buckets):
        b = buckets[sensor]
        name = auri_ble.SENSOR_NAMES.get(sensor, "link_test" if sensor == 15 else str(sensor))
        valid_pct = 100.0 * b.valid / b.packets if b.packets else 0.0
        print(
            f"sensor {sensor} ({name}): packets {b.packets} rate {b.rate():.2f} Hz "
            f"seq_gaps {b.gaps()} valid {valid_pct:.1f}%"
        )
        print(f"  accuracy histogram 0-3: {b.accuracy[0]} {b.accuracy[1]} {b.accuracy[2]} {b.accuracy[3]}")
        if b.quats:
            norms = [_norm(q) for q in b.quats]
            print(
                f"  quat norm min {min(norms):.4f} median {statistics.median(norms):.4f} max {max(norms):.4f}"
            )
            show = list(enumerate(b.quats))
            picked = show[:3] + show[-3:] if len(show) > 6 else show
            for i, q in picked:
                print(f"  quat[{i}] w {q[0]:.4f} x {q[1]:.4f} y {q[2]:.4f} z {q[3]:.4f} norm {_norm(q):.4f}")
        if b.gyro:
            cols = list(zip(*b.gyro))
            spans = " ".join(f"{min(c):.3f}..{max(c):.3f}" for c in cols)
            print(f"  gyro rad/s xyz {spans}")
        if b.gravity:
            cols = list(zip(*b.gravity))
            spans = " ".join(f"{min(c):.3f}..{max(c):.3f}" for c in cols)
            gn = [_norm(g) for g in b.gravity]
            print(f"  gravity m/s^2 xyz {spans}")
            print(
                f"  gravity norm min {min(gn):.3f} median {statistics.median(gn):.3f} max {max(gn):.3f}"
            )


async def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    only = sys.argv[2].upper() if len(sys.argv) > 2 else ""
    from bleak import BleakClient, BleakScanner

    want = auri_ble.SERVICE_UUID.lower()
    disconnects: list[str] = []

    def match(device, adv) -> bool:
        if only and device.address.upper() != only:
            return False
        name = (adv.local_name or device.name or "")
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        return name in NAMES or want in uuids

    print(f"scanning {seconds:.0f}s window requested; looking for {NAMES} or {auri_ble.SERVICE_UUID}"
          + (f" at {only}" if only else ""))
    device = await BleakScanner.find_device_by_filter(match, timeout=15.0)
    if device is None:
        print("scan: no AURI-ARM / AURI-TRUNK and no matching service UUID")
        return 1
    print(f"found name={device.name!r} address={device.address}")

    buckets: dict[int, Bucket] = {}
    raw_count = 0
    combined_raw = 0
    imu_lengths: dict[int, int] = {}
    pongs: dict[int, asyncio.Future] = {}
    statuses: list[auri_ble.Status] = []

    def on_disconnect(_client) -> None:
        disconnects.append("disconnected")
        print("event: disconnected")

    def take(data: bytearray) -> bytes:
        return bytes(data)

    def on_imu(_sender, data: bytearray) -> None:
        nonlocal combined_raw
        rawb = take(data)
        imu_lengths[len(rawb)] = imu_lengths.get(len(rawb), 0) + 1
        sample, raw = auri_ble.decode_imu_data(rawb)
        buckets.setdefault(sample.sensor, Bucket()).add(sample)
        if raw is not None:
            combined_raw += 1
            buckets[sample.sensor].add_raw(raw)

    def on_raw(_sender, data: bytearray) -> None:
        nonlocal raw_count
        sample = auri_ble.decode_raw(take(data))
        raw_count += 1
        buckets.setdefault(sample.sensor, Bucket()).add_raw(sample)

    def on_status(_sender, data: bytearray) -> None:
        obj = auri_ble.decode_status(take(data))
        if isinstance(obj, auri_ble.Pong):
            fut = pongs.get(obj.host_us)
            if fut is not None and not fut.done():
                fut.set_result((time.perf_counter(), obj))
            print(f"pong t_ms={obj.t_ms}")
        else:
            statuses.append(obj)
            print(f"STATUS notify_drops={obj.notify_drops} i2c_errors={obj.i2c_errors} rate={obj.rate_hz}")

    async with BleakClient(device, disconnected_callback=on_disconnect) as client:
        print(f"connected mtu={client.mtu_size}")
        raw_status = bytes(await client.read_gatt_char(auri_ble.STATUS_UUID))
        status = auri_ble.decode_status(raw_status)
        print(f"STATUS read: {status}")
        if isinstance(status, auri_ble.Status):
            print(f"STATUS notify_drops={status.notify_drops} i2c_errors={status.i2c_errors} rate={status.rate_hz}")
        await client.start_notify(auri_ble.IMU_DATA_UUID, on_imu)
        await client.start_notify(auri_ble.RAW_DATA_UUID, on_raw)
        await client.start_notify(auri_ble.STATUS_UUID, on_status)

        def stage_line() -> None:
            lengths = " ".join(f"{n}x{imu_lengths[n]}" for n in sorted(imu_lengths)) or "none"
            print(f"IMU_DATA lengths: {lengths}; separate RAW_DATA {raw_count}; combined raw {combined_raw}")
            if statuses:
                st = statuses[-1]
                print(f"stage STATUS notify_drops={st.notify_drops} i2c_errors={st.i2c_errors}")

        async def listen(label: str, dur: float) -> None:
            nonlocal raw_count, combined_raw
            buckets.clear()
            imu_lengths.clear()
            raw_count = 0
            combined_raw = 0
            await asyncio.sleep(dur)
            print(f"sensor 15 packets: {buckets[15].packets if 15 in buckets else 0}")
            stage_line()
            report(label, buckets)

        await listen(f"listen {seconds:.0f}s at default rate", seconds)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_RATE, 100), response=True)
        print(f"rate 100 write ok; connected={client.is_connected}")
        await listen("rate 100 Hz for 30s", 30.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_RATE, 50), response=True)
        print(f"rate 50 write ok; connected={client.is_connected}")
        await listen("rate 50 Hz for 5s", 5.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_STREAM, 0), response=True)
        print(f"stream off write ok; connected={client.is_connected}")
        await listen("stream off for 3s", 3.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_STREAM, 1), response=True)
        print(f"stream on write ok; connected={client.is_connected}")
        await listen("stream on for 2s", 2.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_HAPTIC, 1), response=True)
        await asyncio.sleep(0.4)
        print(f"haptic 1 sent; still connected={client.is_connected}")
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_TARE), response=True)
        await asyncio.sleep(0.4)
        print(f"tare sent; still connected={client.is_connected}")

        buckets.clear()
        imu_lengths.clear()
        status_n = len(statuses)
        pong_n = 0
        t_reset = time.perf_counter()
        await client.write_gatt_char(
            auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_IMU_RESET, 0x01), response=True
        )
        print(f"IMU reset sent; connected={client.is_connected}")
        await asyncio.sleep(0.25)
        host_us = time.time_ns() // 1000
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        pongs[host_us] = fut
        t_ping = time.perf_counter()
        await client.write_gatt_char(
            auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_TIME_PING, host_us), response=True
        )
        try:
            t1, pong = await asyncio.wait_for(fut, timeout=1.0)
            pong_n += 1
            print(f"pong during reset rtt_ms {(t1 - t_ping) * 1000:.2f} t_ms {pong.t_ms}")
        except asyncio.TimeoutError:
            print("pong during reset: timeout")
        await asyncio.sleep(4.0)
        print(f"STATUS notifies during reset window: {len(statuses) - status_n}; pongs {pong_n}")
        report("after IMU reset", buckets)

        def mark(valid: bool, reset: bool) -> str:
            if reset and valid:
                return "r"
            if reset:
                return "R"
            return "V" if valid else "0"

        for sensor in sorted(buckets):
            b = buckets[sensor]
            marks = "".join(mark(valid, reset) for valid, reset in b.flags)
            print(f"  sensor {sensor} flag trace ({len(marks)}): {marks}")
            first_valid = next((t for (valid, _reset), t in zip(b.flags, b.times) if valid), None)
            after_gap = None
            seen_invalid = False
            for (valid, reset), t in zip(b.flags, b.times):
                if not valid:
                    seen_invalid = True
                elif seen_invalid and (reset or valid):
                    after_gap = t
                    break
            if first_valid is not None:
                print(f"  sensor {sensor} reset_to_first_packet_ms {(b.times[0] - t_reset) * 1000:.0f}")
                print(f"  sensor {sensor} reset_to_first_valid_ms {(first_valid - t_reset) * 1000:.0f}")
            if after_gap is not None:
                print(f"  sensor {sensor} reset_to_valid_after_gap_ms {(after_gap - t_reset) * 1000:.0f}")

    print(f"disconnects: {len(disconnects)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")
        raise
