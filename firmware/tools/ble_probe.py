"""Talk to a flashed Auri strap over BLE and print link statistics.

Imports firmware/protocol/auri_ble.py. Does not copy it.
Usage: ble_probe.py [seconds]
The seconds argument is the first listen window (default 50 Hz). Command tests follow it.
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "protocol"))
import auri_ble  # noqa: E402

NAMES = ("AURI-ARM", "AURI-TRUNK")


class Bucket:
    def __init__(self) -> None:
        self.packets = 0
        self.valid = 0
        self.seqs: list[int] = []
        self.t0: float | None = None
        self.t1: float | None = None

    def add(self, seq: int, valid: bool) -> None:
        now = time.perf_counter()
        if self.t0 is None:
            self.t0 = now
        self.t1 = now
        self.packets += 1
        self.valid += int(valid)
        self.seqs.append(seq)

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


async def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    from bleak import BleakClient, BleakScanner

    want = auri_ble.SERVICE_UUID.lower()
    disconnects: list[str] = []

    def match(device, adv) -> bool:
        name = (adv.local_name or device.name or "")
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        return name in NAMES or want in uuids

    print(f"scanning {seconds:.0f}s window requested; looking for {NAMES} or {auri_ble.SERVICE_UUID}")
    device = await BleakScanner.find_device_by_filter(match, timeout=15.0)
    if device is None:
        print("scan: no AURI-ARM / AURI-TRUNK and no matching service UUID")
        return 1
    print(f"found name={device.name!r} address={device.address}")

    buckets: dict[int, Bucket] = {}
    raw_count = 0
    pongs: dict[int, asyncio.Future] = {}
    statuses: list[auri_ble.Status] = []

    def on_disconnect(_client) -> None:
        disconnects.append("disconnected")
        print("event: disconnected")

    def take(data: bytearray) -> bytes:
        return bytes(data)

    def on_imu(_sender, data: bytearray) -> None:
        sample = auri_ble.decode_imu(take(data))
        buckets.setdefault(sample.sensor, Bucket()).add(sample.seq, sample.valid)

    def on_raw(_sender, data: bytearray) -> None:
        nonlocal raw_count
        auri_ble.decode_raw(take(data))
        raw_count += 1

    def on_status(_sender, data: bytearray) -> None:
        obj = auri_ble.decode_status(take(data))
        if isinstance(obj, auri_ble.Pong):
            fut = pongs.get(obj.host_us)
            if fut is not None and not fut.done():
                fut.set_result((time.perf_counter(), obj))
        else:
            statuses.append(obj)

    async with BleakClient(device, disconnected_callback=on_disconnect) as client:
        print(f"connected mtu={client.mtu_size}")
        raw_status = bytes(await client.read_gatt_char(auri_ble.STATUS_UUID))
        status = auri_ble.decode_status(raw_status)
        print(f"STATUS read: {status}")
        await client.start_notify(auri_ble.IMU_DATA_UUID, on_imu)
        await client.start_notify(auri_ble.RAW_DATA_UUID, on_raw)
        await client.start_notify(auri_ble.STATUS_UUID, on_status)

        buckets.clear()
        await asyncio.sleep(seconds)
        print(f"raw packets in first window: {raw_count}")
        report(f"listen {seconds:.0f}s at default rate", buckets)

        rtts: list[float] = []
        offsets: list[float] = []
        for i in range(10):
            host_us = time.time_ns() // 1000
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            pongs[host_us] = fut
            t0 = time.perf_counter()
            await client.write_gatt_char(
                auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_TIME_PING, host_us), response=True
            )
            try:
                t1, pong = await asyncio.wait_for(fut, timeout=1.0)
            except asyncio.TimeoutError:
                print(f"ping {i} timeout host_us={host_us}")
                await asyncio.sleep(0.2)
                continue
            rtt_ms = (t1 - t0) * 1000.0
            host_rx_us = host_us + int((t1 - t0) * 1_000_000)
            offset_ms = host_rx_us / 1000.0 - pong.t_ms
            rtts.append(rtt_ms)
            offsets.append(offset_ms)
            print(f"ping {i} rtt_ms {rtt_ms:.2f} t_ms {pong.t_ms} offset_ms {offset_ms:.2f}")
            await asyncio.sleep(0.2)
        if rtts:
            best = min(range(len(rtts)), key=lambda k: rtts[k])
            print(
                f"rtt min {min(rtts):.2f} ms median {statistics.median(rtts):.2f} ms "
                f"offset_at_min_rtt {offsets[best]:.2f} ms (lower envelope of host_rx_us/1000 - t_ms)"
            )
        else:
            print("no pongs")

        async def listen(label: str, dur: float) -> None:
            nonlocal raw_count
            buckets.clear()
            raw_count = 0
            await asyncio.sleep(dur)
            print(f"raw packets during {label}: {raw_count}")
            report(label, buckets)

        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_RATE, 100), response=True)
        await listen("rate 100 Hz for 5s", 5.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_RATE, 50), response=True)
        await listen("rate 50 Hz for 5s", 5.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_STREAM, 0), response=True)
        await listen("stream off for 3s", 3.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_STREAM, 1), response=True)
        await listen("stream on for 2s", 2.0)
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_HAPTIC, 1), response=True)
        await asyncio.sleep(0.4)
        print(f"haptic 1 sent; still connected={client.is_connected}")
        await client.write_gatt_char(auri_ble.COMMAND_UUID, auri_ble.command(auri_ble.CMD_TARE), response=True)
        await asyncio.sleep(0.4)
        print(f"tare sent; still connected={client.is_connected}")
        if statuses:
            print(f"last STATUS notify: {statuses[-1]}")

    print(f"disconnects: {len(disconnects)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")
        raise
