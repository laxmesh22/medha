"""BLE link to the Auri straps. Runs in its own thread so the camera loop never waits on it.

``bleak`` is imported only when ``start()`` runs, so ``--straps off`` (the default) works without it.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .protocol import (
    CMD_IMU_RESET, CMD_RATE, CMD_STREAM, CMD_TIME_PING, COMMAND_UUID, DEVICE_NAMES, IMU_DATA_UUID,
    RAW_DATA_UUID, SENSOR_NAMES, SERVICE_UUID, STATUS_UUID, Status, command, decode_imu_data, decode_raw,
    decode_status,
)

log = logging.getLogger(__name__)

STALE_MS = 200
CLOCK_WINDOW_MS = 30_000
RATE_WINDOW_MS = 1_000
PING_EVERY_S = 5.0
WRITE_TIMEOUT_S = 1.0
RECONNECT_S = (1.0, 2.0, 5.0, 10.0)  # capped at 10 s; a missing sensor does not spin faster
STREAM_HZ = 50  # 100 Hz overruns the strap and the next GATT write returns Insufficient Resource
LINK_TEST_SENSOR = 15
SLOT_IDS = {"upper_arm": 0, "forearm": 1, "trunk": 2}


class ClockOffset:
    """``offset_ms = host_rx_ms - t_ms``, the minimum over the last ``window_ms``.

    A rising minimum is kept once the old low sample falls out of the window (clock drift).
    """

    def __init__(self, window_ms: float = CLOCK_WINDOW_MS):
        self.window_ms = window_ms
        self._obs: list[tuple[float, float]] = []
        self.offset_ms: Optional[float] = None

    def observe(self, host_rx_ms: float, t_device_ms: int) -> Optional[float]:
        self._obs.append((host_rx_ms, float(host_rx_ms) - float(t_device_ms)))
        cutoff = host_rx_ms - self.window_ms
        self._obs = [item for item in self._obs if item[0] >= cutoff]
        self.offset_ms = min(item[1] for item in self._obs)
        return self.offset_ms


@dataclass
class SensorSample:
    quat: tuple[float, float, float, float]
    t_device_ms: int
    valid: bool
    accuracy: int
    reset: bool
    seq: int
    gyro: Optional[tuple[float, float, float]] = None
    gravity: Optional[tuple[float, float, float]] = None


def sensor_view(sample: Optional[SensorSample], now_ms: float, offset_ms: Optional[float]) -> dict:
    """Pose fields are None when the sample is missing, stale, or valid=0. Never the last good value."""
    view = {
        "quat": None,
        "gyro": None,
        "gravity": None,
        "t_ms": None,
        "valid": False if sample is None else sample.valid,
        "accuracy": None if sample is None else sample.accuracy,
        "reset": False if sample is None else sample.reset,
        "age_ms": None,
        "available": False,
        "seq": None if sample is None else sample.seq,
    }
    if sample is None or offset_ms is None:
        return view
    host_t = float(sample.t_device_ms) + offset_ms
    age = now_ms - host_t
    view["age_ms"] = round(age, 1)
    if age > STALE_MS or not sample.valid:
        return view
    view["quat"] = [round(v, 5) for v in sample.quat]
    view["gyro"] = None if sample.gyro is None else [round(v, 5) for v in sample.gyro]
    view["gravity"] = None if sample.gravity is None else [round(v, 5) for v in sample.gravity]
    view["t_ms"] = round(host_t, 1)
    view["available"] = True
    return view


def choose_address(candidates: list[tuple[str, Optional[Status]]]) -> Optional[str]:
    """Addresses that share one BLE name.

    One device is used as-is. Several: use one whose STATUS has a sensor both present and streaming.
    None of them healthy means connect to none, so a broken twin is not picked silently.
    """
    if len(candidates) == 1:
        return candidates[0][0]
    healthy = [addr for addr, st in candidates if st is not None and set(st.present) & set(st.ok)]
    if not healthy:
        return None
    return healthy[0]


@dataclass
class _Device:
    address: str
    name: Optional[str] = None
    rssi: Optional[int] = None
    connected: bool = False
    clock: ClockOffset = field(default_factory=ClockOffset)
    samples: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)  # sensor id -> deque of (quat, gyro, seq)
    last_seq: dict = field(default_factory=dict)
    seq_gaps: int = 0
    rx_ms: deque = field(default_factory=lambda: deque(maxlen=400))
    status: Optional[Status] = None
    status_hex: str = ""
    hardware: Optional[str] = None
    rtt_ms: Optional[float] = None
    ping: Optional[tuple] = None  # (host_us, sent_ms)
    disconnected_at: Optional[float] = None
    last_reconnect_s: Optional[float] = None
    imu_absent: bool = False


class StrapLink:
    """One asyncio loop per strap, each on its own daemon thread.

    The camera thread reads ``frame_view()``, which never waits on a Bluetooth call.
    ``addresses`` empty means one scanner thread for AURI-ARM / AURI-TRUNK.
    """

    def __init__(self, addresses: Optional[list[str]] = None, slots: Optional[dict] = None):
        self.addresses = [a.strip() for a in (addresses or []) if a.strip()]
        self.mode = "auto" if not self.addresses else ",".join(self.addresses)
        self.slots = {addr.strip().upper(): slot for addr, slot in (slots or {}).items()}
        self._lock = threading.Lock()
        self._devices: dict[str, _Device] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._loops: list[tuple] = []  # (loop, stop event) per strap thread
        self._lock_loops = threading.Lock()
        self._published: dict = {}
        self._published_status: dict = {"enabled": True, "mode": self.mode, "generation": 0, "devices": []}
        self._drop_gen = 0
        self.generation = 0  # bumps on every new connection; a reconnect drops the yaw reference

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        targets = self.addresses or [None]
        for address in targets:
            thread = threading.Thread(
                target=self._thread_main, args=(address,), name=f"strap-{address or 'scan'}", daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock_loops:
            loops = list(self._loops)
        for loop, event in loops:
            loop.call_soon_threadsafe(event.set)
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads = []

    def request_reconnect(self) -> None:
        """Drop every session so the link reconnects. The camera thread does not wait for this."""
        with self._lock:
            self._drop_gen += 1

    def status(self, now_ms: Optional[float] = None) -> dict:
        """Link summary. If a strap callback holds the lock, the previous summary is returned at once."""
        if not self._lock.acquire(blocking=False):
            return self._published_status
        try:
            now = time.time() * 1000.0 if now_ms is None else now_ms
            self._published_status = {
                "enabled": True, "mode": self.mode, "generation": self.generation,
                "devices": [self._device_view(dev, now) for dev in self._devices.values()],
            }
            return self._published_status
        finally:
            self._lock.release()

    def snapshot(self, now_ms: Optional[float] = None) -> dict:
        """Latest sample per sensor name. Unavailable sensors have None pose fields."""
        now = time.time() * 1000.0 if now_ms is None else now_ms
        with self._lock:
            return self._merged(now)

    def frame_view(self) -> dict:
        """What the camera thread reads. Never waits on BLE or on a lock a strap callback holds."""
        if not self._lock.acquire(blocking=False):
            return self._published
        try:
            self._published = self._merged(time.time() * 1000.0)
            return self._published
        finally:
            self._lock.release()

    def _merged(self, now: float) -> dict:
        merged: dict = {}
        for dev in self._devices.values():
            for name, sensor in self._device_view(dev, now)["sensors"].items():
                prev = merged.get(name)
                if prev is None or (sensor.get("available") and not prev.get("available")):
                    merged[name] = sensor
        return merged

    def discard_pending(self) -> None:
        """Drop samples already received, so a calibration window starts from now."""
        with self._lock:
            for dev in self._devices.values():
                for hist in dev.history.values():
                    hist.clear()

    def drain_new(self) -> dict:
        """Samples since the last drain, keyed by sensor name. The latest snapshot is unchanged."""
        out: dict = {}
        with self._lock:
            for dev in self._devices.values():
                for sid, hist in dev.history.items():
                    name = SENSOR_NAMES.get(sid)
                    if name is None or not hist:
                        continue
                    rows = out.setdefault(name, [])
                    while hist:
                        rows.append(hist.popleft())
        return out

    def _device_view(self, dev: _Device, now: float) -> dict:
        while dev.rx_ms and now - dev.rx_ms[0] > RATE_WINDOW_MS:
            dev.rx_ms.popleft()
        st = dev.status
        sensors = {}
        ids = set(dev.samples)
        if st is not None:
            ids.update(self._placed(dev.address, sid) for sid in st.present)
        for sid in sorted(s for s in ids if s != LINK_TEST_SENSOR):
            name = SENSOR_NAMES.get(sid, str(sid))
            sensors[name] = sensor_view(dev.samples.get(sid), now, dev.clock.offset_ms)
        return {
            "name": dev.name,
            "address": dev.address,
            "slot": self.slots.get(dev.address.upper()),
            "connected": dev.connected,
            "link": "connected" if dev.connected else "searching",
            "rssi": dev.rssi,
            "packet_rate_hz": float(len(dev.rx_ms)),
            "seq_gaps": dev.seq_gaps,
            "notify_drops": None if st is None else st.notify_drops,
            "i2c_errors": None if st is None else st.i2c_errors,
            "battery_mv": None if st is None else st.battery_mv,
            "firmware": None if st is None else st.firmware,
            "protocol": None if st is None else st.protocol,
            "rate_hz": None if st is None else st.rate_hz,
            "streaming": None if st is None else st.streaming,
            "present": [] if st is None else list(st.present),
            "ok": [] if st is None else list(st.ok),
            "offset_ms": None if dev.clock.offset_ms is None else round(dev.clock.offset_ms, 1),
            "rtt_ms": None if dev.rtt_ms is None else round(dev.rtt_ms, 1),
            "status_hex": dev.status_hex,
            "hardware": dev.hardware,
            "last_reconnect_s": dev.last_reconnect_s,
            "sensors": sensors,
        }

    def _placed(self, address: str, sensor: int) -> int:
        """Both pods ship as unit 1 and both emit sensor 0. A slot override gives each its own name."""
        if sensor == LINK_TEST_SENSOR:
            return sensor
        slot = self.slots.get(address.upper())
        if slot is None:
            return sensor
        return SLOT_IDS[slot]

    def _ensure(self, address: str, name: Optional[str], rssi: Optional[int]) -> _Device:
        dev = self._devices.get(address)
        if dev is None:
            dev = _Device(address=address, name=name, rssi=rssi)
            self._devices[address] = dev
        if name:
            dev.name = name
        if rssi is not None:
            dev.rssi = rssi
        return dev

    def _note_rx(self, dev: _Device, sensor: int, seq: int, host_rx: float, t_device: int) -> None:
        dev.clock.observe(host_rx, t_device)
        dev.rx_ms.append(host_rx)
        if sensor == LINK_TEST_SENSOR:
            return
        prev = dev.last_seq.get(sensor)
        dev.last_seq[sensor] = seq
        if prev is not None:
            step = (seq - prev) & 0xFFFF
            if step > 1:
                dev.seq_gaps += step - 1

    def _on_imu(self, address: str, data: bytes) -> None:
        try:
            imu, raw = decode_imu_data(data)
        except ValueError:
            log.warning("strap %s bad IMU_DATA (%d bytes)", address, len(data))
            return
        now = time.time() * 1000.0
        sensor = self._placed(address, imu.sensor)
        with self._lock:
            dev = self._devices.get(address)
            if dev is None:
                return
            self._note_rx(dev, sensor, imu.seq, now, imu.t_ms)
            if sensor == LINK_TEST_SENSOR:
                return
            slot = dev.samples.get(sensor)
            if slot is None:
                slot = SensorSample(imu.quat, imu.t_ms, imu.valid, imu.accuracy, imu.reset, imu.seq)
                dev.samples[sensor] = slot
            else:
                slot.quat, slot.t_device_ms = imu.quat, imu.t_ms
                slot.valid, slot.accuracy, slot.reset, slot.seq = imu.valid, imu.accuracy, imu.reset, imu.seq
            if raw is not None:
                slot.gyro, slot.gravity = raw.gyro, raw.gravity
            if imu.valid:
                dev.history.setdefault(sensor, deque(maxlen=800)).append((slot.quat, slot.gyro, imu.seq))

    def _on_raw(self, address: str, data: bytes) -> None:
        try:
            raw = decode_raw(data)
        except ValueError:
            log.warning("strap %s bad RAW_DATA (%d bytes)", address, len(data))
            return
        now = time.time() * 1000.0
        sensor = self._placed(address, raw.sensor)
        with self._lock:
            dev = self._devices.get(address)
            if dev is None or sensor == LINK_TEST_SENSOR:
                return
            dev.clock.observe(now, raw.t_ms)
            slot = dev.samples.get(sensor)
            if slot is None:
                return
            slot.gyro, slot.gravity = raw.gyro, raw.gravity

    def _on_status(self, address: str, data: bytes) -> None:
        try:
            obj = decode_status(data)
        except ValueError:
            log.warning("strap %s bad STATUS (%d bytes)", address, len(data))
            return
        now = time.time() * 1000.0
        with self._lock:
            dev = self._devices.get(address)
            if dev is None:
                return
            if isinstance(obj, Status):
                dev.status = obj
                if obj.present:
                    dev.imu_absent = False
                    dev.hardware = None
                if dev.name is None:
                    dev.name = DEVICE_NAMES.get(obj.unit)
                return
            dev.clock.observe(now, obj.t_ms)
            if dev.ping is not None and dev.ping[0] == obj.host_us:
                dev.rtt_ms = now - dev.ping[1]

    def _thread_main(self, address: Optional[str]) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError:
            log.error("bleak is not installed. From hub/: pip install -e \".[straps]\"")
            return
        asyncio.run(self._amain(address))

    async def _amain(self, address: Optional[str]) -> None:
        """One event loop per strap. A write that stalls on one board cannot run on the camera thread."""
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        with self._lock_loops:
            self._loops.append((loop, stop))
        try:
            if address is not None:
                await self._device_loop(address, None, None, stop)
                return
            while not self._stop.is_set():
                found = await self._scan()
                chosen = await self._pick(found)
                if not chosen:
                    log.warning("strap auto: no device selected")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=RECONNECT_S[-1])
                        return
                    except asyncio.TimeoutError:
                        continue
                tasks = [
                    asyncio.create_task(self._device_loop(d["address"], d["name"], d["rssi"], stop))
                    for d in chosen
                ]
                await stop.wait()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                return
        finally:
            with self._lock_loops:
                self._loops = [item for item in self._loops if item[0] is not loop]

    async def _scan(self) -> list[dict]:
        from bleak import BleakScanner

        discovered = await BleakScanner.discover(timeout=6.0, return_adv=True)
        want = SERVICE_UUID.lower()
        names = set(DEVICE_NAMES.values())
        out = []
        for dev, adv in discovered.values():
            name = adv.local_name or dev.name or ""
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            if name in names or want in uuids:
                out.append({"address": dev.address, "name": name or None, "rssi": getattr(adv, "rssi", None)})
        log.info("strap scan found %s", [(d["name"], d["address"], d["rssi"]) for d in out])
        return out

    async def _pick(self, found: list[dict]) -> list[dict]:
        by_name: dict[str, list[dict]] = {}
        for dev in found:
            by_name.setdefault(dev["name"] or dev["address"], []).append(dev)
        chosen = []
        for name, group in by_name.items():
            if len(group) == 1:
                chosen.append(group[0])
                continue
            probed = []
            for dev in group:
                status = await self._read_status(dev["address"])
                probed.append((dev, status))
                log.info("strap candidate %s %s present=%s ok=%s", name, dev["address"],
                         None if status is None else status.present, None if status is None else status.ok)
            pick = choose_address([(dev["address"], st) for dev, st in probed])
            if pick is None:
                log.warning("strap %s: %d devices, none present and ok; not connecting", name, len(group))
                continue
            log.info("strap chose %s for %s", pick, name)
            chosen.append(next(dev for dev, _st in probed if dev["address"] == pick))
        return chosen

    async def _read_status(self, address: str) -> Optional[Status]:
        from bleak import BleakClient

        try:
            async with BleakClient(address, timeout=10.0) as client:
                data = bytes(await client.read_gatt_char(STATUS_UUID))
            obj = decode_status(data)
        except Exception:
            log.warning("strap status read failed for %s", address, exc_info=True)
            return None
        return obj if isinstance(obj, Status) else None

    async def _device_loop(self, address: str, name: Optional[str], rssi: Optional[int], stop: asyncio.Event) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._session(address, name, rssi, stop)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("strap session %s", address)
            if self._stop.is_set():
                break
            delay = RECONNECT_S[min(attempt, len(RECONNECT_S) - 1)]
            attempt += 1
            log.info("strap %s reconnect in %ss", address, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass

    def _drop_requested(self, seen: int) -> int:
        with self._lock:
            gen = self._drop_gen
        return gen if gen != seen else seen

    async def _session(self, address: str, name: Optional[str], rssi: Optional[int], stop: asyncio.Event) -> None:
        from bleak import BleakClient

        disconnected = asyncio.Event()

        def on_disc(_client) -> None:
            disconnected.set()

        with self._lock:
            dev = self._ensure(address, name, rssi)
            dev.connected = False
            seen_drop = self._drop_gen
        async with BleakClient(address, disconnected_callback=on_disc, timeout=15.0) as client:
            with self._lock:
                dev = self._ensure(address, name, rssi)
                dev.connected = True
                if dev.disconnected_at is not None:
                    dev.last_reconnect_s = round(time.time() - dev.disconnected_at, 2)
                dev.disconnected_at = None
                # A new connection starts the sequence at 0. Keeping the old seq
                # counts one wrap (about 65535) as lost packets.
                dev.last_seq.clear()
                dev.seq_gaps = 0
                self.generation += 1
                absent = dev.imu_absent
            log.info("strap connected %s (generation %s)", address, self.generation)
            await client.start_notify(IMU_DATA_UUID, lambda _s, data: self._on_imu(address, bytes(data)))
            await client.start_notify(RAW_DATA_UUID, lambda _s, data: self._on_raw(address, bytes(data)))
            await client.start_notify(STATUS_UUID, lambda _s, data: self._on_status(address, bytes(data)))
            status = await self._read_status_live(client, address)
            if status is not None and status.rate_hz != STREAM_HZ:
                await self._write(client, address, "rate 50", command(CMD_RATE, STREAM_HZ))
                await asyncio.sleep(0.3)
                status = await self._read_status_live(client, address)
            if not absent and (status is None or not status.present):
                await self._recover_imu(client, address)
            await self._ping(client, address)
            while not self._stop.is_set() and not disconnected.is_set():
                if self._drop_requested(seen_drop) != seen_drop:
                    log.info("strap %s simulated disconnect", address)
                    break
                waiter = asyncio.create_task(disconnected.wait())
                stopper = asyncio.create_task(stop.wait())
                sleep = asyncio.create_task(asyncio.sleep(PING_EVERY_S))
                done, pending = await asyncio.wait({waiter, stopper, sleep}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if waiter in done or stopper in done or self._stop.is_set():
                    break
                if self._drop_requested(seen_drop) != seen_drop:
                    log.info("strap %s simulated disconnect", address)
                    break
                await self._ping(client, address)
        with self._lock:
            dev = self._devices.get(address)
            if dev is not None:
                dev.connected = False
                dev.disconnected_at = time.time()
        log.info("strap disconnected %s", address)

    async def _read_status_live(self, client, address: str) -> Optional[Status]:
        try:
            raw = bytes(await asyncio.wait_for(client.read_gatt_char(STATUS_UUID), timeout=WRITE_TIMEOUT_S))
        except Exception as exc:
            log.warning("strap %s STATUS read failed: %s", address, exc)
            return None
        with self._lock:
            dev = self._devices.get(address)
            if dev is not None:
                dev.status_hex = raw.hex()
        log.info("strap %s STATUS %s", address, raw.hex())
        self._on_status(address, raw)
        with self._lock:
            dev = self._devices.get(address)
            return None if dev is None else dev.status

    async def _recover_imu(self, client, address: str) -> None:
        """Present bit empty: reset sensor 0 and turn the stream on, once, then once more. Then stop."""
        for attempt in (1, 2):
            log.info("strap %s present empty; IMU reset + stream on, try %s", address, attempt)
            await self._write(client, address, "imu reset", command(CMD_IMU_RESET, 0x01))
            await self._write(client, address, "stream on", command(CMD_STREAM, 1))
            await asyncio.sleep(1.2)
            status = await self._read_status_live(client, address)
            if status is not None and status.present:
                log.info("strap %s sensor present after reset: %s", address, status.present)
                return
        note = "hardware: power-cycle board 2 / check BNO wiring" if address.upper() == "14:63:93:BD:B4:7A" \
            else f"hardware: power-cycle {address} / check BNO wiring"
        with self._lock:
            dev = self._devices.get(address)
            if dev is not None:
                dev.imu_absent = True
                dev.hardware = note
        log.warning("%s (%s)", note, address)

    async def _write(self, client, address: str, what: str, payload: bytes) -> bool:
        try:
            await asyncio.wait_for(
                client.write_gatt_char(COMMAND_UUID, payload, response=True), timeout=WRITE_TIMEOUT_S,
            )
            return True
        except Exception as exc:
            log.warning("strap %s %s failed: %s", address, what, exc)
            return False

    async def _ping(self, client, address: str) -> None:
        host_us = time.time_ns() // 1000
        sent = time.time() * 1000.0
        with self._lock:
            dev = self._devices.get(address)
            if dev is not None:
                dev.ping = (host_us, sent)
        await self._write(client, address, "time ping", command(CMD_TIME_PING, host_us))
