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
    CMD_TIME_PING, COMMAND_UUID, DEVICE_NAMES, IMU_DATA_UUID, RAW_DATA_UUID, SENSOR_NAMES, SERVICE_UUID,
    STATUS_UUID, Status, command, decode_imu_data, decode_raw, decode_status,
)

log = logging.getLogger(__name__)

STALE_MS = 200
CLOCK_WINDOW_MS = 30_000
RATE_WINDOW_MS = 1_000
PING_EVERY_S = 5.0
RECONNECT_S = (1, 2, 5)
LINK_TEST_SENSOR = 15


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
    last_seq: dict = field(default_factory=dict)
    seq_gaps: int = 0
    rx_ms: deque = field(default_factory=lambda: deque(maxlen=400))
    status: Optional[Status] = None
    rtt_ms: Optional[float] = None
    ping: Optional[tuple] = None  # (host_us, sent_ms)


class StrapLink:
    """One asyncio loop, daemon thread. ``addresses`` empty means scan for AURI-ARM / AURI-TRUNK."""

    def __init__(self, addresses: Optional[list[str]] = None):
        self.addresses = [a.strip() for a in (addresses or []) if a.strip()]
        self.mode = "auto" if not self.addresses else ",".join(self.addresses)
        self._lock = threading.Lock()
        self._devices: dict[str, _Device] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_stop: Optional[asyncio.Event] = None
        self.generation = 0  # bumps on every new connection; a reconnect drops the yaw reference

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="strap-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop, event = self._loop, self._async_stop
        if loop is not None and event is not None:
            loop.call_soon_threadsafe(event.set)
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def status(self, now_ms: Optional[float] = None) -> dict:
        now = time.time() * 1000.0 if now_ms is None else now_ms
        with self._lock:
            devices = [self._device_view(dev, now) for dev in self._devices.values()]
        return {"enabled": True, "mode": self.mode, "generation": self.generation, "devices": devices}

    def snapshot(self, now_ms: Optional[float] = None) -> dict:
        """Latest sample per sensor name. Unavailable sensors have None pose fields."""
        now = time.time() * 1000.0 if now_ms is None else now_ms
        with self._lock:
            merged: dict = {}
            for dev in self._devices.values():
                for name, sensor in self._device_view(dev, now)["sensors"].items():
                    prev = merged.get(name)
                    if prev is None or (sensor.get("available") and not prev.get("available")):
                        merged[name] = sensor
            return merged

    def _device_view(self, dev: _Device, now: float) -> dict:
        while dev.rx_ms and now - dev.rx_ms[0] > RATE_WINDOW_MS:
            dev.rx_ms.popleft()
        st = dev.status
        sensors = {}
        ids = set(dev.samples) | (set(st.present) if st else set())
        for sid in sorted(s for s in ids if s != LINK_TEST_SENSOR):
            name = SENSOR_NAMES.get(sid, str(sid))
            sensors[name] = sensor_view(dev.samples.get(sid), now, dev.clock.offset_ms)
        return {
            "name": dev.name,
            "address": dev.address,
            "connected": dev.connected,
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
            "sensors": sensors,
        }

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
        with self._lock:
            dev = self._devices.get(address)
            if dev is None:
                return
            self._note_rx(dev, imu.sensor, imu.seq, now, imu.t_ms)
            if imu.sensor == LINK_TEST_SENSOR:
                return
            slot = dev.samples.get(imu.sensor)
            if slot is None:
                slot = SensorSample(imu.quat, imu.t_ms, imu.valid, imu.accuracy, imu.reset, imu.seq)
                dev.samples[imu.sensor] = slot
            else:
                slot.quat, slot.t_device_ms = imu.quat, imu.t_ms
                slot.valid, slot.accuracy, slot.reset, slot.seq = imu.valid, imu.accuracy, imu.reset, imu.seq
            if raw is not None:
                slot.gyro, slot.gravity = raw.gyro, raw.gravity

    def _on_raw(self, address: str, data: bytes) -> None:
        try:
            raw = decode_raw(data)
        except ValueError:
            log.warning("strap %s bad RAW_DATA (%d bytes)", address, len(data))
            return
        now = time.time() * 1000.0
        with self._lock:
            dev = self._devices.get(address)
            if dev is None or raw.sensor == LINK_TEST_SENSOR:
                return
            dev.clock.observe(now, raw.t_ms)
            slot = dev.samples.get(raw.sensor)
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
                if dev.name is None:
                    dev.name = DEVICE_NAMES.get(obj.unit)
                return
            dev.clock.observe(now, obj.t_ms)
            if dev.ping is not None and dev.ping[0] == obj.host_us:
                dev.rtt_ms = now - dev.ping[1]

    def _thread_main(self) -> None:
        try:
            import bleak  # noqa: F401
        except ImportError:
            log.error("bleak is not installed. From hub/: pip install -e \".[straps]\"")
            return
        asyncio.run(self._amain())

    async def _amain(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._async_stop = asyncio.Event()
        if self.addresses:
            await asyncio.gather(*(self._device_loop(a, None, None) for a in self.addresses))
            return
        while not self._stop.is_set():
            found = await self._scan()
            chosen = await self._pick(found)
            if not chosen:
                log.warning("strap auto: no device selected")
                try:
                    await asyncio.wait_for(self._async_stop.wait(), timeout=5)
                    return
                except asyncio.TimeoutError:
                    continue
            tasks = [asyncio.create_task(self._device_loop(d["address"], d["name"], d["rssi"])) for d in chosen]
            await self._async_stop.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return

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

    async def _device_loop(self, address: str, name: Optional[str], rssi: Optional[int]) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._session(address, name, rssi)
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
                await asyncio.wait_for(self._async_stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass

    async def _session(self, address: str, name: Optional[str], rssi: Optional[int]) -> None:
        from bleak import BleakClient

        disconnected = asyncio.Event()

        def on_disc(_client) -> None:
            disconnected.set()

        with self._lock:
            dev = self._ensure(address, name, rssi)
            dev.connected = False
        async with BleakClient(address, disconnected_callback=on_disc, timeout=15.0) as client:
            with self._lock:
                self._ensure(address, name, rssi).connected = True
                self.generation += 1
            log.info("strap connected %s (generation %s)", address, self.generation)
            await client.start_notify(IMU_DATA_UUID, lambda _s, data: self._on_imu(address, bytes(data)))
            await client.start_notify(RAW_DATA_UUID, lambda _s, data: self._on_raw(address, bytes(data)))
            await client.start_notify(STATUS_UUID, lambda _s, data: self._on_status(address, bytes(data)))
            try:
                self._on_status(address, bytes(await client.read_gatt_char(STATUS_UUID)))
            except Exception:
                log.warning("strap initial STATUS read failed for %s", address, exc_info=True)
            await self._ping(client, address)
            while not self._stop.is_set() and not disconnected.is_set():
                waiter = asyncio.create_task(disconnected.wait())
                stopper = asyncio.create_task(self._async_stop.wait())
                sleep = asyncio.create_task(asyncio.sleep(PING_EVERY_S))
                done, pending = await asyncio.wait({waiter, stopper, sleep}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if waiter in done or stopper in done or self._stop.is_set():
                    break
                await self._ping(client, address)
        with self._lock:
            if address in self._devices:
                self._devices[address].connected = False
        log.info("strap disconnected %s", address)

    async def _ping(self, client, address: str) -> None:
        host_us = time.time_ns() // 1000
        sent = time.time() * 1000.0
        with self._lock:
            dev = self._devices.get(address)
            if dev is not None:
                dev.ping = (host_us, sent)
        try:
            await client.write_gatt_char(COMMAND_UUID, command(CMD_TIME_PING, host_us), response=True)
        except Exception:
            log.warning("strap time ping failed for %s", address, exc_info=True)
